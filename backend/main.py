import json
import html
import hmac
import math
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL
import social
import httpx
from apscheduler.schedulers.background import BackgroundScheduler

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CLIP_DIR = DATA_DIR / "clips"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
PROJECTS_FILE = DATA_DIR / "projects.json"
MAX_VIDEO_SIZE = 2 * 1024 * 1024 * 1024
TRANSCRIPT_CHUNK_SECONDS = 1200
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"}
SUPPORTED_URL_HOSTS = {
    "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "drive.google.com",
    "docs.google.com", "dropbox.com", "dl.dropboxusercontent.com",
}
PROJECTS_LOCK = threading.RLock()

for directory in (UPLOAD_DIR, CLIP_DIR, TRANSCRIPT_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ClipForgeAI API", version="0.3.0")
scheduler = BackgroundScheduler(timezone="UTC")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media/clips", StaticFiles(directory=CLIP_DIR), name="clips")
app.mount("/media/transcripts", StaticFiles(directory=TRANSCRIPT_DIR), name="transcripts")


def run_scheduled_publishing() -> None:
    social.publish_due(signed_public_media_for_video)


@app.on_event("startup")
def start_publishing_worker() -> None:
    social.initialize()
    social.recover_interrupted_posts()
    if not scheduler.running:
        scheduler.add_job(run_scheduled_publishing, "interval", seconds=20, id="publish-due-posts", max_instances=1, coalesce=True)
        scheduler.start()


@app.on_event("shutdown")
def stop_publishing_worker() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def valid_session_cookie(value: str) -> bool:
    try:
        expiry_text, signature = value.split(".", 1)
        secret = os.getenv("APP_SESSION_SECRET", "")
        expected = hmac.new(secret.encode(), expiry_text.encode(), "sha256").hexdigest()
        return bool(len(secret) >= 32 and secret != "replace_with_random_secret_at_least_32_chars" and int(expiry_text) > time.time() and hmac.compare_digest(signature, expected))
    except (ValueError, TypeError):
        return False


def sign_public_media(path: str) -> str:
    secret = os.getenv("MEDIA_SIGNING_KEY") or os.getenv("APP_SESSION_SECRET", "")
    base = (os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
    if not secret or not base.startswith("https://"):
        raise RuntimeError("Set APP_BASE_URL and a media signing secret before publishing hosted media.")
    expires = str(int(time.time()) + 60 * 60 * 24)
    signature = hmac.new(secret.encode(), f"{path}:{expires}".encode(), "sha256").hexdigest()
    return f"{base}{path}?expires={expires}&signature={signature}"


def signed_public_media_for_video(video_path: str) -> str:
    return sign_public_media(f"/media/clips/{Path(video_path).name}")


def valid_public_media(request: Request) -> bool:
    secret = os.getenv("MEDIA_SIGNING_KEY") or os.getenv("APP_SESSION_SECRET", "")
    expires = request.query_params.get("expires", "")
    signature = request.query_params.get("signature", "")
    try:
        if int(expires) <= time.time() or not secret:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{request.url.path}:{expires}".encode(), "sha256").hexdigest()
    return hmac.compare_digest(signature, expected)


@app.middleware("http")
async def require_workspace_login(request: Request, call_next):
    public_paths = {"/api/auth/login", "/api/auth/session", "/api/health"}
    protected = request.url.path.startswith("/api/") and request.url.path not in public_paths
    protected = protected or (request.url.path.startswith("/media/") and not valid_public_media(request))
    if protected:
        if not valid_session_cookie(request.cookies.get("clipforge_session", "")):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Sign in to your ClipforgeAI workspace."}, status_code=401)
    return await call_next(request)

ProjectStatus = Literal["queued", "processing", "completed", "awaiting-source", "failed"]


@app.post("/api/auth/login")
def login(request: Request, response: Response, password: str = Form(...)) -> dict[str, bool]:
    expected = os.getenv("APP_PASSWORD", "")
    session_secret = os.getenv("APP_SESSION_SECRET", "")
    if not expected or len(expected) < 12 or expected == "replace_with_a_long_private_password" or len(session_secret) < 32 or session_secret == "replace_with_random_secret_at_least_32_chars":
        raise HTTPException(status_code=503, detail="Set APP_PASSWORD and a unique APP_SESSION_SECRET before signing in.")
    if not hmac.compare_digest(password, expected):
        raise HTTPException(status_code=401, detail="Incorrect workspace password.")
    expiry_text = str(int(time.time()) + 60 * 60 * 24 * 14)
    signature = hmac.new(session_secret.encode(), expiry_text.encode(), "sha256").hexdigest()
    public_url = os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
    response.set_cookie("clipforge_session", f"{expiry_text}.{signature}", httponly=True, secure=public_url.startswith("https://"), samesite="lax", max_age=60 * 60 * 24 * 14, path="/")
    return {"authenticated": True}


@app.post("/api/auth/logout")
def logout() -> Response:
    response = Response(content=json.dumps({"authenticated": False}), media_type="application/json")
    response.delete_cookie("clipforge_session", path="/")
    return response


@app.get("/api/auth/session")
def auth_session(request: Request) -> dict[str, bool]:
    configured = bool(os.getenv("APP_PASSWORD") and len(os.getenv("APP_PASSWORD", "")) >= 12 and os.getenv("APP_PASSWORD") != "replace_with_a_long_private_password" and len(os.getenv("APP_SESSION_SECRET", "")) >= 32 and os.getenv("APP_SESSION_SECRET") != "replace_with_random_secret_at_least_32_chars")
    return {"authenticated": valid_session_cookie(request.cookies.get("clipforge_session", "")), "configured": configured, "demo_mode": os.getenv("CLIPFORGEAI_DEMO_MODE", "").lower() == "true"}


class Project(BaseModel):
    id: str
    source_type: Literal["upload", "url"]
    source_name: str
    clip_mode: Literal["best-parts", "sequence"]
    clip_duration: int = 30
    status: ProjectStatus
    progress: str | None = None
    created_at: str
    clip_url: str | None = None
    clips: list[dict] = Field(default_factory=list)
    error: str | None = None


class ClipEdit(BaseModel):
    trim_start: float = Field(default=0, ge=0)
    trim_end: float | None = Field(default=None, gt=0)
    aspect_ratio: Literal["9:16", "1:1", "16:9"] = "9:16"


class PublishTarget(BaseModel):
    provider: Literal["youtube", "instagram", "tiktok", "facebook", "x", "linkedin"]
    account_id: str
    privacy_level: Literal["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"] | None = None


class ScheduleRequest(BaseModel):
    targets: list[PublishTarget] = Field(min_length=1)
    cadence: Literal["6-hours", "daily"] = "6-hours"
    first_at: datetime
    caption: str = Field(default="", max_length=2200)


ASPECT_FILTERS = {
    "9:16": "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
    "1:1": "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080",
    "16:9": "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
}


def has_openai_key() -> bool:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return bool(key and key.lower() != "your_api_key_here")


def read_projects() -> list[dict]:
    with PROJECTS_LOCK:
        if not PROJECTS_FILE.exists():
            return []
        try:
            data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []


def write_projects(projects: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    temp_file = PROJECTS_FILE.with_name(f"projects-{threading.get_ident()}.tmp")
    temp_file.write_text(json.dumps(projects, indent=2), encoding="utf-8")
    temp_file.replace(PROJECTS_FILE)


def save_project(project: dict) -> None:
    with PROJECTS_LOCK:
        projects = read_projects()
        projects.append(project)
        write_projects(projects)


def update_project(project_id: str, **changes: object) -> None:
    with PROJECTS_LOCK:
        if not PROJECTS_FILE.exists():
            return
        try:
            projects = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for project in projects:
            if project.get("id") == project_id:
                project.update(changes)
                write_projects(projects)
                return


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    return cleaned or "uploaded-video.mp4"


def get_video_duration(source_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", source_path],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration):
        raise ValueError("Video duration is not available.")
    return duration


def run_ffmpeg_clip(source_path: str, output_path: Path, start: float, length: float, captions_path: Path | None = None) -> bool:
    captions_burned = bool(captions_path and captions_path.is_file())
    video_filter = ASPECT_FILTERS["9:16"]
    if captions_burned:
        relative_captions = captions_path.relative_to(BASE_DIR).as_posix()
        video_filter += f",subtitles={relative_captions}:force_style='FontName=Arial,FontSize=20,Outline=2,Shadow=1,Alignment=2,MarginV=90'"
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(start), "-i", source_path, "-t", str(length),
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac",
            "-movflags", "+faststart", str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
    )
    return captions_burned


def write_clip_captions(project_id: str, clip_number: int, start: float, length: float, segments: list[dict]) -> str | None:
    clip_end = start + length
    cues = []
    for segment in segments:
        cue_start = max(start, float(segment["start"]))
        cue_end = min(clip_end, float(segment["end"]))
        text = html.escape(str(segment.get("text", "")).strip().replace("-->", "→"))
        if cue_end <= cue_start or not text:
            continue
        cues.append((cue_start - start, cue_end - start, text))
    if not cues:
        return None

    def vtt_time(seconds: float) -> str:
        millis = round(seconds * 1000)
        hours, millis = divmod(millis, 3_600_000)
        minutes, millis = divmod(millis, 60_000)
        whole_seconds, millis = divmod(millis, 1000)
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"

    vtt_path = TRANSCRIPT_DIR / f"{project_id}-clip-{clip_number}.vtt"
    content = ["WEBVTT", ""]
    for cue_start, cue_end, text in cues:
        content.extend([f"{vtt_time(cue_start)} --> {vtt_time(cue_end)}", text, ""])
    vtt_path.write_text("\n".join(content), encoding="utf-8")
    return f"/media/transcripts/{vtt_path.name}"


def make_sequence_clips(project_id: str, source_path: str, clip_length: int, transcript_segments: list[dict] | None = None) -> None:
    update_project(project_id, progress="Checking video duration")
    duration = get_video_duration(source_path)
    if duration < 1:
        raise ValueError("The video is too short to create a clip.")
    clips: list[dict] = []
    for index in range(math.ceil(duration / clip_length)):
        update_project(project_id, progress=f"Creating clip {index + 1}")
        start = index * clip_length
        length = min(clip_length, duration - start)
        if length < 1:
            break
        output_path = CLIP_DIR / f"{project_id}-clip-{index + 1}.mp4"
        captions_url = write_clip_captions(project_id, index + 1, start, length, transcript_segments) if transcript_segments is not None else None
        captions_path = TRANSCRIPT_DIR / Path(urlparse(captions_url).path).name if captions_url else None
        captions_burned = False
        try:
            try:
                captions_burned = run_ffmpeg_clip(source_path, output_path, start, length, captions_path)
            except subprocess.CalledProcessError:
                if captions_path is None:
                    raise
                run_ffmpeg_clip(source_path, output_path, start, length)
        except subprocess.CalledProcessError:
            if clips:
                break
            raise
        clip = {
            "number": index + 1,
            "start_seconds": round(start, 1),
            "duration_seconds": round(length, 1),
            "url": f"/media/clips/{output_path.name}",
            "aspect_ratio": "9:16",
            "captions_burned": captions_burned,
        }
        if captions_url:
            clip["captions_url"] = captions_url
        clips.append(clip)
        update_project(project_id, clips=clips)
    if not clips:
        raise ValueError("No clips could be created from this video.")
    update_project(project_id, status="completed", progress="Done", clip_url=clips[0]["url"], clips=clips, error=None)


def transcribe_video_audio(project_id: str, source_path: str) -> list[dict]:
    """Send compressed audio chunks to OpenAI and return their timestamped transcript."""
    update_project(project_id, progress="Extracting audio for transcription")
    pattern = TRANSCRIPT_DIR / f"{project_id}-%03d.mp3"
    audio_files: list[Path] = []
    transcript_segments: list[dict] = []
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", source_path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
                "-f", "segment", "-segment_time", str(TRANSCRIPT_CHUNK_SECONDS), "-reset_timestamps", "1", str(pattern),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        audio_files = sorted(TRANSCRIPT_DIR.glob(f"{project_id}-*.mp3"))
        if not audio_files:
            raise ValueError("Could not extract audio from this video.")
        client = OpenAI()
        for chunk_index, audio_path in enumerate(audio_files):
            update_project(project_id, progress=f"Transcribing audio segment {chunk_index + 1} of {len(audio_files)}")
            with audio_path.open("rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
            for segment in transcript.segments or []:
                transcript_segments.append({
                    "start": round(chunk_index * TRANSCRIPT_CHUNK_SECONDS + segment.start, 2),
                    "end": round(chunk_index * TRANSCRIPT_CHUNK_SECONDS + segment.end, 2),
                    "text": segment.text.strip(),
                })
    finally:
        for audio_path in audio_files or TRANSCRIPT_DIR.glob(f"{project_id}-*.mp3"):
            audio_path.unlink(missing_ok=True)
    if not transcript_segments:
        raise ValueError("No speech was detected. Try Sequence Wise or a video with clear speech.")
    return transcript_segments


def select_highlights(project_id: str, segments: list[dict], video_duration: float, clip_length: int) -> list[dict]:
    update_project(project_id, progress="Selecting highlights")
    client = OpenAI()
    transcript_text = json.dumps(segments, ensure_ascii=False)
    if len(transcript_text) > 120_000:
        transcript_text = transcript_text[:120_000]
    max_clips = min(5, max(1, math.ceil(video_duration / clip_length)))
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_HIGHLIGHT_MODEL", "gpt-4.1-mini"),
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Select compelling, self-contained short-form moments from the timestamped transcript. "
                    "Favor a strong hook, useful insight, humor, emotion, or a surprising payoff. "
                    "Avoid introductions, repeated moments, silence, and overlapping selections. "
                    "For each selection return the timestamp where the clip should begin, leaving enough "
                    "context for its payoff. Use only supplied transcript timestamps. Return only a JSON object "
                    "of the form {\"highlights\":[{\"start_seconds\":0,\"reason\":\"...\"}]}, with no more than the requested count."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "video_duration_seconds": video_duration,
                    "clip_length_seconds": clip_length,
                    "max_highlights": max_clips,
                    "timestamped_transcript": transcript_text,
                }, ensure_ascii=False),
            },
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("OpenAI did not return highlight selections.")
    candidates = json.loads(content).get("highlights", [])
    highlights: list[dict] = []
    for candidate in candidates:
        try:
            start = float(candidate["start_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(start):
            continue
        start = min(max(0.0, start), max(0.0, video_duration - clip_length))
        end = min(video_duration, start + clip_length)
        if end - start < 1 or any(start < item["end_seconds"] and end > item["start_seconds"] for item in highlights):
            continue
        highlights.append({
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "reason": str(candidate.get("reason", "AI-selected highlight"))[:240],
        })
        if len(highlights) >= max_clips:
            break
    if not highlights:
        raise ValueError("The AI could not find a usable highlight. Try Sequence Wise or a different video.")
    return sorted(highlights, key=lambda item: item["start_seconds"])


def make_best_part_clips(project_id: str, source_path: str, clip_length: int, generate_subtitles: bool = False) -> None:
    if not has_openai_key():
        raise ValueError("Best Parts requires an OpenAI API key. Add it to backend/.env and restart the backend.")
    update_project(project_id, progress="Checking video duration")
    duration = get_video_duration(source_path)
    if duration < 1:
        raise ValueError("The video is too short to create a clip.")
    transcript_segments = transcribe_video_audio(project_id, source_path)
    highlights = select_highlights(project_id, transcript_segments, duration, clip_length)
    clips: list[dict] = []
    for index, highlight in enumerate(highlights, start=1):
        update_project(project_id, progress=f"Creating highlight {index} of {len(highlights)}")
        output_path = CLIP_DIR / f"{project_id}-clip-{index}.mp4"
        length = highlight["end_seconds"] - highlight["start_seconds"]
        captions_url = write_clip_captions(project_id, index, highlight["start_seconds"], length, transcript_segments) if generate_subtitles else None
        captions_path = TRANSCRIPT_DIR / Path(urlparse(captions_url).path).name if captions_url else None
        captions_burned = False
        try:
            captions_burned = run_ffmpeg_clip(source_path, output_path, highlight["start_seconds"], length, captions_path)
        except subprocess.CalledProcessError:
            if captions_path is None:
                raise
            run_ffmpeg_clip(source_path, output_path, highlight["start_seconds"], length)
        clips.append({
            "number": index,
            "start_seconds": highlight["start_seconds"],
            "duration_seconds": round(length, 1),
            "reason": highlight["reason"],
            "url": f"/media/clips/{output_path.name}",
            "aspect_ratio": "9:16",
            "captions_burned": captions_burned,
            **({"captions_url": captions_url} if captions_url else {}),
        })
        update_project(project_id, clips=clips)
    update_project(project_id, status="completed", progress="Done", clip_url=clips[0]["url"], clips=clips, error=None)


def process_video(project_id: str, source_path: str, clip_mode: str, clip_length: int, generate_subtitles: bool = False) -> None:
    update_project(project_id, status="processing", progress="Starting video processing", error=None)
    try:
        if clip_mode == "best-parts":
            make_best_part_clips(project_id, source_path, clip_length, generate_subtitles)
        else:
            transcript_segments = transcribe_video_audio(project_id, source_path) if generate_subtitles else None
            make_sequence_clips(project_id, source_path, clip_length, transcript_segments)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        message = str(detail or error).strip()
        if "ffmpeg" in str(error).lower() or "ffprobe" in str(error).lower() or isinstance(error, FileNotFoundError):
            message = "FFmpeg and ffprobe are required. Install FFmpeg and make sure both commands are on PATH."
        update_project(project_id, status="failed", progress="Failed", error=message[:500] or "Video processing failed.")
    except (OpenAIError, ValueError, json.JSONDecodeError) as error:
        message = str(error).strip() or "Video processing failed."
        update_project(project_id, status="failed", progress="Failed", error=message[:500])
    except Exception as error:
        update_project(project_id, status="failed", progress="Failed", error=f"Unexpected processing error: {str(error)[:400]}")


def supported_video_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    return any(hostname == host or hostname.endswith(f".{host}") for host in SUPPORTED_URL_HOSTS)


def download_video(url: str, project_id: str) -> tuple[Path, str]:
    output_template = str(UPLOAD_DIR / f"{project_id}.%(ext)s")
    options = {
        "format": "bv*+ba/b",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "max_filesize": MAX_VIDEO_SIZE,
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
    candidates = [path for path in UPLOAD_DIR.glob(f"{project_id}.*") if path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS]
    if not candidates:
        raise ValueError("The video platform did not produce a supported video file.")
    return candidates[0], str(info.get("title") or "Imported video")


def process_video_url(project_id: str, url: str, clip_mode: str, clip_length: int, generate_subtitles: bool = False) -> None:
    update_project(project_id, status="processing", progress="Starting URL import", error=None)
    try:
        update_project(project_id, progress="Downloading video")
        source_path, title = download_video(url, project_id)
        update_project(project_id, source_name=title)
        process_video(project_id, str(source_path), clip_mode, clip_length, generate_subtitles)
    except Exception as error:
        update_project(project_id, status="failed", progress="Failed", error=f"Could not download or process this video: {str(error)[:400]}")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/capabilities")
def capabilities() -> dict[str, object]:
    return {"openai_configured": has_openai_key(), "url_hosts": sorted(SUPPORTED_URL_HOSTS), "max_upload_bytes": MAX_VIDEO_SIZE, "social_configured": social.capabilities()}


@app.get("/api/social/accounts")
def social_accounts() -> list[dict]:
    return social.list_accounts()


@app.get("/api/social/tiktok/accounts/{account_id}/privacy-options")
def tiktok_privacy_options(account_id: str) -> dict:
    try:
        options = social.tiktok_privacy_options(account_id)
        return {"options": options}
    except (social.SocialSetupError, httpx.HTTPError) as error:
        raise HTTPException(status_code=502, detail="Could not load current TikTok privacy options. Reconnect the account and try again.") from error


@app.get("/api/social/{provider}/connect")
def connect_social(provider: str) -> RedirectResponse:
    if provider not in social.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported social provider.")
    try:
        return RedirectResponse(social.begin_oauth(provider), status_code=302)
    except social.SocialSetupError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/social/{provider}/callback")
async def social_callback(provider: str, code: str | None = None, state: str | None = None, error: str | None = None) -> RedirectResponse:
    if provider not in social.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported social provider.")
    if error or not code or not state:
        return RedirectResponse(f"/settings?connect_error={provider}", status_code=303)
    try:
        connected = await social.finish_oauth(provider, code, state)
        return RedirectResponse(f"/settings?connected={provider}&count={len(connected)}", status_code=303)
    except Exception:
        return RedirectResponse(f"/settings?connect_error={provider}", status_code=303)


@app.delete("/api/social/{provider}/accounts/{account_id}")
def disconnect_social(provider: str, account_id: str) -> dict[str, bool]:
    if provider not in social.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported social provider.")
    if not social.remove_account(provider, account_id):
        raise HTTPException(status_code=404, detail="Connected account not found.")
    return {"disconnected": True}


@app.get("/api/scheduled-posts")
def get_scheduled_posts() -> list[dict]:
    return social.list_scheduled_posts()


@app.delete("/api/scheduled-posts/{post_id}")
def delete_scheduled_post(post_id: str) -> dict[str, bool]:
    if not social.cancel_scheduled_post(post_id):
        raise HTTPException(status_code=409, detail="Only queued posts can be cancelled.")
    return {"cancelled": True}


@app.post("/api/projects/{project_id}/schedule", status_code=201)
def schedule_project(project_id: str, schedule: ScheduleRequest) -> dict:
    project = next((item for item in read_projects() if item.get("id") == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.get("status") != "completed" or not project.get("clips"):
        raise HTTPException(status_code=409, detail="Wait until clip generation has completed before scheduling.")
    first_at = schedule.first_at
    if first_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Choose a schedule time with a timezone.")
    first_at = first_at.astimezone(timezone.utc)
    if first_at < datetime.now(timezone.utc) + timedelta(minutes=1):
        raise HTTPException(status_code=422, detail="Choose a first publish time at least one minute in the future.")
    target_ids = [(target.provider, target.account_id) for target in schedule.targets]
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(status_code=422, detail="Choose each connected account only once.")
    accounts = {(a["provider"], a["id"]) for a in social.list_accounts()}
    for target in schedule.targets:
        if (target.provider, target.account_id) not in accounts:
            raise HTTPException(status_code=422, detail=f"Connect the selected {target.provider} account before scheduling.")
        if target.provider == "tiktok":
            if not target.privacy_level:
                raise HTTPException(status_code=422, detail="Choose a TikTok privacy level for every selected TikTok account.")
            try:
                if target.privacy_level not in social.tiktok_privacy_options(target.account_id):
                    raise HTTPException(status_code=422, detail="That TikTok privacy option is no longer available. Refresh the page and choose again.")
            except (social.SocialSetupError, httpx.HTTPError) as error:
                raise HTTPException(status_code=502, detail="Could not verify TikTok privacy options. Reconnect and try again.") from error
    interval = timedelta(hours=6) if schedule.cadence == "6-hours" else timedelta(days=1)
    created_at = datetime.now(timezone.utc).isoformat()
    posts: list[dict] = []
    for index, clip in enumerate(project["clips"]):
        filename = Path(urlparse(clip.get("url", "")).path).name
        path = (CLIP_DIR / filename).resolve()
        if path.parent != CLIP_DIR.resolve() or not path.is_file():
            continue
        scheduled_at = (first_at + index * interval).isoformat()
        for target in schedule.targets:
            caption = schedule.caption.strip() or f"{project.get('source_name', 'ClipforgeAI video')} · Clip {clip['number']}"
            posts.append({"id": str(uuid4()), "project_id": project_id, "clip_number": clip["number"], "provider": target.provider, "account_id": target.account_id, "caption": caption, "video_path": str(path), "scheduled_at": scheduled_at, "settings": {"privacy_level": target.privacy_level} if target.privacy_level else {}, "created_at": created_at})
    if not posts:
        raise HTTPException(status_code=409, detail="The project's generated clip files are missing.")
    social.add_scheduled_posts(posts)
    return {"scheduled": len(posts), "first_at": first_at.isoformat(), "cadence": schedule.cadence}


@app.get("/api/projects", response_model=list[Project])
def list_projects() -> list[dict]:
    return sorted(read_projects(), key=lambda project: project.get("created_at", ""), reverse=True)


@app.get("/api/projects/{project_id}", response_model=Project)
def get_project(project_id: str) -> dict:
    for project in read_projects():
        if project["id"] == project_id:
            return project
    raise HTTPException(status_code=404, detail="Project not found.")


@app.post("/api/projects/{project_id}/clips/{clip_number}/edit")
def edit_clip(project_id: str, clip_number: int, edit: ClipEdit) -> dict:
    projects = read_projects()
    project = next((item for item in projects if item.get("id") == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    clip = next((item for item in project.get("clips", []) if item.get("number") == clip_number), None)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")
    filename = Path(urlparse(clip.get("url", "")).path).name
    source_path = (CLIP_DIR / filename).resolve()
    if source_path.parent != CLIP_DIR.resolve() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="Clip file not found.")
    try:
        duration = get_video_duration(str(source_path))
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=503, detail="FFmpeg and ffprobe are required to edit clips.") from error
    start = edit.trim_start
    end = edit.trim_end if edit.trim_end is not None else duration
    if start >= duration or end > duration + 0.05 or end <= start:
        raise HTTPException(status_code=422, detail=f"Choose a trim range within this {duration:.1f}-second clip.")
    output_path = CLIP_DIR / f"{project_id}-clip-{clip_number}-edited-{uuid4().hex[:8]}.mp4"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(start), "-i", str(source_path), "-t", str(end - start),
            "-vf", ASPECT_FILTERS[edit.aspect_ratio], "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", str(output_path),
        ], check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not render the edited clip. Check that FFmpeg is installed.") from error
    clip.update(url=f"/media/clips/{output_path.name}", duration_seconds=round(end - start, 1), aspect_ratio=edit.aspect_ratio, captions_url=None)
    if clip_number == 1:
        project["clip_url"] = clip["url"]
    with PROJECTS_LOCK:
        write_projects(projects)
    return clip


@app.post("/api/projects", response_model=Project, status_code=201)
async def create_project(
    background_tasks: BackgroundTasks,
    source_type: Literal["upload", "url"] = Form(...),
    clip_mode: Literal["best-parts", "sequence"] = Form(...),
    clip_duration: int = Form(30),
    generate_subtitles: bool = Form(False),
    video_url: str | None = Form(default=None),
    video_file: UploadFile | None = File(default=None),
) -> dict:
    if clip_duration not in {30, 60, 90}:
        raise HTTPException(status_code=422, detail="Clip length must be 30, 60, or 90 seconds.")
    if clip_mode == "best-parts" and not has_openai_key():
        raise HTTPException(status_code=503, detail="Best Parts requires an OpenAI API key. Add it to backend/.env and restart the backend, or choose Sequence Wise.")
    if generate_subtitles and not has_openai_key():
        raise HTTPException(status_code=503, detail="AI subtitles require an OpenAI API key. Add it to backend/.env and restart the backend.")

    project_id = str(uuid4())
    project: dict = {
        "id": project_id,
        "source_type": source_type,
        "source_name": "",
        "clip_mode": clip_mode,
        "clip_duration": clip_duration,
        "generate_subtitles": generate_subtitles,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "progress": "Waiting to start",
        "clip_url": None,
        "clips": [],
        "error": None,
    }
    if source_type == "upload":
        if video_file is None or not video_file.filename:
            raise HTTPException(status_code=422, detail="Please select a video file.")
        filename = safe_filename(video_file.filename)
        if Path(filename).suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Use an MP4, MOV, MKV, WEBM, AVI, M4V, MPEG, or MPG video.")
        if video_file.size is not None and video_file.size > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=413, detail="The maximum video size is 2 GB.")
        saved_path = UPLOAD_DIR / f"{project_id}-{filename}"
        total_bytes = 0
        try:
            with saved_path.open("wb") as destination:
                while chunk := video_file.file.read(1024 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_VIDEO_SIZE:
                        raise HTTPException(status_code=413, detail="The maximum video size is 2 GB.")
                    destination.write(chunk)
        except Exception:
            saved_path.unlink(missing_ok=True)
            raise
        project.update(source_name=filename, status="queued")
        save_project(project)
        background_tasks.add_task(process_video, project_id, str(saved_path), clip_mode, clip_duration, generate_subtitles)
    else:
        url = (video_url or "").strip()
        if not supported_video_url(url):
            raise HTTPException(status_code=422, detail="Use a public YouTube, Vimeo, Twitch, Google Drive, or Dropbox link.")
        project.update(source_name=url, status="queued")
        save_project(project)
        background_tasks.add_task(process_video_url, project_id, url, clip_mode, clip_duration, generate_subtitles)
    return project


FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

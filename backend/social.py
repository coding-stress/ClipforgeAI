"""OAuth account storage and publishing adapters for configured social providers."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "social.db"
PROVIDERS = ("youtube", "instagram", "tiktok", "facebook", "x", "linkedin")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v23.0")


class SocialSetupError(RuntimeError):
    pass


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


@contextmanager
def db_connection():
    connection = connect_db()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize() -> None:
    with db_connection() as db:
        db.executescript("""
          CREATE TABLE IF NOT EXISTS accounts (
            provider TEXT NOT NULL, account_id TEXT NOT NULL, display_name TEXT NOT NULL,
            encrypted_token BLOB NOT NULL, encrypted_refresh BLOB, expires_at REAL,
            scopes TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}',
            connected_at TEXT NOT NULL, PRIMARY KEY(provider, account_id)
          );
          CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY, provider TEXT NOT NULL, verifier TEXT, created_at REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS scheduled_posts (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, clip_number INTEGER NOT NULL,
            provider TEXT NOT NULL, account_id TEXT NOT NULL, caption TEXT NOT NULL,
            video_path TEXT NOT NULL, scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            error TEXT, remote_id TEXT, remote_url TEXT, settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, published_at TEXT
          );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(scheduled_posts)")}
        if "settings" not in columns:
            db.execute("ALTER TABLE scheduled_posts ADD COLUMN settings TEXT NOT NULL DEFAULT '{}' ")


def encryptor() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise SocialSetupError("Set TOKEN_ENCRYPTION_KEY to a generated Fernet key before connecting social accounts.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as error:
        raise SocialSetupError("TOKEN_ENCRYPTION_KEY is invalid; generate one with Fernet.generate_key().") from error


def provider_config(provider: str) -> tuple[str, str, str, str]:
    """Returns client id, secret, callback URL, and scopes for a provider."""
    base = (os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
    if not base.startswith("https://"):
        raise SocialSetupError("Set APP_BASE_URL to your public HTTPS site URL before connecting accounts.")
    key = provider.upper().replace("-", "_")
    client_id = os.getenv(f"{key}_CLIENT_ID", "").strip()
    client_secret = os.getenv(f"{key}_CLIENT_SECRET", "").strip()
    if provider in {"instagram", "facebook"}:
        client_id = client_id or os.getenv("META_CLIENT_ID", "").strip()
        client_secret = client_secret or os.getenv("META_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SocialSetupError(f"Configure {key}_CLIENT_ID and {key}_CLIENT_SECRET in backend/.env first.")
    scopes = {
        "youtube": "openid email profile https://www.googleapis.com/auth/youtube.upload",
        "instagram": "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
        "facebook": "pages_show_list,pages_read_engagement,pages_manage_posts",
        "tiktok": "user.info.basic,video.publish",
        "x": "tweet.read users.read tweet.write media.write offline.access",
        "linkedin": "openid profile w_member_social",
    }[provider]
    return client_id, client_secret, f"{base}/api/social/{provider}/callback", scopes


def begin_oauth(provider: str) -> str:
    initialize()
    encryptor()
    client_id, _, callback, scopes = provider_config(provider)
    state = secrets.token_urlsafe(32)
    verifier = None
    params: dict[str, str] = {"client_id": client_id, "redirect_uri": callback, "state": state, "scope": scopes}
    if provider == "youtube":
        endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
        params.update(response_type="code", access_type="offline", prompt="consent", include_granted_scopes="true")
    elif provider in {"instagram", "facebook"}:
        endpoint = f"https://www.facebook.com/{META_GRAPH_VERSION}/dialog/oauth"
        params.update(response_type="code")
    elif provider == "tiktok":
        endpoint = "https://www.tiktok.com/v2/auth/authorize/"
        params.update(response_type="code", client_key=client_id)
        params.pop("client_id", None)
    elif provider == "x":
        endpoint = "https://x.com/i/oauth2/authorize"
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params.update(response_type="code", code_challenge=challenge, code_challenge_method="S256")
    else:
        endpoint = "https://www.linkedin.com/oauth/v2/authorization"
        params.update(response_type="code")
    with db_connection() as db:
        db.execute("DELETE FROM oauth_states WHERE created_at < ?", (time.time() - 900,))
        db.execute("INSERT INTO oauth_states(state,provider,verifier,created_at) VALUES(?,?,?,?)", (state, provider, verifier, time.time()))
    return f"{endpoint}?{urlencode(params)}"


async def finish_oauth(provider: str, code: str, state: str) -> list[dict]:
    initialize()
    client_id, client_secret, callback, scopes = provider_config(provider)
    with db_connection() as db:
        row = db.execute("SELECT * FROM oauth_states WHERE state=? AND provider=?", (state, provider)).fetchone()
        if not row or time.time() - row["created_at"] > 900:
            raise SocialSetupError("OAuth state expired or did not match. Please try connecting again.")
        db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
    token_params = {"code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": callback}
    token_headers: dict[str, str] = {}
    token_auth = None
    if provider == "youtube":
        token_url = "https://oauth2.googleapis.com/token"
        token_params["grant_type"] = "authorization_code"
    elif provider in {"instagram", "facebook"}:
        token_url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/oauth/access_token"
    elif provider == "tiktok":
        token_url = "https://open.tiktokapis.com/v2/oauth/token/"
        token_params.update(grant_type="authorization_code", client_key=client_id)
        token_params.pop("client_id", None)
        token_params.pop("redirect_uri", None)
        token_params["redirect_uri"] = callback
        token_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif provider == "x":
        token_url = "https://api.x.com/2/oauth2/token"
        token_params.update(grant_type="authorization_code", code_verifier=row["verifier"] or "")
        token_headers["Content-Type"] = "application/x-www-form-urlencoded"
        token_params.pop("client_secret", None)
        token_params.pop("client_id", None)
        token_auth = httpx.BasicAuth(client_id, client_secret)
    else:
        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        token_params["grant_type"] = "authorization_code"

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(token_url, data=token_params, headers=token_headers, auth=token_auth)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token") or token_data.get("data", {}).get("access_token")
        refresh_token = token_data.get("refresh_token") or token_data.get("data", {}).get("refresh_token")
        expires_in = token_data.get("expires_in") or token_data.get("data", {}).get("expires_in")
        if not access_token:
            raise SocialSetupError("The provider did not return an access token.")
        if provider in {"instagram", "facebook"}:
            long_lived = await client.get(f"https://graph.facebook.com/{META_GRAPH_VERSION}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": client_id, "client_secret": client_secret, "fb_exchange_token": access_token})
            long_lived.raise_for_status()
            long_lived_data = long_lived.json()
            access_token = long_lived_data.get("access_token", access_token)
            expires_in = long_lived_data.get("expires_in", expires_in)
        headers = {"Authorization": f"Bearer {access_token}"}
        accounts: list[dict]
        if provider == "youtube":
            youtube_profile = await client.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"}, headers=headers)
            youtube_profile.raise_for_status()
            profile = youtube_profile.json()
            accounts = [{"id": item["id"], "name": item["snippet"]["title"]} for item in profile.get("items", [])]
        elif provider in {"instagram", "facebook"}:
            page_response = await client.get(f"https://graph.facebook.com/{META_GRAPH_VERSION}/me/accounts", params={"fields": "id,name,access_token,instagram_business_account{id,username}", "access_token": access_token})
            page_response.raise_for_status()
            pages = page_response.json().get("data", [])
            accounts = []
            for page in pages:
                if provider == "facebook":
                    if page.get("access_token"):
                        accounts.append({"id": page["id"], "name": page.get("name", page["id"]), "page_token": page["access_token"]})
                elif page.get("instagram_business_account") and page.get("access_token"):
                    ig = page["instagram_business_account"]
                    accounts.append({"id": ig["id"], "name": ig.get("username", page.get("name", ig["id"])), "page_id": page["id"], "page_token": page["access_token"]})
        elif provider == "tiktok":
            response = await client.get("https://open.tiktokapis.com/v2/user/info/", params={"fields": "open_id,display_name,avatar_url"}, headers=headers)
            response.raise_for_status()
            user = response.json().get("data", {}).get("user", {})
            accounts = [{"id": user["open_id"], "name": user.get("display_name", "TikTok account")}] if user.get("open_id") else []
        elif provider == "x":
            response = await client.get("https://api.x.com/2/users/me", params={"user.fields": "name,username"}, headers=headers)
            response.raise_for_status()
            user = response.json().get("data", {})
            accounts = [{"id": user["id"], "name": f"@{user.get('username', user['id'])}"}] if user.get("id") else []
        else:
            response = await client.get("https://api.linkedin.com/v2/userinfo", headers=headers)
            response.raise_for_status()
            user = response.json()
            accounts = [{"id": user["sub"], "name": user.get("name", "LinkedIn member"), "urn": f"urn:li:person:{user['sub']}"}] if user.get("sub") else []
    if not accounts:
        raise SocialSetupError("Authorization succeeded, but no eligible account was found. Check the account type and granted permissions.")
    cipher = encryptor()
    connected_at = datetime.now(timezone.utc).isoformat()
    expiry = time.time() + int(expires_in) if expires_in else None
    with db_connection() as db:
        for account in accounts:
            token = {"access_token": access_token, **{k: v for k, v in account.items() if k not in {"id", "name"}}}
            db.execute("""INSERT OR REPLACE INTO accounts(provider,account_id,display_name,encrypted_token,encrypted_refresh,expires_at,scopes,metadata,connected_at)
                VALUES(?,?,?,?,?,?,?,?,?)""", (provider, account["id"], account["name"], cipher.encrypt(json.dumps(token).encode()), cipher.encrypt(refresh_token.encode()) if refresh_token else None, expiry, scopes, json.dumps({k: v for k, v in account.items() if k not in {"id", "name"}}), connected_at))
    return [{"provider": provider, "id": a["id"], "name": a["name"]} for a in accounts]


def list_accounts() -> list[dict]:
    initialize()
    with db_connection() as db:
        return [dict(row) for row in db.execute("SELECT provider,account_id AS id,display_name AS name,connected_at FROM accounts ORDER BY provider,display_name")]


def remove_account(provider: str, account_id: str) -> bool:
    with db_connection() as db:
        cursor = db.execute("DELETE FROM accounts WHERE provider=? AND account_id=?", (provider, account_id))
        return cursor.rowcount > 0


def tiktok_privacy_options(account_id: str) -> list[str]:
    token_data, _ = _load_account("tiktok", account_id)
    token_data = _fresh_account_token("tiktok", account_id, token_data)
    with httpx.Client(timeout=45) as client:
        response = client.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", headers=_headers(token_data["access_token"]), json={})
        response.raise_for_status()
    return response.json().get("data", {}).get("privacy_level_options", [])


def capabilities() -> dict[str, bool]:
    try:
        encryptor()
        encrypted_storage_ready = True
    except SocialSetupError:
        encrypted_storage_ready = False
    public_base_url = os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
    public_host_ready = public_base_url.startswith("https://")
    return {provider: public_host_ready and encrypted_storage_ready and bool(os.getenv(f"{provider.upper()}_CLIENT_ID") or (provider in {"instagram", "facebook"} and os.getenv("META_CLIENT_ID"))) and bool(os.getenv(f"{provider.upper()}_CLIENT_SECRET") or (provider in {"instagram", "facebook"} and os.getenv("META_CLIENT_SECRET"))) for provider in PROVIDERS}


def add_scheduled_posts(posts: list[dict]) -> None:
    initialize()
    with db_connection() as db:
        for post in posts:
            db.execute("""INSERT INTO scheduled_posts(id,project_id,clip_number,provider,account_id,caption,video_path,scheduled_at,settings,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (post["id"], post["project_id"], post["clip_number"], post["provider"], post["account_id"], post["caption"], post["video_path"], post["scheduled_at"], json.dumps(post.get("settings", {})), post["created_at"]))


def list_scheduled_posts(limit: int = 100) -> list[dict]:
    initialize()
    with db_connection() as db:
        return [dict(row) for row in db.execute("SELECT id,project_id,clip_number,provider,account_id,caption,scheduled_at,status,error,remote_url,created_at,published_at FROM scheduled_posts ORDER BY scheduled_at DESC LIMIT ?", (limit,))]


def cancel_scheduled_post(post_id: str) -> bool:
    with db_connection() as db:
        cursor = db.execute("DELETE FROM scheduled_posts WHERE id=? AND status='queued'", (post_id,))
        return cursor.rowcount > 0


def recover_interrupted_posts() -> None:
    with db_connection() as db:
        db.execute("UPDATE scheduled_posts SET status='failed',error='The server restarted during publishing. Check the social account before scheduling again to avoid a duplicate.' WHERE status='publishing'")


def _load_account(provider: str, account_id: str) -> tuple[dict, dict]:
    cipher = encryptor()
    with db_connection() as db:
        row = db.execute("SELECT * FROM accounts WHERE provider=? AND account_id=?", (provider, account_id)).fetchone()
    if not row:
        raise SocialSetupError("The connected social account was removed.")
    token_data = json.loads(cipher.decrypt(row["encrypted_token"]).decode())
    metadata = json.loads(row["metadata"] or "{}")
    return token_data, metadata


def _fresh_account_token(provider: str, account_id: str, token_data: dict) -> dict:
    cipher = encryptor()
    with db_connection() as db:
        row = db.execute("SELECT encrypted_refresh,expires_at FROM accounts WHERE provider=? AND account_id=?", (provider, account_id)).fetchone()
    if not row or not row["expires_at"] or row["expires_at"] > time.time() + 300:
        return token_data
    if not row["encrypted_refresh"]:
        raise SocialSetupError(f"The {provider} authorization expired. Reconnect this account in Publishing settings.")
    refresh_token = cipher.decrypt(row["encrypted_refresh"]).decode()
    client_id, client_secret, _, _ = provider_config(provider)
    if provider == "youtube":
        url = "https://oauth2.googleapis.com/token"
        data = {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}
        auth = None
    elif provider == "tiktok":
        url = "https://open.tiktokapis.com/v2/oauth/token/"
        data = {"client_key": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}
        auth = None
    elif provider == "x":
        url = "https://api.x.com/2/oauth2/token"
        data = {"refresh_token": refresh_token, "grant_type": "refresh_token"}
        auth = httpx.BasicAuth(client_id, client_secret)
    elif provider == "linkedin":
        url = "https://www.linkedin.com/oauth/v2/accessToken"
        data = {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}
        auth = None
    else:
        raise SocialSetupError(f"The {provider} authorization expired. Reconnect this account in Publishing settings.")
    with httpx.Client(timeout=45) as client:
        response = client.post(url, data=data, auth=auth)
        response.raise_for_status()
        response_body = response.json()
        updated = response_body.get("data", response_body)
    if not updated.get("access_token"):
        raise SocialSetupError(f"The {provider} account needs to be reconnected.")
    token_data["access_token"] = updated["access_token"]
    new_refresh = updated.get("refresh_token", refresh_token)
    expiry = time.time() + int(updated.get("expires_in", 3600))
    with db_connection() as db:
        db.execute("UPDATE accounts SET encrypted_token=?,encrypted_refresh=?,expires_at=? WHERE provider=? AND account_id=?", (cipher.encrypt(json.dumps(token_data).encode()), cipher.encrypt(new_refresh.encode()), expiry, provider, account_id))
    return token_data


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post_youtube(token: str, video_path: str, caption: str) -> tuple[str, str | None]:
    title = (caption.strip() or Path(video_path).stem)[:100]
    with httpx.Client(timeout=180) as client:
        init = client.post("https://www.googleapis.com/upload/youtube/v3/videos", params={"uploadType": "resumable", "part": "snippet,status"}, headers={**_headers(token), "X-Upload-Content-Type": "video/mp4"}, json={"snippet": {"title": title, "description": caption, "categoryId": "22"}, "status": {"privacyStatus": "public"}})
        init.raise_for_status()
        location = init.headers.get("location")
        if not location:
            raise SocialSetupError("YouTube did not return a resumable upload URL.")
        with open(video_path, "rb") as media:
            uploaded = client.put(location, content=media, headers={"Content-Type": "video/mp4"})
        uploaded.raise_for_status()
        video_id = uploaded.json().get("id")
    if not video_id:
        raise SocialSetupError("YouTube upload completed without a video ID.")
    return video_id, f"https://youtube.com/shorts/{video_id}"


def _post_instagram(token: str, account_id: str, video_url: str, caption: str) -> tuple[str, str | None]:
    graph = f"https://graph.facebook.com/{META_GRAPH_VERSION}"
    with httpx.Client(timeout=60) as client:
        created = client.post(f"{graph}/{account_id}/media", data={"media_type": "REELS", "video_url": video_url, "caption": caption[:2200], "share_to_feed": "true", "access_token": token})
        created.raise_for_status()
        container_id = created.json().get("id")
        if not container_id:
            raise SocialSetupError("Instagram did not return a Reel container ID.")
        ready = False
        for _ in range(60):
            state = client.get(f"{graph}/{container_id}", params={"fields": "status_code", "access_token": token})
            state.raise_for_status()
            code = state.json().get("status_code")
            if code == "FINISHED":
                ready = True
                break
            if code == "ERROR":
                raise SocialSetupError("Instagram could not process the Reel media.")
            time.sleep(10)
        if not ready:
            raise SocialSetupError("Instagram Reel processing timed out; try publishing again later.")
        published = client.post(f"{graph}/{account_id}/media_publish", data={"creation_id": container_id, "access_token": token})
        published.raise_for_status()
        media_id = published.json().get("id")
        return media_id or container_id, None


def _post_facebook(token: str, account_id: str, video_path: str, caption: str) -> tuple[str, str | None]:
    graph = f"https://graph.facebook.com/{META_GRAPH_VERSION}"
    size = os.path.getsize(video_path)
    with httpx.Client(timeout=180) as client:
        started = client.post(f"{graph}/{account_id}/video_reels", data={"upload_phase": "start", "access_token": token})
        started.raise_for_status()
        init = started.json()
        video_id = init.get("video_id")
        upload_url = init.get("upload_url") or f"https://rupload.facebook.com/video-upload/{META_GRAPH_VERSION}/{video_id}"
        if not video_id:
            raise SocialSetupError("Facebook did not return a Reel upload ID.")
        with open(video_path, "rb") as media:
            uploaded = client.post(upload_url, content=media, headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size), "Content-Type": "video/mp4"})
        uploaded.raise_for_status()
        finished = client.post(f"{graph}/{account_id}/video_reels", data={"upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED", "description": caption, "access_token": token})
        finished.raise_for_status()
    return video_id, f"https://www.facebook.com/reel/{video_id}"


def _post_tiktok(token: str, video_path: str, caption: str, privacy_level: str) -> tuple[str, str | None]:
    size = os.path.getsize(video_path)
    chunk_size = min(max(5 * 1024 * 1024, size), 64 * 1024 * 1024)
    chunk_size = min(chunk_size, size)
    total_chunks = (size + chunk_size - 1) // chunk_size
    with httpx.Client(timeout=180) as client:
        creator = client.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", headers=_headers(token), json={})
        creator.raise_for_status()
        options = creator.json().get("data", {}).get("privacy_level_options", [])
        if not options:
            raise SocialSetupError("TikTok did not return eligible privacy levels for this account.")
        if privacy_level not in options:
            raise SocialSetupError("TikTok’s available privacy options changed. Refresh the schedule form and choose again.")
        started = client.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers={**_headers(token), "Content-Type": "application/json; charset=UTF-8"}, json={"post_info": {"title": caption[:2200], "privacy_level": privacy_level, "disable_comment": False, "disable_duet": False, "disable_stitch": False}, "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": total_chunks}})
        started.raise_for_status()
        result = started.json().get("data", {})
        upload_url, publish_id = result.get("upload_url"), result.get("publish_id")
        if not upload_url or not publish_id:
            raise SocialSetupError("TikTok did not initialize the video upload.")
        with open(video_path, "rb") as media:
            for index in range(total_chunks):
                offset = index * chunk_size
                data = media.read(chunk_size)
                end = offset + len(data) - 1
                uploaded = client.put(upload_url, content=data, headers={"Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{end}/{size}", "Content-Length": str(len(data))})
                uploaded.raise_for_status()
        completed = False
        for _ in range(60):
            status = client.post("https://open.tiktokapis.com/v2/post/publish/status/fetch/", headers={**_headers(token), "Content-Type": "application/json; charset=UTF-8"}, json={"publish_id": publish_id})
            status.raise_for_status()
            state = status.json().get("data", {}).get("status")
            if state == "PUBLISH_COMPLETE":
                completed = True
                break
            if state == "FAILED":
                raise SocialSetupError("TikTok did not publish the uploaded video. Check the account permissions and content requirements.")
            time.sleep(10)
        if not completed:
            raise SocialSetupError("TikTok is still processing this post. Check the TikTok app before retrying to avoid a duplicate.")
    return publish_id, None


def _post_x(token: str, video_path: str, caption: str) -> tuple[str, str | None]:
    size = os.path.getsize(video_path)
    with httpx.Client(timeout=180) as client:
        initialized = client.post("https://api.x.com/2/media/upload", params={"command": "INIT", "total_bytes": size, "media_type": "video/mp4", "media_category": "tweet_video"}, headers=_headers(token))
        initialized.raise_for_status()
        media_id = initialized.json().get("data", {}).get("id")
        if not media_id:
            raise SocialSetupError("X did not initialize the media upload.")
        with open(video_path, "rb") as media:
            index = 0
            while chunk := media.read(4 * 1024 * 1024):
                appended = client.post("https://api.x.com/2/media/upload", data={"command": "APPEND", "media_id": media_id, "segment_index": index}, headers=_headers(token), files={"media": ("clip.mp4", chunk, "application/octet-stream")})
                appended.raise_for_status()
                index += 1
        finalized = client.post("https://api.x.com/2/media/upload", params={"command": "FINALIZE", "media_id": media_id}, headers=_headers(token))
        finalized.raise_for_status()
        state = finalized.json().get("data", {}).get("processing_info", {})
        while state.get("state") in {"pending", "in_progress"}:
            time.sleep(min(state.get("check_after_secs", 5), 15))
            polled = client.get("https://api.x.com/2/media/upload", params={"command": "STATUS", "media_id": media_id}, headers=_headers(token))
            polled.raise_for_status()
            state = polled.json().get("data", {}).get("processing_info", {})
        if state.get("state") == "failed":
            raise SocialSetupError("X could not process the uploaded video.")
        post = client.post("https://api.x.com/2/tweets", headers={**_headers(token), "Content-Type": "application/json"}, json={"text": caption[:280], "media": {"media_ids": [media_id]}})
        post.raise_for_status()
        post_id = post.json().get("data", {}).get("id")
    if not post_id:
        raise SocialSetupError("X did not return a post ID.")
    return post_id, f"https://x.com/i/status/{post_id}"


def _post_linkedin(token: str, metadata: dict, account_id: str, video_path: str, caption: str) -> tuple[str, str | None]:
    owner = metadata.get("urn") or f"urn:li:person:{account_id}"
    version = os.getenv("LINKEDIN_VERSION", "202609")
    base_headers = {**_headers(token), "Linkedin-Version": version, "X-Restli-Protocol-Version": "2.0.0"}
    size = os.path.getsize(video_path)
    with httpx.Client(timeout=180) as client:
        init = client.post("https://api.linkedin.com/rest/videos?action=initializeUpload", headers={**base_headers, "Content-Type": "application/json"}, json={"initializeUploadRequest": {"owner": owner, "fileSizeBytes": size, "uploadThumbnail": False, "uploadCaptions": False}})
        init.raise_for_status()
        payload = init.json().get("value", {})
        video_urn = payload.get("video")
        instructions = payload.get("uploadInstructions", [])
        if not video_urn or not instructions:
            raise SocialSetupError("LinkedIn did not return video upload instructions.")
        uploaded_parts = []
        with open(video_path, "rb") as media:
            for instruction in instructions:
                start, end = instruction["firstByte"], instruction["lastByte"]
                media.seek(start)
                chunk = media.read(end - start + 1)
                uploaded = client.put(instruction["uploadUrl"], content=chunk, headers={"Content-Type": "application/octet-stream"})
                uploaded.raise_for_status()
                etag = uploaded.headers.get("etag", "").strip('"')
                if not etag:
                    raise SocialSetupError("LinkedIn did not return an upload part ETag.")
                uploaded_parts.append(etag)
        client.post("https://api.linkedin.com/rest/videos?action=finalizeUpload", headers={**base_headers, "Content-Type": "application/json"}, json={"finalizeUploadRequest": {"video": video_urn, "uploadToken": payload.get("uploadToken", ""), "uploadedPartIds": uploaded_parts}}).raise_for_status()
        post = client.post("https://api.linkedin.com/rest/posts", headers={**base_headers, "Content-Type": "application/json"}, json={"author": owner, "commentary": caption, "visibility": "PUBLIC", "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}, "content": {"media": {"title": caption[:200], "id": video_urn}}, "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False})
        post.raise_for_status()
        post_id = post.headers.get("x-restli-id")
    return post_id or video_urn, None


def publish_video(provider: str, account_id: str, video_path: str, caption: str, public_video_url: str | None = None, settings: dict | None = None) -> tuple[str, str | None]:
    token_data, metadata = _load_account(provider, account_id)
    token_data = _fresh_account_token(provider, account_id, token_data)
    token = token_data.get("access_token", "")
    if provider == "youtube":
        return _post_youtube(token, video_path, caption)
    if provider == "instagram":
        if not public_video_url:
            raise SocialSetupError("Instagram Reels need a publicly reachable HTTPS media URL.")
        return _post_instagram(token_data.get("page_token", token), account_id, public_video_url, caption)
    if provider == "facebook":
        return _post_facebook(token_data.get("page_token", token), account_id, video_path, caption)
    if provider == "tiktok":
        privacy = (settings or {}).get("privacy_level")
        if not privacy:
            raise SocialSetupError("Choose a TikTok privacy level when scheduling this post.")
        return _post_tiktok(token, video_path, caption, privacy)
    if provider == "x":
        return _post_x(token, video_path, caption)
    if provider == "linkedin":
        return _post_linkedin(token, metadata, account_id, video_path, caption)
    raise SocialSetupError("Unsupported publishing provider.")


def publish_due(public_media_url) -> None:
    initialize()
    with db_connection() as db:
        pending = db.execute("SELECT * FROM scheduled_posts WHERE status='queued' AND scheduled_at<=? ORDER BY scheduled_at LIMIT 10", (datetime.now(timezone.utc).isoformat(),)).fetchall()
    for post in pending:
        with db_connection() as db:
            changed = db.execute("UPDATE scheduled_posts SET status='publishing',error=NULL WHERE id=? AND status='queued'", (post["id"],)).rowcount
        if not changed:
            continue
        try:
            video_path = Path(post["video_path"]).resolve()
            if not video_path.is_file():
                raise SocialSetupError("The scheduled clip file is no longer available on persistent storage.")
            video_url = public_media_url(str(video_path)) if post["provider"] == "instagram" else None
            remote_id, remote_url = publish_video(post["provider"], post["account_id"], str(video_path), post["caption"], video_url, json.loads(post["settings"] or "{}"))
            with db_connection() as db:
                db.execute("UPDATE scheduled_posts SET status='published',remote_id=?,remote_url=?,published_at=? WHERE id=?", (remote_id, remote_url, datetime.now(timezone.utc).isoformat(), post["id"]))
        except Exception as error:
            if isinstance(error, httpx.HTTPStatusError):
                message = f"{post['provider']} returned HTTP {error.response.status_code}. Check the provider app permissions and account eligibility."
            elif isinstance(error, httpx.TimeoutException):
                message = f"{post['provider']} timed out while publishing. Check the provider before retrying to avoid duplicates."
            elif isinstance(error, httpx.HTTPError):
                message = f"Could not reach {post['provider']}. Check the network and social account before retrying."
            else:
                message = str(error) or "Publishing failed. Reconnect the account and try again."
            with db_connection() as db:
                db.execute("UPDATE scheduled_posts SET status='failed',error=? WHERE id=?", (message[:500], post["id"]))


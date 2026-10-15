# ClipforgeAI

ClipforgeAI turns long videos into short clips on your Windows computer.

## Features

- Upload MP4, MOV, MKV, WEBM, AVI, M4V, MPEG, and MPG videos up to 2 GB.
- Import public YouTube, Vimeo, Twitch, Google Drive, and Dropbox links with yt-dlp.
- Create chronological clips in 30, 60, or 90 second lengths.
- Use **Best Parts** to transcribe a video's extracted audio with OpenAI and rank highlight moments with an OpenAI model.
- Generate optional timed WebVTT captions using OpenAI transcription, burn captions into the clip when FFmpeg supports it, preview them in the video player, and download the caption file.
- Trim generated clips and render 9:16, 1:1, or 16:9 aspect ratios in the built-in clip editor.
- Connect YouTube, Instagram, TikTok, Facebook, X, and LinkedIn accounts with OAuth; account tokens are encrypted at rest.
- Schedule all clips to selected accounts every 6 hours or daily, and monitor the durable publishing queue.
- Preview and download generated clips, and see saved projects and processing status on the dashboard.

## Requirements

- Windows 10 or 11
- Python 3.12 or newer
- Node.js 20.19+ or 22.12+ and npm
- FFmpeg and ffprobe available on `PATH`

Check FFmpeg before starting:

```powershell
ffmpeg -version
ffprobe -version
```

## Install

Open PowerShell in the project folder and prepare the backend:

```powershell
cd D:\Projects\ClipforgeAI\backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

To enable **Best Parts**, open `backend/.env`, replace `your_api_key_here` with your OpenAI API key, and save it. Best Parts sends extracted audio to OpenAI for transcription and sends the transcript to OpenAI for highlight selection. API charges may apply. The original video file is not sent to OpenAI. **Sequence Wise** works without an API key and keeps processing on your computer.

Set `APP_PASSWORD` to a private password with at least 12 characters and `APP_SESSION_SECRET` to a random secret with at least 32 characters before opening the app. For social account connections, generate `TOKEN_ENCRYPTION_KEY` using `backend/.venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Local development can leave `APP_BASE_URL` blank; OAuth connections require the public HTTPS URL after deployment.

In the same backend PowerShell window, start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Open a second PowerShell window for the frontend:

```powershell
cd D:\Projects\ClipforgeAI\frontend
npm ci
npm run dev
```

Open the local URL printed by Vite (usually `http://localhost:5173`). The API docs are at `http://127.0.0.1:8000/docs`.

## Use

1. Choose a local video or paste a public YouTube, Vimeo, Twitch, Google Drive, or Dropbox link.
2. Choose **Sequence Wise** for local chronological clips or **Best Parts** for AI-selected moments.
3. Select 30, 60, or 90 seconds.
4. Generate, preview, and download clips. Projects remain on the dashboard.

Uploaded videos, project records, temporary audio chunks, and output clips are stored in `backend/data`. Temporary audio chunks are deleted after transcription. Do not expose this development server to the public internet; it has no user authentication.

The clip editor trims and center-crops the current rendered clip. It does not yet provide face tracking, logo overlays, or animated subtitle styling. Scheduled cross-posting requires provider OAuth credentials, account authorization, and a publicly reachable media URL for some providers; the local development app does not claim that social accounts are connected.

For a guided tour of the code and a first small modification, see [the step-by-step guide](docs/learning-guide.md).

For the hosted HTTPS deployment, OAuth app registration, encrypted token storage, and provider setup, see [the deployment guide](docs/deployment.md). The hosted app requires app credentials and external platform approval before every publishing path can be activated.

## API

- `GET /api/health` — API health
- `GET /api/capabilities` — current OpenAI setup and input limits
- `GET /api/projects` — recent projects
- `GET /api/projects/{id}` — project status and clips
- `POST /api/projects` — upload or import a video and start processing
- `/media/...` — generated video files

## Hosted deployment

Build and run with Docker or deploy the included Render blueprint. Hosted scheduled publishing requires a continuously running single instance with the persistent data disk attached. Follow [docs/deployment.md](docs/deployment.md) to configure HTTPS, login secrets, OAuth apps, and provider permissions.

# Build ClipforgeAI step by step

This guide explains the working local version in this repository, then shows how to extend it. The app uses React + TypeScript in `frontend/` and FastAPI + FFmpeg in `backend/`.

## 1. Start the app

1. Install Python, Node.js, and FFmpeg. Confirm `ffmpeg -version` and `ffprobe -version` work in PowerShell.
2. In `backend/`, create a virtual environment and install `requirements.txt` as described in the root README.
3. Copy `backend/.env.example` to `backend/.env`. Put your own OpenAI API key in that local file if you want Best Parts or AI subtitles. Never paste the key into source code or commit `.env`.
4. Start FastAPI with `python -m uvicorn main:app --reload --port 8000` from `backend/`.
5. In a second terminal, run `npm ci` and `npm run dev` from `frontend/`, then open the local URL Vite prints.

## 2. Follow a video through the app

1. `frontend/src/components/NewProject.tsx` collects the source, mode, clip length, and subtitle option.
2. The browser sends a multipart `POST /api/projects` request. `frontend/vite.config.ts` proxies `/api` and `/media` to FastAPI during local development.
3. `backend/main.py` validates the request, stores an upload under `backend/data/uploads/`, records a project in `projects.json`, and queues processing with FastAPI background tasks.
4. For a URL source, `yt-dlp` downloads the source first. FFmpeg and ffprobe inspect the video and render chronological clips or AI-selected highlights.
5. Best Parts transcribes extracted audio with OpenAI, then sends the timestamped transcript to an OpenAI model to select moments. Optional subtitles use the same transcription to write a WebVTT file per clip. The video itself is not sent to OpenAI.
6. The page polls `GET /api/projects/{id}` until processing completes. The returned clip and caption URLs point to files served from `/media`.
7. Editing posts a trim range and aspect ratio to `/api/projects/{id}/clips/{number}/edit`. FastAPI renders a new MP4 and updates the saved project record.

## 3. Make a small change

Try changing the default clip length from 30 seconds to 60 seconds:

1. In `frontend/src/components/NewProject.tsx`, change the initial `clipDuration` state.
2. In `backend/main.py`, change the default value on the `clip_duration` form field to match.
3. Reload the page, generate a Sequence Wise project, and confirm its duration.

Keep validation on both sides: the frontend makes valid choices easy, while the backend must reject invalid requests because clients can be bypassed.

## 4. Add a feature safely

1. Decide what data the feature needs and whether it requires a third-party account.
2. Add a typed request model and validation in `backend/main.py`.
3. Persist durable state in the project JSON (or migrate to SQLite when concurrent users or multiple workers are needed).
4. Add UI state and clear progress/error messages in the relevant React component.
5. Add setup instructions to the README and keep secrets in `.env` or a proper secret store.
6. Build the frontend and compile the Python module after changes.

## 5. Follow scheduling and publishing

1. `frontend/src/components/Settings.tsx` reads provider readiness and connected accounts from the backend.
2. The **Connect** action starts an OAuth state/authorization-code flow. `backend/social.py` exchanges the code, fetches eligible accounts, and encrypts tokens with the Fernet key before writing them to SQLite.
3. On the generated-clips page, choose destinations, cadence, first time, and caption. `POST /api/projects/{id}/schedule` writes one durable queue row for each clip/destination pair.
4. A single APScheduler worker checks the queue every 20 seconds, dispatches each due row to the matching provider adapter, and stores its result or error.
5. Instagram receives a temporary signed media URL because its service needs to fetch the MP4 from the public HTTPS host. The other adapters upload bytes from the worker.

Set up an OAuth app and get the required scopes approved at each social provider. Provider approval is outside this repository, and real publishing cannot succeed until those developer credentials and account permissions are configured. See `docs/deployment.md` for provider setup. Keep one backend worker/instance so the scheduler does not publish a queue item twice. Do not expose the app without its workspace login and persistent storage.

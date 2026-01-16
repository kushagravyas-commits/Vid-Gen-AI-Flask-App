# VidGen AI (FastAPI backend + Flask frontend)

## About Endpoints
- FastAPI backend:
  - POST /api/v1/jobs (submit)
  - GET /api/v1/jobs/{job_id} (status + log tail)
  - GET /api/v1/jobs/{job_id}/download?format=zip (download outputs)
  - /api/v1/meta/languages, /api/v1/meta/styles (UI metadata)

## Prerequisites
- Python 3.10+
- `ffmpeg` and `ffprobe` available in PATH (required by your generator)
- Your `video_generator.py` placed at `backend/app/video_engine/video_generator.py` and patched (see `README_PATCH.md`)

## Setup

1) Backend:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
   pip install -r requirements.txt

   # Install your generator dependencies too:
   # pip install langgraph langchain-core openai gTTS whisper
   # and any others you used.

   uvicorn app.main:app --reload --port 8000
   ```
2) Frontend:
   ```bash
   cd frontend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   export BACKEND_URL=http://localhost:8000  # Windows: set BACKEND_URL=...
   python app.py
   ```
3) Open: http://localhost:5000

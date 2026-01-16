from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.api.schemas import (
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
    StylesResponse,
    LanguagesResponse,
)
from app.core.jobs import job_store
from app.core.runner import submit_job
from app.core.config import settings
from app.utils.languages import INDIAN_LANGUAGES


router = APIRouter()


@router.get("/meta/styles", response_model=StylesResponse)
def list_styles():
    return {"styles": settings.STYLES}


@router.get("/meta/languages", response_model=LanguagesResponse)
def list_languages():
    return {"languages": INDIAN_LANGUAGES}


@router.post("/jobs", response_model=JobCreateResponse)
def create_job(req: JobCreateRequest):
    # Basic validation
    for code in req.languages:
        if code not in INDIAN_LANGUAGES:
            raise HTTPException(status_code=400, detail=f"Unsupported language code: {code}")

    if req.style not in settings.STYLES:
        raise HTTPException(status_code=400, detail=f"Unknown style: {req.style}")

    job = job_store.create(query=req.query, languages=req.languages, style=req.style)
    submit_job(job.job_id)  # background execution
    return {"job_id": job.job_id, "status": job.status}


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, log_lines: int = Query(40, ge=0, le=400)):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    tail = None
    if job.log_path and os.path.exists(job.log_path) and log_lines > 0:
        with open(job.log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        tail = "".join(lines[-log_lines:])

    return {
        "job_id": job.job_id,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "progress_stage": job.progress_stage,
        "message": job.message,
        "outputs": job.outputs,
        "error": job.error,
        "log_tail": tail,
    }


@router.get("/jobs/{job_id}/download")
def download_job_output(
    job_id: str,
    format: str = Query("zip", pattern="^(zip|single)$"),
    language: str | None = Query(None, description="Required when format=single"),
):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "COMPLETED":
        raise HTTPException(status_code=409, detail="Job not completed yet")

    if format == "zip":
        if not job.zip_path or not os.path.exists(job.zip_path):
            raise HTTPException(status_code=500, detail="ZIP output missing")
        return FileResponse(
            job.zip_path,
            media_type="application/zip",
            filename=os.path.basename(job.zip_path),
        )

    # format == "single"
    if not language:
        raise HTTPException(status_code=400, detail="language is required when format=single")

    for out in job.outputs:
        if out["language"] == language:
            if not os.path.exists(out["video_path"]):
                raise HTTPException(status_code=500, detail="Video output missing")
            return FileResponse(
                out["video_path"],
                media_type="video/mp4",
                filename=out["filename"],
            )

    raise HTTPException(status_code=404, detail=f"No output for language={language}")

@router.get("/jobs/{job_id}/preview")
def preview_job_output(
    job_id: str,
    language: str | None = Query(None, description="Language code to preview (e.g., hi). Defaults to first output."),
):
    """
    Stream an MP4 for in-app preview (Content-Disposition: inline).
    Use /download for attachment downloads.
    """
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "COMPLETED":
        raise HTTPException(status_code=409, detail="Job not completed yet")

    if not job.outputs:
        raise HTTPException(status_code=404, detail="No outputs found")

    chosen = None
    if language:
        for out in job.outputs:
            if out["language"] == language:
                chosen = out
                break
        if not chosen:
            raise HTTPException(status_code=404, detail=f"No output for language={language}")
    else:
        chosen = job.outputs[0]

    if not os.path.exists(chosen["video_path"]):
        raise HTTPException(status_code=500, detail="Video output missing")

    return FileResponse(
        chosen["video_path"],
        media_type="video/mp4",
        headers={"Content-Disposition": "inline"},
    )

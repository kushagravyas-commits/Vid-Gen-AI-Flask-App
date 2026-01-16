from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal


class JobCreateRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User prompt. Duration should be included in the query text.")
    languages: List[str] = Field(..., min_length=1, description="List of language codes (e.g., hi, en, ta).")
    style: str = Field(..., min_length=1, description="Selected video style label.")


JobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobOutput(BaseModel):
    language: str
    video_path: str
    filename: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    progress_stage: str
    message: str
    outputs: List[JobOutput] = []
    error: Optional[str] = None
    log_tail: Optional[str] = None


class StylesResponse(BaseModel):
    styles: List[str]


class LanguagesResponse(BaseModel):
    # mapping: code -> display name
    languages: Dict[str, str]

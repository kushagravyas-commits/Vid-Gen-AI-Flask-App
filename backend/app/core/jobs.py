from __future__ import annotations

import os
import json
import uuid
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Job:
    job_id: str
    query: str
    languages: List[str]
    style: str

    status: str = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED
    progress_stage: str = "queued"
    message: str = "Waiting to start"
    error: Optional[str] = None

    created_at: str = ""
    updated_at: str = ""

    # outputs
    outputs: List[Dict[str, str]] = None
    zip_path: Optional[str] = None
    log_path: Optional[str] = None
    work_dir: Optional[str] = None

    def __post_init__(self):
        now = _now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if self.outputs is None:
            self.outputs = []


class JobStore:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: Dict[str, Job] = {}

    def create(self, query: str, languages: List[str], style: str) -> Job:
        with self._lock:
            job_id = uuid.uuid4().hex
            work_dir = os.path.join(self.root_dir, job_id)
            os.makedirs(work_dir, exist_ok=True)
            log_path = os.path.join(work_dir, "job.log")

            job = Job(
                job_id=job_id,
                query=query,
                languages=languages,
                style=style,
                status="QUEUED",
                progress_stage="queued",
                message="Job created",
                created_at=_now_iso(),
                updated_at=_now_iso(),
                outputs=[],
                zip_path=None,
                log_path=log_path,
                work_dir=work_dir,
            )
            self._jobs[job_id] = job
            self._persist(job)
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return job

        # If not in memory, try loading from disk (helps after restart)
        job_path = os.path.join(self.root_dir, job_id, "job.json")
        if os.path.exists(job_path):
            with open(job_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            job = Job(**data)
            with self._lock:
                self._jobs[job_id] = job
            return job
        return None

    def update(self, job_id: str, **fields: Any) -> Job:
        with self._lock:
            job = self.get(job_id)
            if not job:
                raise KeyError(job_id)
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = _now_iso()
            self._persist(job)
            return job

    def append_output(self, job_id: str, language: str, video_path: str, filename: str):
        with self._lock:
            job = self.get(job_id)
            if not job:
                raise KeyError(job_id)
            job.outputs.append({"language": language, "video_path": video_path, "filename": filename})
            job.updated_at = _now_iso()
            self._persist(job)

    def set_zip(self, job_id: str, zip_path: str):
        self.update(job_id, zip_path=zip_path)

    def _persist(self, job: Job):
        path = os.path.join(self.root_dir, job.job_id, "job.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(job), f, ensure_ascii=False, indent=2)


job_store = JobStore(settings.JOBS_DIR)

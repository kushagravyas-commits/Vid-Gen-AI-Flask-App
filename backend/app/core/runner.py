from __future__ import annotations

import os
import io
import sys
import zipfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Optional

from app.core.config import settings
from app.core.jobs import job_store
from app.utils.languages import INDIAN_LANGUAGES


# In-process executor (simple). For production: Celery + Redis recommended.
_executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)


@contextmanager
def _chdir(path: str):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _run_single_language(job_id: str, lang_code: str) -> str:
    """Run the LangGraph pipeline once, inside an isolated workdir.

    Returns: absolute path to produced MP4
    """
    job = job_store.get(job_id)
    assert job and job.work_dir

    # Create per-language working directory (isolates relative outputs)
    lang_dir = os.path.join(job.work_dir, f"run_{lang_code}")
    os.makedirs(lang_dir, exist_ok=True)

    # Import *inside* to avoid import-time side effects before job dir exists.
    # IMPORTANT: Place your patched video generator at:
    # backend/app/video_engine/video_generator.py
    from app.video_engine.video_generator import app  # noqa

    inputs = {
        "user_query": job.query,
        "languages": [INDIAN_LANGUAGES[lang_code]],  # display name used in script metadata/prompt
        "style": job.style,
        "tts_lang": lang_code,  # used by patched generate_voice
    }

    # Redirect stdout/stderr to job log (append)
    log_path = job.log_path or os.path.join(job.work_dir, "job.log")
    with open(log_path, "a", encoding="utf-8") as logf:
        with _chdir(lang_dir):
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = logf, logf
            try:
                final_state = app.invoke(inputs)
            finally:
                sys.stdout, sys.stderr = old_out, old_err

    # Pipeline writes final_video.mp4 in the CWD (lang_dir)
    out_mp4 = os.path.join(lang_dir, "final_video.mp4")
    if not os.path.exists(out_mp4):
        raise FileNotFoundError(f"Expected output not found: {out_mp4}")

    return os.path.abspath(out_mp4)


def _zip_outputs(job_id: str, outputs_dir: str) -> str:
    job = job_store.get(job_id)
    assert job and job.work_dir
    zip_path = os.path.join(job.work_dir, f"{job_id}_outputs.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(outputs_dir):
            for fn in files:
                abs_path = os.path.join(root, fn)
                rel_path = os.path.relpath(abs_path, outputs_dir)
                zf.write(abs_path, arcname=rel_path)
    return zip_path


def _job_worker(job_id: str):
    job = job_store.get(job_id)
    if not job:
        return

    outputs_dir = os.path.join(job.work_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)

    try:
        job_store.update(job_id, status="RUNNING", progress_stage="starting", message="Job started")

        for idx, lang_code in enumerate(job.languages, start=1):
            job_store.update(
                job_id,
                progress_stage=f"rendering_{lang_code}",
                message=f"Rendering language {idx}/{len(job.languages)}: {INDIAN_LANGUAGES.get(lang_code, lang_code)}",
            )

            mp4_path = _run_single_language(job_id, lang_code)
            out_name = f"{job_id}_{lang_code}.mp4"
            dest_path = os.path.join(outputs_dir, out_name)
            shutil.copy2(mp4_path, dest_path)

            job_store.append_output(job_id, language=lang_code, video_path=dest_path, filename=out_name)

        # Create ZIP for download convenience
        job_store.update(job_id, progress_stage="zipping", message="Packaging outputs")
        zip_path = _zip_outputs(job_id, outputs_dir)
        job_store.set_zip(job_id, zip_path=zip_path)

        job_store.update(job_id, status="COMPLETED", progress_stage="done", message="Completed")

    except Exception as e:
        job_store.update(job_id, status="FAILED", progress_stage="failed", message="Failed", error=str(e))


def submit_job(job_id: str):
    """Submit a job to the background executor."""
    _executor.submit(_job_worker, job_id)

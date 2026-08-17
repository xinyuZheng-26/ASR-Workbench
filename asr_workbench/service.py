"""FastAPI application and the real single-worker local transcription queue."""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import shutil
import subprocess
import uuid
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .domain import JobStatus
from .model_manager import ModelManager
from .paths import AppPaths
from .store import InvalidTransition, JobStore

MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mp4", ".mov", ".mkv", ".webm",
}


class Workbench:
    def __init__(self, paths: Optional[AppPaths] = None) -> None:
        self.paths = paths or AppPaths.create()
        self.store = JobStore(self.paths.database)
        self.models = ModelManager(self.paths)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        for job_id in self.store.recover_interrupted_jobs():
            self.queue.put_nowait(job_id)
        self.worker_task = asyncio.create_task(self._consume(), name="asr-single-worker")

    async def stop(self) -> None:
        if self.worker_task is not None:
            self.worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker_task
        self.store.close()

    async def enqueue(self, job_id: str) -> None:
        self.queue.put_nowait(job_id)

    async def _consume(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await asyncio.to_thread(self._run_job, job_id)
            finally:
                self.queue.task_done()

    def _run_job(self, job_id: str) -> None:
        try:
            job = self.store.transition(job_id, JobStatus.RUNNING)
            source = Path(job["media_path"])
            prepared = self._prepare_audio(source, job_id)
            try:
                transcript = self.models.transcribe(prepared)
            finally:
                if prepared != source:
                    prepared.unlink(missing_ok=True)
            result_path = self.paths.results / (job_id + ".txt")
            result_path.write_text(transcript, encoding="utf-8")
            self.store.transition(
                job_id,
                JobStatus.COMPLETED,
                result_path=result_path,
                duration_seconds=self._duration_seconds(source),
            )
        except Exception as exc:
            reason = self._safe_error(exc)
            try:
                current = self.store.get_job(job_id)
                if current and current["status"] == JobStatus.RUNNING.value:
                    self.store.transition(job_id, JobStatus.FAILED, failure_reason=reason)
            except (InvalidTransition, KeyError):
                pass

    def _prepare_audio(self, source: Path, job_id: str) -> Path:
        """Normalize with FFmpeg when available; direct input remains the safe fallback."""
        if shutil.which("ffmpeg") is None:
            return source
        normalized = self.paths.media / (job_id + ".wav")
        command = [
            "ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(normalized),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            normalized.unlink(missing_ok=True)
            return source
        return normalized

    @staticmethod
    def _duration_seconds(source: Path) -> Optional[float]:
        if source.suffix.lower() != ".wav":
            return None
        try:
            with wave.open(str(source), "rb") as audio:
                return round(audio.getnframes() / float(audio.getframerate()), 3)
        except (OSError, wave.Error):
            return None

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).replace("\n", " ").strip()
        return message[:600] or exc.__class__.__name__


def create_app(paths: Optional[AppPaths] = None) -> FastAPI:
    workbench = Workbench(paths)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await workbench.start()
        try:
            yield
        finally:
            await workbench.stop()

    app = FastAPI(title="ASR Workbench", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.workbench = workbench
    web_root = Path(__file__).parent / "web"
    app.mount("/assets", StaticFiles(directory=str(web_root)), name="assets")

    @app.get("/")
    async def home() -> FileResponse:
        return FileResponse(web_root / "index.html")

    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True, "host_policy": "loopback-only", "model": workbench.models.snapshot()}

    @app.get("/api/model")
    async def model_status() -> Dict[str, Any]:
        return workbench.models.snapshot()

    @app.post("/api/model/download")
    async def download_model() -> Dict[str, Any]:
        # ModelScope work is explicitly initiated from the local user interface.
        return await asyncio.to_thread(workbench.models.download_and_validate)

    @app.post("/api/model/load")
    async def load_model() -> Dict[str, Any]:
        # This verifies existing files without requesting a new model download.
        return await asyncio.to_thread(workbench.models.load_if_available)

    @app.post("/api/jobs")
    async def create_job(file: UploadFile = File(...)) -> Dict[str, Any]:
        model = workbench.models.snapshot()
        if model["state"] not in {"ready", "available"}:
            raise HTTPException(status_code=409, detail=model["message"])
        if model["state"] == "available":
            model = await asyncio.to_thread(workbench.models.load_if_available)
            if model["state"] != "ready":
                raise HTTPException(status_code=409, detail=model["message"])
        original_name = Path(file.filename or "未命名文件").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=415, detail="仅支持常见音频或视频格式：%s" % ", ".join(sorted(ALLOWED_SUFFIXES)))
        stored_name = "%s%s" % (uuid.uuid4().hex, suffix)
        destination = workbench.paths.media / stored_name
        size = 0
        try:
            with destination.open("wb") as target:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="单个文件不能超过 1 GiB。")
                    target.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        job = workbench.store.create_job(original_name, stored_name, destination)
        await workbench.enqueue(job["id"])
        return public_job(job)

    @app.get("/api/jobs")
    async def list_jobs() -> Dict[str, Any]:
        return {"jobs": [public_job(job) for job in workbench.store.list_jobs()]}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> Dict[str, Any]:
        job = workbench.store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        result = public_job(job)
        if job["status"] == JobStatus.COMPLETED.value and job["result_path"]:
            result["transcript"] = Path(job["result_path"]).read_text(encoding="utf-8")
        return result

    @app.get("/api/jobs/{job_id}/download")
    async def download_txt(job_id: str) -> FileResponse:
        job = workbench.store.get_job(job_id)
        if job is None or job["status"] != JobStatus.COMPLETED.value or not job["result_path"]:
            raise HTTPException(status_code=404, detail="尚无可下载的 TXT 结果。")
        return FileResponse(
            job["result_path"],
            media_type="text/plain; charset=utf-8",
            filename=Path(job["original_name"]).stem + ".txt",
        )

    @app.post("/api/jobs/{job_id}/retry")
    async def retry_job(job_id: str) -> Dict[str, Any]:
        try:
            job = workbench.store.transition(job_id, JobStatus.QUEUED)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在。")
        except InvalidTransition:
            raise HTTPException(status_code=409, detail="只有失败任务可以重新排队。")
        await workbench.enqueue(job_id)
        return public_job(job)

    return app


def public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": job["id"],
        "original_name": job["original_name"],
        "status": job["status"],
        "duration_seconds": job["duration_seconds"],
        "failure_reason": job["failure_reason"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "mime_type": mimetypes.guess_type(job["original_name"])[0],
    }

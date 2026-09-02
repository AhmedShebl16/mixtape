"""Mixtape -- FastAPI app: serves the UI and drives downloads.

Bound to 127.0.0.1 by run.bat -- this is a local tool and must not be
reachable from the network.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import downloader, jobs

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DEFAULT_OUTPUT = BASE_DIR / "downloads"

app = FastAPI(title="Mixtape")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class NewJob(BaseModel):
    url: str
    output_dir: str | None = None


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/config")
async def config() -> dict:
    """Default output folder, plus whether ffmpeg is actually available."""
    return {
        "default_output": str(DEFAULT_OUTPUT),
        "ffmpeg": downloader.ffmpeg_path(),
    }


@app.post("/api/jobs")
async def create_job(payload: NewJob) -> dict:
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Enter a playlist URL.")

    loop = asyncio.get_running_loop()
    try:
        playlist_title, tracks = await loop.run_in_executor(None, downloader.probe, url)
    except Exception as exc:  # noqa: BLE001 - surface the reason to the UI
        raise HTTPException(status_code=400, detail=downloader._clean_error(str(exc))) from exc

    output_dir = Path(payload.output_dir).expanduser() if payload.output_dir else DEFAULT_OUTPUT
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot use that folder: {exc}") from exc

    job = jobs.create(url, output_dir, playlist_title, tracks)
    job.loop = loop
    downloader.start(job)

    return {
        "job_id": job.id,
        "playlist_title": job.playlist_title,
        "output_dir": str(output_dir),
        "tracks": [{"index": t.index, "title": t.title} for t in job.tracks],
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")

    async def stream():
        # Snapshot first, so a reconnecting client catches up immediately.
        for track in job.tracks:
            yield _sse(track.to_event())

        while True:
            try:
                event = await asyncio.wait_for(job.queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _sse(event)
            if event.get("event") == "job_complete":
                break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")
    job.cancel_event.set()
    return {"cancelled": True}

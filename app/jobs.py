"""In-memory job registry.

Single user, single process: jobs live only as long as the server does, so there
is no database here. Each job owns an asyncio.Queue that worker threads push
progress events onto and the SSE endpoint drains.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# queued -> downloading -> converting -> done | failed | cancelled
TrackStatus = str


@dataclass
class Track:
    index: int
    video_id: str
    title: str
    status: TrackStatus = "queued"
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    error: str = ""
    filename: str = ""

    def to_event(self) -> dict[str, Any]:
        return {
            "event": "track",
            "index": self.index,
            "status": self.status,
            "percent": round(self.percent, 1),
            "speed": self.speed,
            "eta": self.eta,
            "error": self.error,
            "filename": self.filename,
        }


@dataclass
class Job:
    id: str
    url: str
    output_dir: Path
    playlist_title: str
    tracks: list[Track]
    status: str = "running"  # running | complete | cancelled
    cancel_event: threading.Event = field(default_factory=threading.Event)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    loop: asyncio.AbstractEventLoop | None = None

    def publish(self, event: dict[str, Any]) -> None:
        """Push an event to the SSE stream. Safe to call from worker threads."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self.queue.put_nowait, event)
        except RuntimeError:
            # Loop shut down mid-download; nothing is listening any more.
            pass


_jobs: dict[str, Job] = {}


def create(url: str, output_dir: Path, playlist_title: str, tracks: list[Track]) -> Job:
    job = Job(
        id=uuid.uuid4().hex[:12],
        url=url,
        output_dir=output_dir,
        playlist_title=playlist_title,
        tracks=tracks,
    )
    _jobs[job.id] = job
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)

"""yt-dlp driving layer.

Tracks are probed first (cheap, flat) so the UI can render the whole list
immediately, then downloaded one video at a time on a small thread pool. Doing
one video per YoutubeDL call -- rather than handing yt-dlp the playlist -- is
what makes per-track progress and per-track error reporting possible.
"""

from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .jobs import Job, Track, ProbeTrack

# Three at a time is a deliberate ceiling: more parallelism invites throttling
# and 429s from YouTube, which slows the run down rather than speeding it up.
MAX_WORKERS = 3

# Progress hooks fire many times per second per track. Emitting all of them
# would flood the SSE stream for no visible benefit.
UPDATE_INTERVAL = 0.25

# A copy dropped in bin/ wins over PATH, so the app keeps working even if the
# system install disappears or PATH is not refreshed in this shell.
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "bin"


def ffmpeg_path() -> str:
    """Absolute path to a usable ffmpeg, or "" if there is none."""
    bundled = BUNDLED_DIR / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg") or ""


class Cancelled(Exception):
    """Raised out of a progress hook to abort an in-flight download."""


def probe(url: str) -> tuple[str, list[Track]]:
    """List a playlist's videos without downloading anything. Returns Track objects for job creation."""
    playlist_title, probe_tracks = _probe_raw(url)
    tracks = [
        Track(index=t.index, video_id=t.video_id, title=t.title)
        for t in probe_tracks
    ]
    return playlist_title, tracks


def probe_for_ui(url: str) -> tuple[str, bool, list[ProbeTrack]]:
    """Probe for UI selection: returns (playlist_title, is_playlist, probe_tracks_with_duration)."""
    playlist_title, probe_tracks = _probe_raw(url)
    is_playlist = len(probe_tracks) > 1 or (len(probe_tracks) == 1 and probe_tracks[0].video_id != "")
    # For single video, we still want to show it in selection
    return playlist_title, is_playlist, probe_tracks


def _probe_raw(url: str) -> tuple[str, list[ProbeTrack]]:
    """Internal probe returning ProbeTrack with duration."""
    opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise ValueError("Could not read that URL. Is it a public YouTube playlist or video?")

    entries = info.get("entries")
    if entries is None:
        # A single video URL rather than a playlist -- treat it as a playlist of one.
        entries = [info]
        playlist_title = "Single video"
    else:
        playlist_title = info.get("title") or "Playlist"

    probe_tracks: list[ProbeTrack] = []
    for position, entry in enumerate(entries, start=1):
        if not entry:
            # Deleted/private entries can come back as None.
            probe_tracks.append(
                ProbeTrack(
                    index=position,
                    video_id="",
                    title="(unavailable)",
                    duration=0,
                    available=False,
                )
            )
            continue
        probe_tracks.append(
            ProbeTrack(
                index=position,
                video_id=entry.get("id") or "",
                title=entry.get("title") or "(untitled)",
                duration=entry.get("duration") or 0,
                available=bool(entry.get("id")),
            )
        )

    if not probe_tracks:
        raise ValueError("That playlist has no playable videos.")
    return playlist_title, probe_tracks


def _fmt_speed(bytes_per_sec: float | None) -> str:
    if not bytes_per_sec:
        return ""
    mb = bytes_per_sec / 1_048_576
    return f"{mb:.1f} MB/s" if mb >= 0.1 else f"{bytes_per_sec / 1024:.0f} KB/s"


def _fmt_eta(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ""
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _ydl_options(job: Job, track: Track, hook, pp_hook) -> dict[str, Any]:
    # The index is baked into the literal prefix because we download videos
    # individually, so %(playlist_index)s is not available here.
    outtmpl = str(job.output_dir / f"{track.index:03d} - %(title)s.%(ext)s")
    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ],
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 5,
        "ignoreerrors": False,  # we catch per track ourselves, for real messages
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "windowsfilenames": True,
        "consoletitle": False,
    }
    bundled = BUNDLED_DIR / "ffmpeg.exe"
    if bundled.exists():
        options["ffmpeg_location"] = str(BUNDLED_DIR)
    return options


def _download_one(job: Job, track: Track) -> None:
    if job.cancel_event.is_set():
        track.status = "cancelled"
        job.publish(track.to_event())
        return

    last_emit = 0.0

    def emit(force: bool = False) -> None:
        nonlocal last_emit
        now = time.monotonic()
        if force or now - last_emit >= UPDATE_INTERVAL:
            last_emit = now
            job.publish(track.to_event())

    def hook(d: dict[str, Any]) -> None:
        if job.cancel_event.is_set():
            raise Cancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            track.status = "downloading"
            track.percent = (done / total * 100) if total else 0.0
            track.speed = _fmt_speed(d.get("speed"))
            track.eta = _fmt_eta(d.get("eta"))
            emit()
        elif d.get("status") == "finished":
            track.percent = 100.0
            track.speed = ""
            track.eta = ""
            track.status = "converting"
            emit(force=True)

    def pp_hook(d: dict[str, Any]) -> None:
        # Deliberately no cancel check: the download is already complete here,
        # and aborting mid-convert would strand the source file on disk. A
        # couple of extra seconds is a fair price for a clean output folder.
        if d.get("postprocessor") != "ExtractAudio":
            return
        if d.get("status") == "started":
            track.status = "converting"
            emit(force=True)
        elif d.get("status") == "finished":
            path = (d.get("info_dict") or {}).get("filepath")
            if path:
                track.filename = Path(path).name

    track.status = "downloading"
    emit(force=True)

    url = f"https://www.youtube.com/watch?v={track.video_id}"
    try:
        with YoutubeDL(_ydl_options(job, track, hook, pp_hook)) as ydl:
            ydl.download([url])
    except Cancelled:
        track.status = "cancelled"
        _cleanup_partials(job, track)
    except DownloadError as exc:
        if job.cancel_event.is_set():
            track.status = "cancelled"
            _cleanup_partials(job, track)
        else:
            track.status = "failed"
            track.error = _clean_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - one bad track must not kill the run
        if job.cancel_event.is_set():
            track.status = "cancelled"
            _cleanup_partials(job, track)
        else:
            track.status = "failed"
            track.error = _clean_error(str(exc))
    else:
        track.status = "done"
        track.percent = 100.0

    track.speed = ""
    track.eta = ""
    emit(force=True)


def _cleanup_partials(job: Job, track: Track) -> None:
    """Delete the half-written files an aborted download leaves behind."""
    try:
        for path in job.output_dir.glob(f"{track.index:03d} - *"):
            if path.name.endswith((".part", ".ytdl")):
                path.unlink(missing_ok=True)
    except OSError:
        pass


def _clean_error(message: str) -> str:
    """Strip yt-dlp's ANSI codes and prefixes so the UI can show the reason."""
    text = message.replace("\x1b[0;31m", "").replace("\x1b[0m", "")
    for prefix in ("ERROR: ", "[youtube] "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()[:300]


def run_job(job: Job) -> None:
    """Download every track. Blocking -- call this on its own thread."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="dl") as pool:
        futures = [pool.submit(_download_one, job, track) for track in job.tracks]
        wait(futures)

    job.status = "cancelled" if job.cancel_event.is_set() else "complete"
    job.publish(
        {
            "event": "job_complete",
            "status": job.status,
            "done": sum(1 for t in job.tracks if t.status == "done"),
            "failed": sum(1 for t in job.tracks if t.status == "failed"),
            "total": len(job.tracks),
        }
    )


def start(job: Job) -> None:
    threading.Thread(target=run_job, args=(job,), daemon=True).start()

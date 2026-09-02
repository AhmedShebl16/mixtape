# Mixtape

Turn a YouTube playlist into a folder of 320 kbps MP3s.

Paste a playlist URL, pick a folder, press Start. Mixtape lists every track up front,
then downloads and converts them with a live progress bar for each one. It runs
entirely on your own machine — there is no server, no upload, and no account.

```
Mixtape
Turn a YouTube playlist into a folder of 320 kbps MP3s.

  Playlist URL   https://www.youtube.com/playlist?list=...
  Save to folder C:\Users\you\Music\roadtrip
  [ Start ]  [ Cancel ]        Saving to C:\Users\you\Music\roadtrip

  Wild rides                                        3 of 15 done
  ─────────────────────────────────────────────────────────────
  01  Hersheypark 2026! What's New??      ██████████     done
  02  What's NEW At Universal Epic Uni…   ██████████     done
  03  Ramoji Film City Hyderabad | Com…   ██████░░░░  2.1 MB/s
  04  We Went to Canada's Wonderland…     ░░░░░░░░░░  converting
  05  Six Flags Magic Mountain 2026       ░░░░░░░░░░     queued
```

## Features

- **Whole playlists in one go** — the track list appears immediately, before any downloading starts.
- **320 kbps MP3**, the highest quality MP3 ffmpeg can produce from the source stream.
- **Live per-track progress** — speed, percentage, and the download → convert → done handoff.
- **One bad track won't stop the run.** Private, deleted, or region-blocked videos are marked
  failed with the reason and everything else keeps going.
- **Cancel any time**, leaving a clean output folder — no half-written `.part` files and no
  stray source files next to your MP3s.
- **Local only.** The server binds to `127.0.0.1` and is not reachable from your network.

## Requirements

- **Python 3.10+**
- **ffmpeg** — does the MP3 encoding (see below)

## Install

```bash
git clone https://github.com/AhmedShebl16/mixtape.git
cd mixtape

python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # macOS / Linux
```

### ffmpeg

Mixtape looks for ffmpeg in a `bin/` folder next to the app first, then falls back to your `PATH`.

**Windows** — either install it system-wide:

```powershell
winget install Gyan.FFmpeg
```

…or, if that gives you trouble, download a [static build](https://www.gyan.dev/ffmpeg/builds/)
and drop `ffmpeg.exe` into `bin/`. The bundled copy wins over `PATH`, survives reboots, and needs
no environment changes.

**macOS** — `brew install ffmpeg`  ·  **Debian/Ubuntu** — `sudo apt install ffmpeg`

The app tells you on screen if it can't find ffmpeg, so you won't discover it halfway through a playlist.

## Usage

**Windows** — double-click `run.bat`.

**Any platform:**

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Then open <http://127.0.0.1:8765>. Files land in `downloads/` unless you point it somewhere else,
named `001 - Track title.mp3` so they keep the playlist's running order.

Single video URLs work too — they're treated as a playlist of one.

## How it works

Mixtape probes the playlist *flat* first (`extract_flat`), which is a cheap metadata-only call, so
the full track list can render in about a second. It then downloads each video **individually**
rather than handing the whole playlist to yt-dlp in one call. That is the design decision that
makes per-track progress bars and per-track error messages possible, and it's why one dead video
can't take down the rest of the run.

Downloads run three at a time. That ceiling is deliberate: more parallelism invites rate limiting
from YouTube, which makes the overall run slower, not faster.

| File | Role |
|---|---|
| `app/downloader.py` | yt-dlp options, progress hooks, per-track worker |
| `app/main.py` | HTTP routes and the SSE progress stream |
| `app/jobs.py` | in-memory job registry |
| `web/` | the interface — plain HTML, CSS, and JavaScript, no build step |

## Configuration

Both live at the top of `app/downloader.py`:

```python
MAX_WORKERS = 3        # simultaneous downloads
UPDATE_INTERVAL = 0.25 # seconds between progress updates per track
```

To change the audio format or bitrate, edit the `FFmpegExtractAudio` postprocessor in
`_ydl_options()` — `preferredcodec` accepts `m4a`, `opus`, `flac`, and others.

## A note on "320 kbps"

YouTube's audio is already lossy — typically Opus at around 128–160 kbps. Encoding that to
320 kbps MP3 is a *transparent* transcode: it preserves everything the source has, and 320 is the
right setting to avoid adding any loss of your own. But it does not invent quality that was never
there, and no downloader can. Anyone promising "better than the original" is selling you a bigger
file, not a better one.

If you'd rather keep the untouched source audio, set `preferredcodec` to `opus` or use
`'format': 'bestaudio'` with the postprocessor removed.

## Roadmap

Deliberately left out of the first version, each a small addition:

- ID3 tags and embedded cover art (`FFmpegMetadata` + `EmbedThumbnail` postprocessors)
- A download archive, so re-running a playlist only fetches new tracks
- Keeping the original untranscoded audio alongside the MP3
- A packaged Windows `.exe` with ffmpeg bundled

## Responsible use

Mixtape is for material you have the right to download — your own uploads, Creative Commons and
public-domain works, and content whose license or owner permits it. Downloading copyrighted music
you don't own rights to may breach YouTube's Terms of Service and your local copyright law.
You are responsible for what you do with it.

## Built with

[yt-dlp](https://github.com/yt-dlp/yt-dlp) does the extraction, [ffmpeg](https://ffmpeg.org/) the
encoding, and [FastAPI](https://fastapi.tiangolo.com/) serves it. Mixtape is a small amount of glue
around three excellent projects.

## License

[MIT](LICENSE)

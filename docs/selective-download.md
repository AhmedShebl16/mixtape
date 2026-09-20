# Feature: Selective Playlist Download

## Overview
Allow users to fetch a playlist (or single video), preview all tracks with checkboxes, select specific videos to download, then start the download job with only the selected tracks.

## User Flow
1. User enters a YouTube URL (playlist or single video) and output folder
2. User clicks "Fetch" (new button, replaces "Start")
3. Backend probes the URL, returns full track list
4. Frontend renders track list with checkboxes (all checked by default)
5. User toggles selections, can "Select All" / "Deselect All"
6. User clicks "Download Selected" (new primary action)
6. Backend creates job with only selected tracks, starts download
7. Progress UI same as before but only for selected tracks

## API Changes

### POST /api/jobs (modified)
**Request:**
```json
{
  "url": "https://youtube.com/playlist?list=...",
  "output_dir": "C:/Music/roadtrip",
  "track_indices": [1, 3, 5]  // optional; if omitted, download all
}
```

**Response:** Same as before but `tracks` only includes selected tracks.

### POST /api/probe (new endpoint)
**Request:**
```json
{ "url": "https://youtube.com/playlist?list=..." }
```

**Response:**
```json
{
  "playlist_title": "My Playlist",
  "is_playlist": true,
  "tracks": [
    { "index": 1, "video_id": "abc123", "title": "Track One", "duration": 210 },
    { "index": 2, "video_id": "def456", "title": "Track Two", "duration": 185 },
    ...
  ]
}
```

For single video: `is_playlist: false`, `tracks` has one entry.

## Frontend Changes

### New UI States
1. **Initial** — URL input + output folder + "Fetch" button
2. **Selection** — Track list with checkboxes, "Select All/None", "Download Selected" button, "Back" button
3. **Downloading** — Existing progress UI (unchanged)

### Track List Item (Selection Mode)
```
[☑] 01  Track Title                    3:30
[☐] 02  Another Track                  2:45
```
- Checkbox left of index
- Duration shown (from probe)
- Hover highlights row
- Keyboard: Space to toggle, Enter to confirm

## Backend Changes

### app/main.py
- Add `/api/probe` endpoint
- Modify `/api/jobs` to accept optional `track_indices`
- Filter tracks before creating job

### app/downloader.py
- `probe()` returns duration + more metadata
- `create_job` accepts pre-filtered track list

### app/jobs.py
- No changes needed (tracks already flexible)

## Data Model Additions

Track (probe response):
```python
@dataclass
class ProbeTrack:
    index: int
    video_id: str
    title: str
    duration: int  # seconds, 0 if unknown
```

## Configuration
No new config needed.

## Edge Cases
- Empty selection → disable "Download Selected", show inline message
- Single video URL → skip selection step, go straight to download (or show single-item selection)
- Very long playlists (100+) — virtualize list or paginate (v1: render all, CSS handles scroll)
- Private/deleted videos → probe marks them, UI shows disabled checkbox with "Unavailable" label

## Testing Checklist
- [ ] Playlist URL → shows all tracks with checkboxes
- [ ] Single video URL → shows one track
- [ ] Select All / Deselect All works
- [ ] Individual toggle works
- [ ] "Back" returns to URL input
- [ ] Download only processes selected tracks
- [ ] Progress UI shows correct track count
- [ ] Cancel works mid-download
- [ ] Empty selection blocked
- [ ] Private videos handled gracefully

## Future Enhancements
- Search/filter tracks in selection view
- Sort by title/duration
- Select by range (Shift+click)
- Keyboard shortcuts (A=all, N=none, D=download)
- Persist selection in localStorage
- Show estimated total size/time
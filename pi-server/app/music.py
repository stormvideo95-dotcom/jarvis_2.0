"""Music for the Nest: a queue of YouTube tracks, resolved to stream URLs with yt-dlp.

Tracks are dicts in the Music AI format: {"id", "title", "artists", ...}.
"""
import threading

_lock = threading.RLock()
_queue: list[dict] = []
_index = -1


def _ydl(opts: dict):
    from yt_dlp import YoutubeDL

    return YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, **opts})


def _resolve(meta: dict) -> dict:
    with _ydl({"format": "bestaudio[ext=m4a]/bestaudio"}) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={meta['id']}", download=False)
    ext = info.get("ext") or "m4a"
    ctype = {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm"}.get(ext, "audio/mp4")
    title = meta.get("title") or info.get("title") or "Muziek"
    full = {**meta, "title": title}
    if not full.get("artists") and info.get("uploader"):
        full["artists"] = [info["uploader"]]
    if not full.get("duration") and info.get("duration"):
        full["duration"] = int(info["duration"])
    return {"id": meta["id"], "title": title, "url": info["url"], "type": ctype, "meta": full}


def _advance(start: int) -> dict | None:
    global _index
    i = start
    while i < len(_queue):
        try:
            track = _resolve(_queue[i])
            _queue[i] = track["meta"]
            _index = i
            return track
        except Exception:  # unplayable video, try the next one
            i += 1
    return None


def set_queue(tracks: list[dict]) -> dict | None:
    """Replace the queue (e.g. taken over from the phone) and resolve the first track."""
    global _queue
    with _lock:
        _queue = [t for t in tracks if t and t.get("id")]
        return _advance(0)


def search(query: str) -> dict | None:
    with _ydl({"extract_flat": "in_playlist"}) as y:
        info = y.extract_info(f"ytsearch8:{query}", download=False)
    tracks = [{"id": e["id"], "title": e.get("title") or "",
               "artists": [e["channel"]] if e.get("channel") else []}
              for e in (info.get("entries") or []) if e and e.get("id")]
    return set_queue(tracks)


def next_track() -> dict | None:
    with _lock:
        return _advance(_index + 1)


def current() -> dict | None:
    with _lock:
        return _queue[_index] if 0 <= _index < len(_queue) else None


def upcoming(n: int = 25) -> list[dict]:
    with _lock:
        return _queue[_index + 1: _index + 1 + n] if _index >= 0 else []

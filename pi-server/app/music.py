"""Music for the Nest: a queue of YouTube tracks.

Songs are downloaded to the Pi (data/music_cache, max ~1.5 GB, oldest removed first)
and served to the Nest from Jarvis itself: the Nest can't open YouTube's own links.

Tracks are dicts in the Music AI format: {"id", "title", "artists", ...}.
"""
import os
import threading

from . import config

CACHE = os.path.join(os.path.dirname(config.SPEAKER_FILE), "music_cache")
CACHE_MAX = 1500 * 1024 * 1024

_lock = threading.RLock()
_queue: list[dict] = []
_index = -1


def _ydl(opts: dict):
    from yt_dlp import YoutubeDL

    return YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, **opts})


def _trim_cache():
    files = sorted((os.path.join(CACHE, f) for f in os.listdir(CACHE)), key=os.path.getmtime)
    total = sum(os.path.getsize(f) for f in files)
    while files and total > CACHE_MAX:
        f = files.pop(0)
        total -= os.path.getsize(f)
        os.remove(f)


def _download(video_id: str) -> tuple[str, dict]:
    """Download the audio once (m4a), return (filename, info)."""
    os.makedirs(CACHE, exist_ok=True)
    for f in os.listdir(CACHE):
        if f.startswith(video_id + "."):
            os.utime(os.path.join(CACHE, f))
            return f, {}
    opts = {"format": "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio",
            "outtmpl": os.path.join(CACHE, "%(id)s.%(ext)s"), "noprogress": True, "retries": 3}
    with _ydl(opts) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    name = os.path.basename(info.get("requested_downloads", [{}])[0].get("filepath") or
                            f"{video_id}.{info.get('ext', 'm4a')}")
    try:
        _trim_cache()
    except OSError:
        pass
    return name, info


def _resolve(meta: dict) -> dict:
    name, info = _download(meta["id"])
    ext = name.rsplit(".", 1)[-1]
    ctype = {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm", "opus": "audio/ogg"}.get(ext, "audio/mp4")
    title = meta.get("title") or info.get("title") or "Muziek"
    full = {**meta, "title": title}
    if not full.get("artists") and info.get("uploader"):
        full["artists"] = [info["uploader"]]
    if not full.get("duration") and info.get("duration"):
        full["duration"] = int(info["duration"])
    url = f"{config.PUBLIC_URL}/media/{name}"
    return {"id": meta["id"], "title": title, "url": url, "type": ctype, "meta": full}


def prefetch(n: int = 1):
    """Download the next song(s) in the background so they start instantly."""
    def run():
        for meta in upcoming(n):
            try:
                _download(meta["id"])
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


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

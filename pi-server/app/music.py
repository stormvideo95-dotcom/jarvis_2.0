"""Find music on YouTube with yt-dlp and hand stream URLs to the Nest Mini."""
from . import config  # noqa: F401  (kept for future Music AI settings)

_queue: list[str] = []   # video ids from the last search
_index = -1


def _ydl(opts: dict):
    from yt_dlp import YoutubeDL

    return YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, **opts})


def _resolve(video_id: str) -> dict:
    with _ydl({"format": "bestaudio[ext=m4a]/bestaudio"}) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    ext = info.get("ext") or "m4a"
    ctype = {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm"}.get(ext, "audio/mp4")
    return {"title": info.get("title") or "Muziek", "url": info["url"], "type": ctype}


def search(query: str) -> dict:
    """Search YouTube, remember the results, return the first playable track."""
    global _queue, _index
    with _ydl({"extract_flat": "in_playlist"}) as y:
        info = y.extract_info(f"ytsearch8:{query}", download=False)
    _queue = [e["id"] for e in (info.get("entries") or []) if e and e.get("id")]
    _index = -1
    return next_track()


def next_track() -> dict | None:
    global _index
    while _index + 1 < len(_queue):
        _index += 1
        try:
            return _resolve(_queue[_index])
        except Exception:  # unplayable video, try the next one
            continue
    return None

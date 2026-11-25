"""Talk to the Google Nest Mini as a normal Cast device (option 2: Jarvis takes over).

The Nest stays a regular Cast speaker for every other app. When Jarvis speaks it
casts its voice; if Jarvis' own music was playing it resumes it afterwards at the
same spot. Another app's cast (Spotify, YouTube...) is stopped by Jarvis' reply.
"""
import json
import threading
import time

from . import config


class Nest:
    def __init__(self):
        self._cast = None
        self._target = None
        self._lock = threading.RLock()
        self.music = None  # {"title","url","type"} of the song Jarvis is playing
        self._interrupt = threading.Event()
        self.speaking_until = 0.0   # while time < this, Jarvis is talking
        self.speaking_text = ""

    # ---- connection -------------------------------------------------------
    @staticmethod
    def chosen() -> dict:
        """Speaker picked in the terminal (speaker.json), else the .env values."""
        try:
            with open(config.SPEAKER_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return {"name": data.get("name", ""), "ip": data.get("ip", "")}
        except (OSError, ValueError):
            return {"name": config.NEST_NAME, "ip": config.NEST_IP}

    def _device(self):
        import pychromecast

        want = self.chosen()
        if (self._cast is not None and self._cast.socket_client.is_connected
                and self._target == want):
            return self._cast
        if self._cast is not None:  # speaker changed or connection lost
            try:
                self._cast.disconnect(timeout=3)
            except Exception:
                pass
            self._cast = None
        casts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=[want["name"]] if want["name"] else None,
            known_hosts=[want["ip"]] if want["ip"] else None,
            discovery_timeout=10,
        )
        try:
            browser.stop_discovery()
        except Exception:
            pass
        if not casts:
            raise RuntimeError("Nest Mini not found; check NEST_NAME / NEST_IP")
        cast = casts[0]
        cast.wait(timeout=10)
        self._cast = cast
        self._target = want
        return cast

    def _mc(self):
        return self._device().media_controller

    def _play(self, url, ctype, title, start=0.0):
        mc = self._mc()
        mc.play_media(url, ctype, title=title, current_time=start, stream_type="BUFFERED")
        mc.block_until_active(timeout=25)

    def _jarvis_music_position(self):
        """Seconds into Jarvis' own song if it is what the Nest is playing, else None."""
        if not self.music:
            return None
        st = self._mc().status
        if st.content_id != self.music["url"] or st.player_state not in ("PLAYING", "BUFFERING"):
            return None
        return float(getattr(st, "adjusted_current_time", None) or st.current_time or 0.0)

    # ---- public -----------------------------------------------------------
    def speak(self, url: str, seconds: float, then=None, text: str = ""):
        """Cast a reply. Runs in the background so the board gets an answer fast."""
        def run():
            with self._lock:
                resume_at = self._jarvis_music_position()
                self._interrupt.clear()
                self._play(url, "audio/wav", "Jarvis")
                self.speaking_text = text
                self.speaking_until = time.time() + seconds + 1.0
                stopped = self._interrupt.wait(seconds + 1.5)
                self.speaking_until = 0.0
                self.speaking_text = ""
                if stopped:            # "stop!" -> silence, nothing else
                    return
                if then is not None:
                    then()
                elif resume_at is not None:
                    self._play(self.music["url"], self.music["type"], self.music["title"], resume_at)
        threading.Thread(target=run, daemon=True).start()

    def talking(self):
        """Text Jarvis is saying right now, or None when it is quiet."""
        return self.speaking_text if time.time() < self.speaking_until else None

    def stop_speaking(self):
        if time.time() < self.speaking_until:
            self._interrupt.set()
            try:
                self._mc().stop()
            except Exception:
                pass

    def play_track(self, track: dict, start: float = 0.0):
        with self._lock:
            self.music = track
            self._play(track["url"], track["type"], track["title"], start)
        try:
            from . import music
            music.prefetch(1)   # next song ready before this one ends
        except Exception:
            pass

    def music_status(self):
        """(state, seconds) of Jarvis' own song on the Nest; state is None if something else plays."""
        if not self.music or self._cast is None:
            return None, 0.0
        st = self._mc().status
        if st.content_id != self.music["url"]:
            return None, 0.0
        pos = float(getattr(st, "adjusted_current_time", None) or st.current_time or 0.0)
        state = st.player_state
        if state == "IDLE" and getattr(st, "idle_reason", None) == "FINISHED":
            state = "FINISHED"
        return state, pos

    def pause(self):
        self._mc().pause()

    def resume(self):
        mc = self._mc()
        st = mc.status
        if self.music and (st.content_id != self.music["url"] or st.player_state in ("IDLE", "UNKNOWN")):
            # the Nest forgot the song (stopped, other app, restart): start it again
            pos = float(getattr(st, "adjusted_current_time", None) or st.current_time or 0.0) \
                if st.content_id == self.music["url"] else 0.0
            self.play_track(self.music, pos)
        else:
            mc.play()

    def stop(self):
        self.music = None
        self._mc().stop()

    def volume(self, level: int):
        self._device().set_volume(max(0, min(100, int(level))) / 100.0)

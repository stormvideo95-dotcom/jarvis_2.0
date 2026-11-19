# Jarvis 2.0

Hold **BOOT** on the round board → talk → let go → Jarvis answers on your **Nest Mini**.

```
1.85" board (ears) ──Wi-Fi──▶ Umbrel Pi 5 (jarvis) ──▶ NVIDIA cloud (Whisper + Llama)
                                    │
                                    └──cast──▶ Nest Mini (voice + music)
```

## Install in 2 commands

**1. On the Umbrel Pi** (SSH in with `ssh umbrel@umbrel.local`):

```bash
curl -fsSL https://raw.githubusercontent.com/stormvideo95-dotcom/jarvis_2.0/main/install-pi.sh | bash
```

It asks for your NVIDIA key once, finds the Pi's IP, builds and starts Jarvis, and lets you pick your Nest speaker.
At the end it prints the Mac command below **with your Pi IP and key already filled in**.

**2. On your Mac** (round board plugged in with USB-C):

```bash
curl -fsSL https://raw.githubusercontent.com/stormvideo95-dotcom/jarvis_2.0/main/flash-mac.sh | PI_IP=<pi-ip> JARVIS_KEY=<key> bash
```

It installs arduino-cli + ESP32 support (first time only), asks your Wi-Fi name and password, and flashes the board.

### Handy later

- Change speaker: `docker exec -it jarvis python -m app.pick_speaker` (add `sudo` if needed)
- Update Jarvis: run the Pi command again (your `.env` is kept)
- Logs: `docker logs -f jarvis` · Status page: `http://<pi-ip>:8765`
- Flash fails? Hold BOOT, press RST, let go of BOOT, run the Mac command again.

## Things you can say

| Say | Jarvis does |
|---|---|
| "Zet phonk op" | Plays phonk on the Nest |
| "Volgende" / "pauze" / "verder" / "stop" | Controls the music (no talking) |
| "Zet het volume op 30" | Volume |
| "Timer van 10 minuten voor de pizza" | Says it when time is up |
| Any question | Short spoken answer |

## Good to know

- The Nest stays a normal Cast speaker for all other apps. If another app is casting, Jarvis takes over (option 2).
- When Jarvis answers during its own music, the song continues at the same spot after.
- Board heard you badly? Raise `MIC_GAIN` in the sketch (4 → 6 or 8).
- Keep `.env` and `secrets.h` private (they hold your NVIDIA key) — never push them to GitHub.

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
At the end it prints the Pi address and Jarvis key you need for the board setup.

**2. Flash the board** (Chrome on your Mac, board on USB-C), nothing to install:

👉 **https://stormvideo95-dotcom.github.io/jarvis_2.0/**

Then press RST, join the Wi-Fi **Jarvis-Setup** with your phone and fill in your Wi-Fi, the Pi address and the Jarvis key
(the Pi install prints both). Hold BOOT 10 s any time to open that setup again.

### Handy later

- Change speaker: `docker exec -it jarvis python -m app.pick_speaker` (add `sudo` if needed)
- Update Jarvis: run the Pi command again (your `.env` is kept)
- Logs: `docker logs -f jarvis` · Status page: `http://<pi-ip>:8790`
- Flash fails? Hold BOOT, press RST, let go of BOOT, click Flash again.

## Button or wake word

On the Jarvis page (`http://<pi-ip>:8790`) choose **Knop (BOOT)** or **Wake word**.
Wake words: **Hey Jarvis, Alexa, Hey Mycroft, Hey Rhasspy** (openWakeWord, runs on the Pi, audio never leaves your home).
In wake word mode the board streams its mic to the Pi; BOOT keeps working too. A ding on the Nest means "I'm listening".

## Home Assistant

The Pi installer asks once for a Home Assistant long-lived token
(HA: your name bottom left → Security → Long-lived access tokens). Jarvis can control
lights, switches, scenes, fans and the thermostat (`HA_DOMAINS` in `.env`) and read temperatures.
Locks, alarms and garage doors are left out on purpose.

## Study mode

Say **"Jarvis, start studiemodus"**. Jarvis asks: what to study (**NW, HB, Frans**), which game
(**quiz kahoot** = A-D with points, **quiz type** = open questions, **quiz mix** = everything mixed)
and how many questions (a number, or "tot ik stop zeg"). Questions come from your own study material
in `pi-server/app/leerstof/` (from Storm Study). Jarvis listens by itself after every question; say **stop** to end.

## Say "stop"

While Jarvis is talking you can say **stop** (or stoppen, zwijg, hou op, genoeg) and it goes quiet right away.
In button mode the board keeps the mic open for 30 s after you talk, so it hears you.

## Music AI (phone ↔ Nest ↔ Mac)

Jarvis joins your Music AI taste server (`MUSIC_AI_URL`, default `http://127.0.0.1:8765`) as the device **Jarvis (Nest)**.
First time: the Jarvis page shows a 6-digit code → Music AI app → Settings → Taste AI → **Add a device**.
Then: *"speel mijn gsm hier verder"*, *"zet het verder op mijn Mac"*, or use **Play on → Jarvis (Nest)** in the app.
No APK update needed.

## Things you can say

| Say | Jarvis does |
|---|---|
| "Zet phonk op" | Plays phonk on the Nest |
| "Volgende" / "pauze" / "verder" / "stop" | Controls the music (no talking) |
| "Zet het volume op 30" | Volume |
| "Timer van 10 minuten voor de pizza" | Says it when time is up |
| "Doe de lichten aan" / "Hoe warm is het binnen?" | Home Assistant |
| Any question | Short spoken answer |

## Good to know

- The Nest stays a normal Cast speaker for all other apps. If another app is casting, Jarvis takes over (option 2).
- When Jarvis answers during its own music, the song continues at the same spot after.
- Board heard you badly? Raise `MIC_GAIN` in the sketch (4 → 6 or 8).
- Your NVIDIA key lives only in `.env` on the Pi; your Wi-Fi password only on the board. Neither is in this repo.

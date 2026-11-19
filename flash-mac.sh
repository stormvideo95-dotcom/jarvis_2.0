#!/usr/bin/env bash
# Jarvis 2.0 — one-command flash of the round ESP32-S3 board from a Mac
#   curl -fsSL https://raw.githubusercontent.com/stormvideo95-dotcom/jarvis_2.0/main/flash-mac.sh | PI_IP=... JARVIS_KEY=... bash
# (the Pi installer prints this line with PI_IP and JARVIS_KEY already filled in)
set -euo pipefail

REPO="stormvideo95-dotcom/jarvis_2.0"
ESP_INDEX="https://espressif.github.io/arduino-esp32/package_esp32_index.json"
FQBN="esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,CDCOnBoot=cdc"
WORK="$HOME/.jarvis-board"
TTY=/dev/tty
say() { printf "\n\033[1;33m▶ %s\033[0m\n" "$*"; }
ok()  { printf "\033[1;32m✔ %s\033[0m\n" "$*"; }
ask() { printf "%s" "$1" > $TTY; read -r REPLY < $TTY; }

# ---- 1. arduino-cli ---------------------------------------------------------
mkdir -p "$WORK/bin"; export PATH="$WORK/bin:$PATH"
if ! command -v arduino-cli >/dev/null; then
  say "Installing arduino-cli"
  if command -v brew >/dev/null; then
    brew install arduino-cli
  else
    ARCH=$( [ "$(uname -m)" = "arm64" ] && echo "ARM64" || echo "64bit" )
    curl -fsSL "https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_macOS_${ARCH}.tar.gz" \
      | tar xz -C "$WORK/bin" arduino-cli
  fi
fi
ok "arduino-cli ready"

say "Installing ESP32 board support (first time ~5 minutes)"
arduino-cli core update-index --additional-urls "$ESP_INDEX" >/dev/null
arduino-cli core install esp32:esp32 --additional-urls "$ESP_INDEX"
ok "ESP32 support ready"

# ---- 2. code + secrets ------------------------------------------------------
say "Downloading the Jarvis board code"
rm -rf "$WORK/src"; mkdir -p "$WORK/src"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/main" | tar xz -C "$WORK/src" --strip-components=1
SKETCH="$WORK/src/board/jarvis_board"

WIFI_NOW=$(networksetup -getairportnetwork en0 2>/dev/null | sed -n 's/^Current Wi-Fi Network: //p' || true)
ask "Wi-Fi name (2.4 GHz)${WIFI_NOW:+ [$WIFI_NOW]}: "; SSID=${REPLY:-$WIFI_NOW}
printf "Wi-Fi password: " > $TTY; read -rs PASS < $TTY; echo > $TTY
[ -n "${PI_IP:-}" ]      || { ask "Umbrel Pi IP (e.g. 192.168.1.10): "; PI_IP=$REPLY; }
[ -n "${JARVIS_KEY:-}" ] || { ask "JARVIS_KEY (from the Pi's .env): "; JARVIS_KEY=$REPLY; }

esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
cat > "$SKETCH/secrets.h" <<EOF
#pragma once
#define WIFI_SSID   "$(esc "$SSID")"
#define WIFI_PASS   "$(esc "$PASS")"
#define JARVIS_URL  "http://$PI_IP:8765"
#define JARVIS_KEY  "$(esc "$JARVIS_KEY")"
EOF
ok "Settings written (Wi-Fi $SSID, Pi $PI_IP)"

# ---- 3. find the board ------------------------------------------------------
PORT=$(ls /dev/cu.usbmodem* /dev/cu.usbserial* 2>/dev/null | head -1 || true)
if [ -z "$PORT" ]; then
  echo "No board found. Plug the round board in with USB-C and run this command again."
  echo "Still nothing? Hold BOOT, plug it in, let go of BOOT, then try again."
  exit 1
fi
ok "Board on $PORT"

# ---- 4. compile + flash -----------------------------------------------------
say "Building and flashing Jarvis"
if ! arduino-cli compile --upload -p "$PORT" --fqbn "$FQBN" "$SKETCH"; then
  echo
  echo "Flashing failed. Hold BOOT, press RST once, let go of BOOT, then run this command again."
  exit 1
fi
ok "Flashed! Press RST once on the board."

cat <<EOF

────────────────────────────────────────────────────────────
  Done. Hold BOOT on the round board, talk, let go.
  Jarvis answers on your Nest.

  See what the board is doing:
  arduino-cli monitor -p $PORT -c baudrate=115200
────────────────────────────────────────────────────────────
EOF

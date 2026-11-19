#!/usr/bin/env bash
# Jarvis 2.0 — one-command install / update for the Umbrel Pi
#   curl -fsSL https://raw.githubusercontent.com/stormvideo95-dotcom/jarvis_2.0/main/install-pi.sh | bash
set -euo pipefail

REPO="stormvideo95-dotcom/jarvis_2.0"
DIR="$HOME/jarvis"
TTY=/dev/tty
say()  { printf "\n\033[1;33m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✔ %s\033[0m\n" "$*"; }

DOCKER="docker"
$DOCKER ps >/dev/null 2>&1 || DOCKER="sudo docker"

say "Downloading Jarvis 2.0"
TMP=$(mktemp -d)
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/main" | tar xz -C "$TMP"
mkdir -p "$DIR/data"
cp -r "$TMP"/*/pi-server/. "$DIR/"     # never overwrites your .env (it is not in the repo)
rm -rf "$TMP"
ok "Files in $DIR"

cd "$DIR"
PI_IP=$(hostname -I | tr ' ' '\n' | grep -E '^[0-9.]+$' | grep -Ev '^(100\.|172\.|127\.)' | head -1 || true)

if [ ! -f .env ]; then
  say "First time setup"
  cp .env.example .env
  printf "Paste your NVIDIA key (nvapi-...): " > $TTY
  read -rs NVKEY < $TTY; echo > $TTY
  [ -n "$NVKEY" ] || { echo "No key given, stopping."; exit 1; }
  JKEY=$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)
  sed -i "s#^NVIDIA_API_KEY=.*#NVIDIA_API_KEY=$NVKEY#" .env
  sed -i "s#^JARVIS_KEY=.*#JARVIS_KEY=$JKEY#" .env
  sed -i "s#^PUBLIC_URL=.*#PUBLIC_URL=http://$PI_IP:8790#" .env
  ok "Saved .env (Pi IP $PI_IP)"
else
  ok "Keeping your existing .env"
  # Jarvis moved from port 8765 (clashed with another app) to 8790
  if grep -q '^PORT=8765' .env; then
    sed -i 's#^PORT=8765#PORT=8790#; s#:8765#:8790#g' .env
    ok "Moved Jarvis to port 8790"
  fi
  # old default model was removed by NVIDIA
  if grep -Eq '^NVIDIA_MODEL=(meta/llama-3.3-70b-instruct|google/gemma-4-31b-it)$' .env; then
    sed -i 's#^NVIDIA_MODEL=.*#NVIDIA_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b#' .env
    rm -f data/model.txt
    ok "Switched AI model to nvidia/nemotron-3.5-lightning-30b-a3b (fastest on NVIDIA right now)"
  fi
fi
PORT=$(grep '^PORT=' .env | cut -d= -f2-); PORT=${PORT:-8790}
if command -v ss >/dev/null && ss -ltn | grep -q ":$PORT " && ! $DOCKER ps --format '{{.Names}}' | grep -qx jarvis; then
  echo "Port $PORT is already used by another app. Change PORT and PUBLIC_URL in $DIR/.env, then run this again."
  exit 1
fi
JKEY=$(grep '^JARVIS_KEY=' .env | cut -d= -f2-)

say "Building and starting Jarvis (first time takes a few minutes)"
$DOCKER compose up -d --build
ok "Jarvis is running"

say "Pick the speaker Jarvis talks on"
sleep 3
$DOCKER exec -it jarvis python -m app.pick_speaker < $TTY || echo "Run later: $DOCKER exec -it jarvis python -m app.pick_speaker"

cat <<EOF

────────────────────────────────────────────────────────────
  Jarvis 2.0 is live:  http://$PI_IP:$PORT

  Now flash the round board (Chrome on your Mac, board on USB-C):
  https://stormvideo95-dotcom.github.io/jarvis_2.0/

  In the phone setup page ("Jarvis-Setup" Wi-Fi) fill in:
    Jarvis on the Pi:  http://$PI_IP:$PORT
    Jarvis key:        $JKEY

  Change speaker later:  $DOCKER exec -it jarvis python -m app.pick_speaker
  Update Jarvis later:   run the same install command again
────────────────────────────────────────────────────────────
EOF

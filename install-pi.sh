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

# ---- Storm Study link (asked once) ----
if ! grep -q '^STUDY_JARVIS_TOKEN=' .env; then
  printf '\n# Storm Study\nSTUDY_URL=https://study.ictstorm.com\nSTUDY_JARVIS_TOKEN=\n' >> .env
fi
if [ -z "$(grep '^STUDY_JARVIS_TOKEN=' .env | cut -d= -f2-)" ] && [ ! -f data/.study_skipped ]; then
  say "Connect Storm Study (optional)"
  echo "On study.ictstorm.com: your account -> Jarvis -> make a Jarvis code (starts with jv_)."
  printf "Paste the Jarvis code (or press Enter to skip): " > $TTY
  read -rs JVCODE < $TTY; echo > $TTY
  if [ -n "$JVCODE" ]; then
    sed -i "s#^STUDY_JARVIS_TOKEN=.*#STUDY_JARVIS_TOKEN=$JVCODE#" .env
    CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 8 -H "Authorization: Bearer $JVCODE" https://study.ictstorm.com/api/jarvis || true)
    case "$CODE" in
      200) ok "Storm Study connected" ;;
      401) echo "Saved, but Storm Study says the code is wrong or expired. Run this again with a new code." ;;
      *)   echo "Saved. Storm Study did not answer yet (HTTP $CODE); Jarvis will try again later." ;;
    esac
  else
    touch data/.study_skipped
    echo "Skipped. To add it later: rm $DIR/data/.study_skipped and run this install again."
  fi
fi

# ---- Home Assistant link (asked once) ----
if ! grep -q '^HA_URL=' .env; then
  printf '\n# Home Assistant\nHA_URL=http://127.0.0.1:8123\nHA_TOKEN=\nHA_DOMAINS=light,switch,scene,fan,climate,input_boolean\n' >> .env
fi
if [ -z "$(grep '^HA_TOKEN=' .env | cut -d= -f2-)" ] && [ ! -f data/.ha_skipped ]; then
  say "Connect Home Assistant (optional)"
  echo "In Home Assistant: click your name (bottom left) -> Security -> Long-lived access tokens -> Create token."
  printf "Paste the Home Assistant token (or press Enter to skip): " > $TTY
  read -rs HATOKEN < $TTY; echo > $TTY
  if [ -n "$HATOKEN" ]; then
    sed -i "s#^HA_TOKEN=.*#HA_TOKEN=$HATOKEN#" .env
    if curl -fsS -m 5 -H "Authorization: Bearer $HATOKEN" http://127.0.0.1:8123/api/ >/dev/null 2>&1; then
      ok "Home Assistant connected"
    else
      echo "Saved, but Home Assistant did not answer on http://127.0.0.1:8123 yet. Check the token or HA_URL in $DIR/.env"
    fi
  else
    touch data/.ha_skipped
    echo "Skipped. To add it later: rm $DIR/data/.ha_skipped and run this install again."
  fi
fi

# ---- School buddy + Google Drive (asked once) ----
if ! grep -q '^SCHOOL_SITE=' .env; then
  printf '\n# School buddy (Jarvis School app)\nSCHOOL_SITE=https://sites.google.com/labonderwijs.be/humanbody/homepage\nSCHOOL_ROUTE=z\nSCHOOL_WEEK1=2026-11-09\nSCHOOL_REMIND=19:00\nSCHOOL_PLANNER_REMIND=18:00\n' >> .env
fi
if ! grep -q '^DRIVE_SECRET=' .env; then
  DSECRET=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)
  printf '\n# Google Drive saver (school-drive/README.md)\nDRIVE_SCRIPT_URL=\nDRIVE_SECRET=%s\n' "$DSECRET" >> .env
fi
if [ -z "$(grep '^DRIVE_SCRIPT_URL=' .env | cut -d= -f2-)" ] && [ ! -f data/.drive_skipped ]; then
  say "Connect Google Drive for Jarvis School (optional)"
  echo "Follow https://github.com/$REPO/blob/main/school-drive/README.md"
  echo "Your DRIVE_SECRET (paste it in the script):  $(grep '^DRIVE_SECRET=' .env | cut -d= -f2-)"
  printf "Paste the Web app URL (ends in /exec), or press Enter to skip: " > $TTY
  read -r DURL < $TTY
  if [ -n "$DURL" ]; then
    sed -i "s#^DRIVE_SCRIPT_URL=.*#DRIVE_SCRIPT_URL=$DURL#" .env
    DS=$(grep '^DRIVE_SECRET=' .env | cut -d= -f2-)
    if curl -fsSL -m 20 -H 'Content-Type: application/json' -d "{\"action\":\"ping\",\"secret\":\"$DS\"}" "$DURL" | grep -q '"ok":true'; then
      ok "Google Drive connected (folder: Jarvis School)"
    else
      echo "Saved, but the script did not say ok. Check the SECRET in the script and that it is deployed for 'Anyone'."
    fi
  else
    touch data/.drive_skipped
    echo "Skipped. Scans stay on the Pi. To add it later: rm $DIR/data/.drive_skipped and run this install again."
  fi
fi

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

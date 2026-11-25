#!/data/data/com.termux/files/usr/bin/bash
# Ninja Studio engine on the phone: run ONCE inside the Termux app.
#
#   bash termux-setup.sh                  (from a copy of this project, e.g. pushed with adb)
#   curl -fsSL <raw link to this file> | bash   (downloads the project from GitHub)
#
# Installs Python + FFmpeg + the app's packages (about 400 MB, 5-10 minutes), puts the app in ~/ninjastudio,
# writes ~/ninjastudio-start.sh / ~/ninjastudio-stop.sh and lets the Ninja Studio phone app start the engine by itself.
# Run it again any time to update. Your clips and settings in ~/ninjastudio-data are kept.
set -e
ZIP="${NINJA_ZIP:-https://github.com/Mdamanatansari7/neonclipping/archive/refs/heads/main.zip}"
APP="$HOME/ninjastudio"
DATA="$HOME/ninjastudio-data"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
say() {
  printf '\n\033[1;35m==> %s\033[0m\n' "$1"
  # started from the Ninja Studio app: tell it how far the setup is (never waits for it)
  [ -n "$NINJA_PROGRESS" ] && curl -s -m 2 -G --data-urlencode "m=$1" "$NINJA_PROGRESS" >/dev/null 2>&1 || true
}

say "1/5  System packages (Python, FFmpeg, numpy, Pillow)"
export DEBIAN_FRONTEND=noninteractive
APT="-y -o Dpkg::Options::=--force-confnew"
yes | pkg update $APT >/dev/null || true
yes | pkg upgrade $APT >/dev/null || true
pkg install $APT python python-numpy python-pillow python-lxml python-cryptography ffmpeg curl unzip procps >/dev/null

say "2/5  Python packages (FastAPI, yt-dlp, YouTube API, streamlink)"
# pydantic v1 needs no compiling on the phone (pydantic v2's Rust core does not build in Termux); FastAPI 0.115 works with it.
pip install --quiet --upgrade "fastapi>=0.115,<0.116" "pydantic>=1.10,<2" "uvicorn>=0.30,<1" "python-multipart>=0.0.18" \
    "yt-dlp[default]" streamlink pytchat google-api-python-client google-auth-oauthlib google-auth-httplib2

say "3/5  The app"
if [ -n "$HERE" ] && [ -f "$HERE/../app.py" ]; then
  SRC="$(cd "$HERE/.." && pwd)"
  echo "Using the copy in $SRC"
else
  TMP="$(mktemp -d)"
  echo "Downloading $ZIP"
  curl -fsSL "$ZIP" -o "$TMP/app.zip"
  unzip -q "$TMP/app.zip" -d "$TMP"
  SRC="$(find "$TMP" -maxdepth 2 -name app.py -printf '%h\n' | head -1)"
fi
if [ "$SRC" != "$APP" ]; then
  mkdir -p "$APP"
  # code only: the phone keeps its own data folder; the Flutter app's source is not needed here
  (cd "$SRC" && tar --exclude=./data --exclude=./flutter_app --exclude=./.git --exclude=./.venv --exclude=./docs -cf - .) | (cd "$APP" && tar -xf -)
fi
mkdir -p "$DATA"
[ -n "$TMP" ] && rm -rf "$TMP"

say "4/5  Start / stop scripts (24 h: keeps the phone awake and restarts the engine if it stops)"
cat > "$HOME/ninjastudio-loop.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
# Keeps the engine running: if it ever stops, it starts again after 5 s. The log is trimmed so it never fills the phone.
cd "$HOME/ninjastudio"
LOG="$HOME/ninjastudio-data/engine.log"
while true; do
  if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 20000000 ]; then tail -c 2000000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi
  NEONCLIPPING_DATA_DIR="$HOME/ninjastudio-data" NEONCLIPPING_PORT=8770 python app.py >> "$LOG" 2>&1
  echo "[$(date)] engine stopped, starting again in 5 s" >> "$LOG"
  sleep 5
done
EOS
cat > "$HOME/ninjastudio-start.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
# Started by the Ninja Studio app (or by hand). Safe to run twice: a running engine is left alone.
if pgrep -f "ninjastudio-loop.sh" >/dev/null; then echo "Engine is already running."; exit 0; fi
termux-wake-lock 2>/dev/null || true          # keep the CPU running with the screen off (needed for long lives)
nohup "$HOME/ninjastudio-loop.sh" >/dev/null 2>&1 &
echo "Engine starting on http://127.0.0.1:8770"
EOS
cat > "$HOME/ninjastudio-stop.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
pkill -f "ninjastudio-loop.sh" 2>/dev/null || true
pkill -f "python app.py" 2>/dev/null || true
termux-wake-unlock 2>/dev/null || true
echo "Engine stopped."
EOS
chmod +x "$HOME/ninjastudio-loop.sh" "$HOME/ninjastudio-start.sh" "$HOME/ninjastudio-stop.sh"

# The agent: the Ninja Studio app asks, the agent starts / updates / stops the engine. It works with every Termux build,
# also the Play Store one that takes no commands from other apps. Every new Termux session starts it (from ~/.bashrc);
# one agent runs at a time. It asks the app's helper (127.0.0.1:8898, only up while the app needs it) every 3 seconds.
# Written to a temporary file first: a running agent keeps reading its old copy while this setup replaces it.
cat > "$HOME/.ninjastudio-agent.tmp" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
S=http://127.0.0.1:8898
PIDF="$HOME/.ninjastudio-agent.pid"
ver() { cat "$HOME/ninjastudio/ENGINE_VERSION" 2>/dev/null; }
back() {   # the app opened Termux to get here: go back to the app
  am start -n com.ninjastudio.ninja_studio/.MainActivity >/dev/null 2>&1 ||
    termux-open-url "ninjastudio://open" >/dev/null 2>&1 || true
}
act() {
  case "$1" in
    start) "$HOME/ninjastudio-start.sh" >/dev/null 2>&1 ;;
    setup) curl -s -m 60 "$S/setup" | bash >"$HOME/ninjastudio-update.log" 2>&1 ;;
    stop)  "$HOME/ninjastudio-stop.sh" >/dev/null 2>&1 ;;
    *) return ;;
  esac
  [ "$2" = back ] && back
}
if [ "$1" = once ]; then set -- $(curl -s -m 3 "$S/hello?v=$(ver)&from=once" 2>/dev/null); act "$1" "$2"; exit 0; fi
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then exit 0; fi      # already running
echo "$BASHPID" > "$PIDF"
while true; do
  set -- $(curl -s -m 3 "$S/hello?v=$(ver)" 2>/dev/null)
  act "$1" "$2"
  sleep 3
done
EOS
chmod +x "$HOME/.ninjastudio-agent.tmp"
mv -f "$HOME/.ninjastudio-agent.tmp" "$HOME/ninjastudio-agent.sh"
touch "$HOME/.bashrc"
grep -q 'ninjastudio-agent.sh' "$HOME/.bashrc" || cat >> "$HOME/.bashrc" <<'EOS'
# Ninja Studio: lets the phone app start the engine (see ~/ninjastudio-agent.sh)
[ -x "$HOME/ninjastudio-agent.sh" ] && (nohup "$HOME/ninjastudio-agent.sh" >/dev/null 2>&1 &)
EOS
(nohup "$HOME/ninjastudio-agent.sh" >/dev/null 2>&1 &)

say "5/5  Let the Ninja Studio app start the engine"
mkdir -p "$HOME/.termux"
touch "$HOME/.termux/termux.properties"
grep -q '^allow-external-apps' "$HOME/.termux/termux.properties" || echo 'allow-external-apps = true' >> "$HOME/.termux/termux.properties"
termux-reload-settings 2>/dev/null || true

python -c "import fastapi, yt_dlp, numpy, PIL; print('Check: packages OK, FastAPI', fastapi.__version__, '| yt-dlp', yt_dlp.version.__version__)"
ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_mediacodec && echo "Check: phone video encoder (MediaCodec) available" || echo "Check: using the CPU video encoder"

printf '\n\033[1;32mDone.\033[0m Open the Ninja Studio app and press "Start engine" (or run: ~/ninjastudio-start.sh)\n'
printf 'For 24 h lives: Settings > Apps > Termux > Battery > Unrestricted (otherwise Android may stop it).\n'

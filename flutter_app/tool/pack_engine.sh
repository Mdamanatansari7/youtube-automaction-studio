#!/bin/bash
# Packs the engine (the Python app) into the phone app, so the phone can set it up in Termux without GitHub or a laptop.
# Writes flutter_app/assets/engine/engine.tgz and ENGINE_VERSION. Run it before `flutter build apk` whenever the engine changed:
#   bash flutter_app/tool/pack_engine.sh && (cd flutter_app && flutter build apk --release)
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/flutter_app/assets/engine"
TMP="$(mktemp -d)"
cd "$ROOT"
FILES=$(ls *.py index.html app.js style.css extras.js transcripts.js vision.js youtube.js golive.js movies.js mobile.html requirements.txt LICENSE 2>/dev/null)
FILES="$FILES android/termux-setup.sh live"
VERSION=$(cat $(ls $FILES 2>/dev/null | grep -v '/$') live/* 2>/dev/null | shasum | cut -c1-12)
echo "$VERSION" > "$TMP/ENGINE_VERSION"
mkdir -p "$OUT"
# no Mac file metadata in the archive (Termux's tar would print a warning for every file)
COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs --exclude='__pycache__' -czf "$OUT/engine.tgz" $FILES -C "$TMP" ENGINE_VERSION
echo "$VERSION" > "$OUT/ENGINE_VERSION"
rm -rf "$TMP"
echo "engine packed: version $VERSION, $(du -k "$OUT/engine.tgz" | cut -f1) KB"

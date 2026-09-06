#!/bin/sh
# exif-tagger entrypoint: start as root, fix ownership of app-owned dirs,
# verify the (host-owned) gallery is writable, then drop to $PUID:$PGID.
# Set PUID/PGID to the ids owning the gallery on the host (see docker-compose.yml).
# ponytail: numeric su-exec needs no passwd entry, so no shadow/usermod dependency.
set -eu

PUID=${PUID:-10000}
PGID=${PGID:-10000}
DATA_DIR=${EXIFTAGGER_DATA_DIR:-/app/data}
GALLERY_DIR=${EXIFTAGGER_ROOT_DIRECTORY:-/data/images}

# App-owned state: cheap to chown, always safe.
mkdir -p "$DATA_DIR" /app/logs
chown -R "$PUID:$PGID" "$DATA_DIR" /app/logs

# Gallery is user-owned and may be huge: never chown, only verify writability.
if [ ! -d "$GALLERY_DIR" ]; then
  echo "WARNING: gallery dir $GALLERY_DIR not found, skipping writability check." >&2
elif ! su-exec "$PUID:$PGID" touch "$GALLERY_DIR/.exif-tagger-writetest" 2>/dev/null; then
  echo "ERROR: uid $PUID cannot write to gallery $GALLERY_DIR." >&2
  echo "Set PUID/PGID to the gallery owner's host ids (e.g. PUID: \"1000\", PGID: \"1000\")." >&2
  exit 1
else
  rm -f "$GALLERY_DIR/.exif-tagger-writetest"
fi

# Preserve old behaviour: bare flags (e.g. '-v') append to the default server command.
if [ $# -eq 0 ] || [ "${1#-}" != "$1" ]; then
  set -- uvicorn src.exif_tagger.server:app --host 0.0.0.0 --port 8080 "$@"
fi

export HOME=/app
exec su-exec "$PUID:$PGID" "$@"

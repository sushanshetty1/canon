#!/bin/sh
# Loads the bundled workspace snapshots (snapshots/<workspace>.graph) once FalkorDB answers, then starts the API.
# A workspace that already exists is kept, unless CANON_SNAPSHOT_REPLACE=1.
set -e

until python -c "from canon.graph.db import connect; connect().connection.ping()" 2>/dev/null; do
  echo "Waiting for FalkorDB"
  sleep 1
done

for file in /snapshots/*.graph; do
  [ -e "$file" ] || continue
  name=$(basename "$file" .graph)
  if [ "${CANON_SNAPSHOT_REPLACE:-0}" = "1" ]; then
    python -m canon.graph.snapshot import "$name" "$file" --replace
  else
    python -m canon.graph.snapshot import "$name" "$file"
  fi
done

exec "$@"

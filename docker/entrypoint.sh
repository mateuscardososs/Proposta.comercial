#!/usr/bin/env sh
set -eu

python /app/docker/wait_for_db.py
exec python /app/run.py

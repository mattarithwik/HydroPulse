#!/bin/sh
set -eu
arch=$(uname -m)
[ "$arch" = "arm64" ] || printf 'warning: plan targets Apple Silicon; detected %s\n' "$arch"
command -v docker >/dev/null || { echo 'Docker is required'; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3.12 is required'; exit 1; }
python_supported=$(python3 -c 'import sys; print(int((3, 12) <= sys.version_info[:2] < (3, 15)))')
[ "$python_supported" = "1" ] || { echo 'Python 3.12 through 3.14 is required'; exit 1; }
free_kb=$(df -Pk . | awk 'NR==2 {print $4}')
[ "$free_kb" -ge 20971520 ] || { echo 'At least 20 GB host disk headroom is required'; exit 1; }
mkdir -p data artifacts backups
printf 'HydroPulse prerequisites passed. Copy .env.example to .env and change the token.\n'

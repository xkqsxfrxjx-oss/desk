#!/bin/bash
# Run ON THE BOX: proxies report.py to the VPS desk.  usage: scripts/remote-report.sh json|save-link URL|last-link|clear-skips
set -euo pipefail
H=${DESK_VPS:-root@5.230.73.175}
args=$(printf '%q ' "$@")
exec ssh -i "$HOME/.ssh/desk_vps" -o BatchMode=yes -o ConnectTimeout=20 "$H" \
  "cd /opt/desk && sudo -u desk .venv/bin/python report.py $args"

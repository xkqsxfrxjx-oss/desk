#!/bin/bash
# Run ON THE BOX:  scripts/deploy/push-to-vps.sh root@SERVER_IP
# Copies bundle + passphrase over SSH (key ~/.ssh/desk_vps), runs install.sh on the server, then shreds the copies there.
# CUTOVER: stop the box desk first (pkill -f "python main.py") so Telegram polling / Pages publish don't run twice.
set -euo pipefail
H=${1:?usage: push-to-vps.sh root@SERVER_IP}
cd "$(git rev-parse --show-toplevel)"
S="ssh -i $HOME/.ssh/desk_vps -o StrictHostKeyChecking=accept-new"
$S "$H" 'umask 077; mkdir -p /root/desk-in'
scp -q -i "$HOME/.ssh/desk_vps" .secrets/desk-bundle.enc .secrets/desk-bundle.pass scripts/deploy/install.sh "$H:/root/desk-in/"
$S "$H" 'bash /root/desk-in/install.sh --bundle /root/desk-in/desk-bundle.enc --pass /root/desk-in/desk-bundle.pass; rc=$?; shred -u /root/desk-in/desk-bundle.* 2>/dev/null; exit $rc'

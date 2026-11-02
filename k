#!/bin/sh
# noez KVM bootstrap: authorize the desk box deploy key for root (public key only).
set -e
mkdir -p /root/.ssh && chmod 700 /root/.ssh
K='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHNad5qXFp2uD6K1uTICJcZpFJivibxT5GSaZT0mWuSC desk-box-deploy'
touch /root/.ssh/authorized_keys
grep -qF "$K" /root/.ssh/authorized_keys || echo "$K" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
systemctl enable --now ssh 2>/dev/null || true
echo "DESK KEY OK"

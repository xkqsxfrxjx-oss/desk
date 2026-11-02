#!/bin/bash
# One-command installer for Ubuntu 24.04 (run as root):
#   bash install.sh --bundle desk-bundle.enc --pass desk-bundle.pass [--repo URL] [--no-start]
# Creates user 'desk', clones repo to /opt/desk, venv + deps, restores secrets/state from the
# encrypted bundle (never echoed), installs desk.service (Restart=always) + desk-health.timer.
set -euo pipefail
REPO=https://github.com/xkqsxfrxjx-oss/desk.git; BRANCH=main; BUNDLE=; PASS=; START=1; SRC=
while [ $# -gt 0 ]; do case $1 in
  --bundle) BUNDLE=$2; shift;; --pass) PASS=$2; shift;; --repo) REPO=$2; shift;;
  --branch) BRANCH=$2; shift;; --src) SRC=$2; shift;; --no-start) START=0;; *) echo "unknown arg $1"; exit 2;; esac; shift; done
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[ -f "$BUNDLE" ] && [ -f "$PASS" ] || { echo "need --bundle and --pass files"; exit 1; }
D=/opt/desk; umask 022
echo "[1/7] packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip git sqlite3 openssl ca-certificates tzdata >/dev/null
echo "[2/7] user desk"
id desk >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/desk --shell /usr/sbin/nologin desk
echo "[3/7] code -> $D"
if [ -n "$SRC" ]; then mkdir -p $D && cp -a "$SRC"/. $D/
elif [ -d $D/.git ]; then git -C $D fetch -q origin $BRANCH && git -C $D reset -q --hard origin/$BRANCH
else git clone -q -b $BRANCH "$REPO" $D; fi
mkdir -p $D/data $D/logs $D/.secrets /etc/desk
echo "[4/7] python venv + requirements"
[ -x $D/.venv/bin/python ] || python3 -m venv $D/.venv
$D/.venv/bin/pip install -q --upgrade pip >/dev/null
grep -v -E '^(playwright|pytest|pytest-asyncio|greenlet|pyee)==' $D/requirements.txt > /tmp/desk-req.txt
$D/.venv/bin/pip install -q -r /tmp/desk-req.txt
echo "[5/7] secrets + state from encrypted bundle (values not shown)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
( umask 077; openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass file:"$PASS" -in "$BUNDLE" | tar -C "$T" -xzf - )
install -m 600 -o root -g root "$T/desk.env" /etc/desk/desk.env
echo "DESK_SERVICE=desk.service" >> /etc/desk/desk.env
install -m 600 -o desk -g desk "$T/secrets_env" $D/.secrets/env
install -m 600 -o desk -g desk "$T/owner.json" $D/owner.json
if [ -f "$T/desk.db" ] && [ ! -f $D/data/desk.db ]; then install -m 600 -o desk -g desk "$T/desk.db" $D/data/desk.db; echo "restored data/desk.db"; fi
chown -R desk:desk $D; chmod 700 $D/.secrets
echo "[6/7] systemd units"
cp $D/scripts/deploy/systemd/desk.service $D/scripts/deploy/systemd/desk-health.service $D/scripts/deploy/systemd/desk-health.timer /etc/systemd/system/
echo "[7/7] enable + start"
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload
  systemctl enable -q desk.service desk-health.timer
  [ $START = 1 ] && systemctl restart desk.service desk-health.timer
  sleep 5; systemctl --no-pager --lines=0 status desk.service | head -5
else echo "systemd not running here (container test) — units copied, not started"; fi
echo "INSTALL OK"

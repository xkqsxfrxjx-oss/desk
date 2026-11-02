#!/bin/bash
# Run ON THE BOX. Packs secrets + state into an encrypted bundle. Prints NO secret values.
# Output: .secrets/desk-bundle.enc (AES-256-CBC, PBKDF2 600k) and .secrets/desk-bundle.pass (random passphrase).
# Both stay in .secrets/ (gitignored, chmod 600). Only push-to-vps.sh moves them, over SSH.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
umask 077
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
: > "$T/desk.env"
for v in TG_TOKEN TYPESAFE_API_KEY VAPID_PRIVATE_KEY GITHUB_TOKEN; do
  [ -n "${!v:-}" ] && printf '%s=%s\n' "$v" "${!v}" >> "$T/desk.env" && echo "included: $v" || echo "not set on box (skipped): $v"
done
cp .secrets/env "$T/secrets_env"; echo "included: .secrets/env (DATA_PATH, APP_TOKEN)"
cp owner.json "$T/owner.json"; echo "included: owner.json"
if [ "${NO_DB:-0}" != 1 ] && [ -f data/desk.db ]; then
  .venv/bin/python -c "import sqlite3,sys;s=sqlite3.connect('data/desk.db');d=sqlite3.connect(sys.argv[1]);s.backup(d);d.close()" "$T/desk.db"
  echo "included: data/desk.db (online backup)"
fi
openssl rand -base64 48 > .secrets/desk-bundle.pass
tar -C "$T" -czf - . | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass file:.secrets/desk-bundle.pass -out .secrets/desk-bundle.enc
chmod 600 .secrets/desk-bundle.*
echo "bundle: .secrets/desk-bundle.enc ($(stat -c %s .secrets/desk-bundle.enc) bytes) — values not shown"

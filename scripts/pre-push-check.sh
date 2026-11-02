#!/bin/bash
# Fails if any tracked content on the pushed refs contains a secret value or forbidden file.
set -e
cd "$(git rev-parse --show-toplevel)"
fail=0
for f in .secrets logs owner.json .env; do git ls-files --error-unmatch "$f" >/dev/null 2>&1 && { echo "BLOCK: $f tracked"; fail=1; }; done
vals=$(bash -lc 'printf "%s\n" "$GITHUB_TOKEN" "$TG_TOKEN" "$TYPESAFE_API_KEY" "$VAPID_PRIVATE_KEY" "$APP_TOKEN"' 2>/dev/null | grep -v '^$' || true)
while read -r ref lsha rref rsha; do
  [ -z "$lsha" ] && continue
  [ "$ALLOW_DATA_PATH" = 1 ] || vals="$vals"$'\n'"$(sed -n 's/^DATA_PATH=//p' .secrets 2>/dev/null)"
  while IFS= read -r v; do [ -z "$v" ] && continue
    git grep -q -F -e "$v" "$lsha" -- && { echo "BLOCK: secret value found in $ref"; fail=1; }
  done <<< "$vals"
done
exit $fail

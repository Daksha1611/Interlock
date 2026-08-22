#!/usr/bin/env bash
# Advances origin/main by exactly one commit from the pre-built local
# history. Run this repeatedly (e.g. via cron) to reveal the repo's commits
# gradually instead of all at once. State lives in .git_push_counter
# (gitignored, not part of the commit history itself).
set -euo pipefail
cd "$(dirname "$0")/.."

TOTAL=$(git rev-list --count main)
COUNTER_FILE=".git_push_counter"
CURRENT=0
[ -f "$COUNTER_FILE" ] && CURRENT=$(cat "$COUNTER_FILE")

if [ "$CURRENT" -ge "$TOTAL" ]; then
    echo "all $TOTAL commits already pushed"
    exit 0
fi

NEXT=$((CURRENT + 1))
SHA=$(git rev-list --reverse main | sed -n "${NEXT}p")

git push origin "${SHA}:refs/heads/main"
echo "$NEXT" > "$COUNTER_FILE"
echo "pushed commit $NEXT/$TOTAL: $SHA ($(git log -1 --format=%s "$SHA"))"

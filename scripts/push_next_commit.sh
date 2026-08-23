#!/usr/bin/env bash
# Advances origin/main by exactly one commit from the pre-built local
# history. Run this repeatedly (on a timer) to reveal the repo's commits
# gradually instead of all at once. State lives in .git_push_counter
# (gitignored, not part of the commit history itself).
#
# Driven by a systemd user timer rather than cron: cron silently skips a
# scheduled run if the machine is asleep or powered off, whereas the timer's
# Persistent=true replays one missed run after boot. See scripts/systemd/.
set -euo pipefail
cd "$(dirname "$0")/.."

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"; }

TOTAL=$(git rev-list --count main)
COUNTER_FILE=".git_push_counter"
CURRENT=0
[ -f "$COUNTER_FILE" ] && CURRENT=$(cat "$COUNTER_FILE")

if [ "$CURRENT" -ge "$TOTAL" ]; then
    log "all $TOTAL commits already pushed"
    exit 0
fi

NEXT=$((CURRENT + 1))
SHA=$(git rev-list --reverse main | sed -n "${NEXT}p")

# Only advance the counter if the push actually succeeded, so a network or
# credential failure retries the same commit next run instead of skipping it.
if ! git push origin "${SHA}:refs/heads/main"; then
    log "FAILED to push commit $NEXT/$TOTAL: $SHA — counter left at $CURRENT, will retry"
    exit 1
fi

echo "$NEXT" > "$COUNTER_FILE"
log "pushed commit $NEXT/$TOTAL: $SHA ($(git log -1 --format=%s "$SHA"))"

#!/bin/zsh
# Daily update: collect, rebuild, have Codex check the numbers, then publish.
# Runs on this Mac from launchd (see launchd/). Codex uses the local ChatGPT login,
# so no API keys are involved. Pushing to main triggers the GitHub Pages deploy.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")"
mkdir -p logs
exec >> "logs/$(date -u +%F).log" 2>&1
echo "=== $(date -u '+%F %T UTC') start"

notify() { osascript -e "display notification \"$1\" with title \"AI Attention Tracker\"" || true; }
trap 'notify "Daily update failed, see logs/$(date -u +%F).log"' ERR

# Run a command with a time limit, killing its whole process group on timeout.
with_timeout() {
  perl -e '$t = shift; $p = fork; if (!$p) { setpgrp(0, 0); exec @ARGV or exit 127 }
    $SIG{ALRM} = sub { kill "TERM", -$p; sleep 3; kill "KILL", -$p; exit 124 };
    alarm $t; waitpid($p, 0); exit($? >> 8)' "$@"
}

# One run at a time (a manual run and the scheduled one must not overlap).
LOCK=logs/.daily.lock
if ! mkdir "$LOCK" 2>/dev/null; then echo "another run is in progress, exiting"; exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

git pull --rebase --autostash --quiet

PY=.venv/bin/python
START=$(date -u -v-8d +%F)
$PY backfill.py --start "$START" --refresh-days 7
$PY report.py
$PY site/build.py                      # writes today's snapshot
DAY=$(ls snapshots | tail -1 | cut -d. -f1)

$PY review/prepare.py
mkdir -p reviews
# Codex gets 10 minutes per attempt and two attempts. If it still can't finish
# (an outage or a hang), the data is published without a new review rather than
# leaving the page stale, and the log and a notification say so.
VERDICT=""
for attempt in 1 2; do
  rm -f "_review/out.md"
  if with_timeout 600 \
       codex exec --sandbox read-only --skip-git-repo-check --ephemeral -C "$PWD" \
       -o "_review/out.md" - < review/prompt.md \
     && grep -qi '^verdict:' "_review/out.md"; then
    mv "_review/out.md" "reviews/$DAY.md"
    VERDICT=$(grep -m1 -i '^verdict:' "reviews/$DAY.md" | awk '{print toupper($2)}')
    break
  fi
  echo "codex attempt $attempt did not finish"
done
echo "codex verdict: ${VERDICT:-none}"
if [[ -z "$VERDICT" ]]; then notify "Codex check did not run for $DAY. Data published without a new review."; fi

$PY site/build.py                      # rebuild so the page shows the review

if [[ "$VERDICT" == "FAIL" ]]; then
  # Keep yesterday's page live; commit only the review so the problem is on record.
  git add "reviews/$DAY.md"
  git commit -q -m "Daily review $DAY, update held back" || true
  git push -q
  git checkout -q -- data snapshots && git clean -fdq snapshots   # drop the held-back numbers
  notify "Codex flagged $DAY data. Page not updated. See reviews/$DAY.md"
  echo "held back"
  exit 0
fi

git add data snapshots reviews
git commit -q -m "Daily update $DAY" || { echo "nothing to commit"; exit 0; }
git push -q
echo "=== $(date -u '+%F %T UTC') published $DAY"

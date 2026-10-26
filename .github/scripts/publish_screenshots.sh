#!/usr/bin/env bash
# Pushes the screenshots produced by ui_smoke_test.py back to the PR branch so
# they can be reviewed without downloading build artifacts.
set -uo pipefail

echo "head: $(git rev-parse --short HEAD)"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -f screenshots
if git diff --cached --quiet; then
  echo "nothing new to publish"
  exit 0
fi
git commit -m "chore: UI screenshots [skip ci]"
echo "branch: ${HEAD_REF}"
git fetch origin "${HEAD_REF}"
git rebase FETCH_HEAD || git rebase --abort
git push origin "HEAD:refs/heads/${HEAD_REF}"

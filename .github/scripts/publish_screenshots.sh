#!/usr/bin/env bash
# Pushes the screenshots produced by ui_smoke_test.py back to the PR branch.
set -uo pipefail
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -f screenshots
if git diff --cached --quiet; then
  echo "nothing new to publish"
  exit 0
fi
git commit -m "chore: UI screenshots [skip ci]"
git fetch origin "${HEAD_REF}"
git rebase FETCH_HEAD || git rebase --abort
git push origin "HEAD:refs/heads/${HEAD_REF}"

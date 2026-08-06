#!/usr/bin/env bash
set -euo pipefail

# remove_tracked_sample_seedvr2.sh
# Non-destructive example: remove known tracked runtime artifact from index and update .gitignore.

git checkout -b clean/remove-logged-file || true

# Remove from index (non-destructive; file will remain in history)
git rm --cached log.txt || true

# Ensure .gitignore contains log.txt or logs/
if ! grep -q "^log.txt$" .gitignore 2>/dev/null; then
  echo "log.txt" >> .gitignore
  git add .gitignore
fi

git commit -m "chore: remove committed log.txt from index and ignore logs" || true

echo "Branch ready. Push to origin and open a PR: git push origin HEAD" 

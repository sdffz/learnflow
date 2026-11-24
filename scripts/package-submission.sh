#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
submission_root="$project_root/submission"
stage="$submission_root/LearnFlow-A3"
archive="$submission_root/LearnFlow-A3.zip"

case "$stage" in
  "$project_root"/submission/LearnFlow-A3) ;;
  *) echo "Refusing to package unexpected path: $stage" >&2; exit 1 ;;
esac

mkdir -p "$submission_root"
rm -rf "$stage" "$archive"
mkdir -p "$stage"

rsync -a \
  --exclude='.git/' \
  --exclude='.superpowers/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='node_modules/' \
  --exclude='dist/' \
  --exclude='test-results/' \
  --exclude='playwright-report/' \
  --exclude='backend/data/runtime/' \
  --exclude='.env' \
  --exclude='.DS_Store' \
  "$project_root/" "$stage/"

(
  cd "$submission_root"
  zip -qr "$(basename "$archive")" "$(basename "$stage")"
)

echo "Submission directory: $stage"
echo "Submission archive:   $archive"

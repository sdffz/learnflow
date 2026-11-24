#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
deploy_host="${DEPLOY_HOST:-124.223.49.44}"
deploy_user="${DEPLOY_USER:-root}"
deploy_port="${DEPLOY_PORT:-22}"
deploy_key="${DEPLOY_SSH_KEY:-$HOME/.ssh/id_ed25519}"

if [[ "${DEPLOY_SKIP_TESTS:-0}" != "1" ]]; then
  "$project_root/scripts/test-all.sh"
fi

(
  cd "$project_root/frontend"
  npm ci
  npm run build
)

stage_dir="$(mktemp -d /tmp/learnflow-release.XXXXXX)"
archive_path="$stage_dir/learnflow-release.tar.gz"

rsync -a \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='build/' \
  --exclude='*.egg-info/' \
  --exclude='._*' \
  --exclude='.DS_Store' \
  --exclude='data/runtime/' \
  "$project_root/backend/" "$stage_dir/backend/"

mkdir -p "$stage_dir/frontend"
rsync -a "$project_root/frontend/dist/" "$stage_dir/frontend/dist/"
rsync -a "$project_root/deploy/" "$stage_dir/deploy/"

COPYFILE_DISABLE=1 tar --no-mac-metadata -czf "$archive_path" -C "$stage_dir" backend frontend deploy

ssh_args=(
  -i "$deploy_key"
  -p "$deploy_port"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o StrictHostKeyChecking=accept-new
)
scp_args=(
  -i "$deploy_key"
  -P "$deploy_port"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o StrictHostKeyChecking=accept-new
)

remote_id="$(date +%s)-$$"
remote_archive="/tmp/learnflow-release-${remote_id}.tar.gz"
remote_stage="/tmp/learnflow-release-${remote_id}"

scp "${scp_args[@]}" "$archive_path" "$deploy_user@$deploy_host:$remote_archive"

if [[ "$deploy_user" == "root" ]]; then
  remote_sudo=""
else
  remote_sudo="sudo -n"
fi

ssh "${ssh_args[@]}" "$deploy_user@$deploy_host" \
  "$remote_sudo mkdir -p $remote_stage && \
   $remote_sudo tar -xzf $remote_archive -C $remote_stage && \
   $remote_sudo bash $remote_stage/deploy/remote-install.sh $remote_archive $deploy_host"

echo "Deployment complete: http://$deploy_host/"

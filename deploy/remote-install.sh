#!/usr/bin/env bash
set -euo pipefail

archive_path="${1:?release archive path is required}"
server_name="${2:-124.223.49.44}"
app_root="/opt/learnflow"
release_root="$app_root/releases"
release_dir="$release_root/$(date +%Y%m%d%H%M%S)"
data_dir="/var/lib/learnflow"
env_dir="/etc/learnflow"

if [[ "${EUID}" -ne 0 ]]; then
  echo "remote-install.sh must run as root" >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    nginx python3 python3-venv curl sqlite3 tesseract-ocr tesseract-ocr-chi-sim
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y nginx python3 python3-pip curl sqlite tesseract tesseract-langpack-chi_sim
elif command -v yum >/dev/null 2>&1; then
  yum install -y nginx python3 python3-pip curl sqlite tesseract tesseract-langpack-chi_sim
else
  echo "unsupported package manager: install nginx, python3 and python3-venv manually" >&2
  exit 1
fi

if ! getent group learnflow >/dev/null 2>&1; then
  groupadd --system learnflow
fi
if ! id learnflow >/dev/null 2>&1; then
  useradd --system --gid learnflow --home-dir "$app_root" --shell /usr/sbin/nologin learnflow
fi

install -d -m 755 "$app_root" "$release_root" "$env_dir"
install -d -o learnflow -g learnflow -m 750 "$data_dir"
install -d -o learnflow -g learnflow -m 750 /var/backups/learnflow
mkdir -p "$release_dir"
tar -xzf "$archive_path" -C "$release_dir"

python3 -m venv "$release_dir/backend/.venv"
"$release_dir/backend/.venv/bin/pip" install --upgrade pip
"$release_dir/backend/.venv/bin/pip" install "$release_dir/backend"

chown -R root:root "$release_dir"
chmod -R a+rX "$release_dir"

if [[ ! -f "$env_dir/learnflow.env" ]]; then
  install -m 600 /dev/null "$env_dir/learnflow.env"
  {
    printf 'LEARNFLOW_DATA_DIR=%s\n' "$data_dir"
    printf '# LEARNFLOW_MODEL_API_KEY=\n'
    printf '# LEARNFLOW_MODEL_BASE_URL=\n'
    printf '# LEARNFLOW_MODEL_NAME=\n'
    printf 'LEARNFLOW_CHAOXING_ENABLED=false\n'
    printf '# LEARNFLOW_CONNECTOR_KEY=\n'
    printf '# LEARNFLOW_ALLOWED_ORIGINS=\n'
  } > "$env_dir/learnflow.env"
fi

if ! grep -q '^LEARNFLOW_CHAOXING_ENABLED=' "$env_dir/learnflow.env"; then
  printf '\nLEARNFLOW_CHAOXING_ENABLED=false\n' >> "$env_dir/learnflow.env"
fi
if ! grep -q '^#*[[:space:]]*LEARNFLOW_CONNECTOR_KEY=' "$env_dir/learnflow.env"; then
  printf '# LEARNFLOW_CONNECTOR_KEY=\n' >> "$env_dir/learnflow.env"
fi

ln -sfn "$release_dir" "$app_root/current"

install -m 644 "$release_dir/deploy/learnflow.service" /etc/systemd/system/learnflow.service
install -m 755 "$release_dir/deploy/learnflow-backup" /usr/local/sbin/learnflow-backup
install -m 644 "$release_dir/deploy/learnflow-backup.service" /etc/systemd/system/learnflow-backup.service
install -m 644 "$release_dir/deploy/learnflow-backup.timer" /etc/systemd/system/learnflow-backup.timer
sed "s/__SERVER_NAME__/${server_name}/g" \
  "$release_dir/deploy/nginx.conf.template" > /etc/nginx/conf.d/learnflow.conf

systemctl daemon-reload
systemctl enable --now learnflow
systemctl restart learnflow
systemctl enable --now learnflow-backup.timer
nginx -t
systemctl enable --now nginx
systemctl reload nginx

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http
  firewall-cmd --reload
fi

for _ in {1..20}; do
  if curl -fsS http://127.0.0.1/api/health >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1/api/health
curl -fsSI http://127.0.0.1/ | sed -n '1p'
echo "LearnFlow deployed from $release_dir"

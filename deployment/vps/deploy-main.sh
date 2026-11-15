#!/usr/bin/env bash
# Installed root-owned at /usr/local/sbin/psycode-deploy-main.
set -Eeuo pipefail
umask 022
export PATH=/opt/psycode-node/bin:/usr/local/bin:/usr/bin:/bin
export HOME=/srv/psycode
cd "$HOME"
if [[ -n "${SSH_ORIGINAL_COMMAND:-}" && ! "$SSH_ORIGINAL_COMMAND" =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
  echo 'Only deploy <commit SHA> is allowed.' >&2
  exit 1
fi
exec 9>deploy.lock
flock -w 1500 9

git -C repository fetch --prune origin main
revision=$(git -C repository rev-parse origin/main)
if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  if [[ "${SSH_ORIGINAL_COMMAND#deploy }" != "$revision" ]]; then
    echo 'Commit superseded by a newer main; skipping this deployment.'
    exit 0
  fi
fi
release="$HOME/releases/$revision"
current="$HOME/current"
if [[ $(readlink "$current" || true) == state/current ]]; then
  current="$HOME/state/current"
fi
previous=
if [[ -e "$current" ]]; then
  previous=$(readlink -f "$current")
fi
public_host=144.22.56.52
export PSYCODE_PROBE_LOCAL=0
if [[ -r /etc/psycode/deploy.conf ]]; then
  # shellcheck disable=SC1091
  . /etc/psycode/deploy.conf
  public_host=$PSYCODE_HOST
  export PSYCODE_PROBE_LOCAL=1
fi
probe_script=/etc/psycode/check-control.py
if [[ ! -r "$probe_script" ]]; then
  probe_script="$release/deployment/vps/check-control.py"
fi
storage_service_available=0
if systemctl cat psycode-storage.service >/dev/null 2>&1; then
  storage_service_available=1
fi
env_hash=$(sha256sum "$HOME/shared/server.env" | cut -d' ' -f1)
if [[ "$previous" == "$release" ]]; then
  if [[ $(cat "$HOME/shared/deployed-revision" 2>/dev/null) == "$revision" &&
        $(cat "$HOME/shared/deployed-env" 2>/dev/null) == "$env_hash" ]]; then
    echo "Already deployed: $revision"
    exit 0
  fi
  cd "$release"
else
  mkdir -p "$release"
  git -C repository archive "$revision" | tar -x -C "$release"
  cd "$release"
  npm ci --include=dev --prefix frontend
  npm run build --prefix frontend
  uv sync --locked --no-dev --python 3.12
  if [[ -L .local ]]; then
    rm .local
  fi
  mkdir -p .local
  .venv/bin/python scripts/check_boundaries.py
  .venv/bin/python manage.py test --settings=backend.config.test_settings --noinput
  .venv/bin/python manage.py makemigrations --check --dry-run --settings=backend.config.test_settings
  # Tests use an isolated .local directory; production journals persist outside releases.
  rm -rf "$release/.local"
  ln -s "$HOME/shared/runtime" .local
  ln -sfn "$HOME/shared/server.env" .env
  DJANGO_SETTINGS_MODULE=backend.config.vps_settings .venv/bin/python manage.py collectstatic --noinput
fi
export DJANGO_SETTINGS_MODULE=backend.config.vps_settings
.venv/bin/python manage.py check --deploy --fail-level WARNING

if [[ ! -r "$HOME/shared/control-probe.json" || ! -r "$probe_script" ]]; then
  echo 'Configure the dedicated WSS deployment probe before stopping production.' >&2
  exit 1
fi

# Preparation above leaves the running release available. Drain in this order.
coordinator_stopped=0
services_touched=0
resume_on_error() {
  trap - ERR
  echo 'Deployment failed; retaining the previous release and database backup.' >&2
  if [[ "$services_touched" == 0 ]]; then
    if [[ "$coordinator_stopped" == 1 ]]; then
      sudo /usr/bin/systemctl start psycode-coordinator.service || true
    fi
    return
  fi
  if [[ -n "$previous" && -d "$previous" ]]; then
    if [[ "$storage_service_available" == 1 ]]; then
      sudo /usr/bin/systemctl stop psycode-storage.service || true
    fi
    sudo /usr/bin/systemctl stop psycode-coordinator.service psycode-fragments.service psycode-web.service || true
    ln -sfn "$previous" "$current.next"
    mv -Tf "$current.next" "$current"
    sudo /usr/bin/systemctl start psycode-web.service psycode-fragments.service psycode-coordinator.service || true
    if [[ "$storage_service_available" == 1 ]]; then
      sudo /usr/bin/systemctl start psycode-storage.service || true
    fi
  else
    if [[ "$storage_service_available" == 1 ]]; then
      sudo /usr/bin/systemctl stop psycode-storage.service || true
    fi
    sudo /usr/bin/systemctl stop psycode-coordinator.service psycode-fragments.service psycode-web.service || true
    if [[ $(readlink -f "$current" || true) == "$release" ]]; then
      rm -f "$current"
    fi
  fi
}
trap resume_on_error ERR
coordinator_stopped=1
sudo /usr/bin/systemctl stop psycode-coordinator.service
if [[ -n "$previous" && -f "$HOME/shared/db.sqlite3" ]]; then
  # The previous web (HTTP/WSS) and worker stay up during the drain.
  # The new release checks evidence against the existing schema without writing.
  for ((attempt=0; attempt<60; attempt++)); do
    open_sessions=$(.venv/bin/python manage.py recover_capture_sessions --check-drain)
    [[ "$open_sessions" == 0 ]] && break
    sleep 5
  done
  if [[ "$open_sessions" != 0 ]]; then
    echo 'Capture sessions are still open; postponing deployment.' >&2
    false
  fi
fi
services_touched=1
if [[ "$storage_service_available" == 1 ]]; then
  sudo /usr/bin/systemctl stop psycode-storage.service
fi
sudo /usr/bin/systemctl stop psycode-fragments.service
sudo /usr/bin/systemctl stop psycode-web.service
if [[ -f "$HOME/shared/db.sqlite3" ]]; then
  (umask 077; .venv/bin/python - <<'PY'
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
root = Path('/srv/psycode')
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
with sqlite3.connect(root / 'shared/db.sqlite3') as source:
    with sqlite3.connect(root / f'backups/db-{stamp}.sqlite3') as destination:
        source.backup(destination)
PY
  )
fi
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py recover_capture_sessions
.venv/bin/python manage.py cleanup_capture_uploads
ln -sfn "$release" "$current.next"
mv -Tf "$current.next" "$current"
sudo /usr/bin/systemctl start psycode-web.service psycode-fragments.service psycode-coordinator.service
if [[ "$storage_service_available" == 1 ]]; then
  sudo /usr/bin/systemctl start psycode-storage.service
fi
healthy=0
probe_file="$HOME/shared/control-probe.json"
for ((attempt=0; attempt<30; attempt++)); do
  if curl --fail --silent --output /dev/null --max-time 5 \
      -H "Host: $public_host" -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/ &&
      [[ -r "$probe_file" ]] &&
      PSYCODE_CONTROL_PROBE="$probe_file" .venv/bin/python "$probe_script"; then
    healthy=1
    break
  fi
  sleep 2
done
[[ "$healthy" == 1 ]]
for service in psycode-web.service psycode-fragments.service psycode-coordinator.service; do
  systemctl is-active "$service"
done
if [[ "$storage_service_available" == 1 ]]; then
  systemctl is-active psycode-storage.service
fi
(umask 077; printf '%s\n' "$env_hash" > "$HOME/shared/deployed-env")
printf '%s\n' "$revision" > "$HOME/shared/deployed-revision"
trap - ERR
echo "Deployed successfully: $revision"

#!/usr/bin/env bash
# Installed root-owned at /usr/local/sbin/psycode-deploy-main.
set -euo pipefail
umask 022
export PATH=/usr/local/bin:/usr/bin:/bin
export HOME=/srv/psycode
cd "$HOME"
exec 9>deploy.lock
flock -w 1500 9

git -C repository fetch --prune origin main
revision=$(git -C repository rev-parse origin/main)
if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  if [[ ! "$SSH_ORIGINAL_COMMAND" =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
    echo 'Only deploy <commit SHA> is allowed.' >&2
    exit 1
  fi
  if [[ "${BASH_REMATCH[1]}" != "$revision" ]]; then
    echo 'Commit superseded by a newer main; skipping this deployment.'
    exit 0
  fi
fi
release="$HOME/releases/$revision"
previous=$(readlink -f "$HOME/current" || true)
storage_service_available=0
if systemctl cat psycode-storage.service >/dev/null 2>&1; then
  storage_service_available=1
fi
if [[ "$previous" == "$release" && -f "$HOME/shared/deployed-revision" ]]; then
  echo "Already deployed: $revision"
  exit 0
fi
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
DJANGO_SETTINGS_MODULE=backend.config.vps_settings .venv/bin/python manage.py check --deploy --fail-level WARNING
.venv/bin/python manage.py collectstatic --noinput

if [[ ! -r "$HOME/shared/control-probe.json" ]]; then
  echo 'Configure the dedicated WSS deployment probe before stopping production.' >&2
  exit 1
fi

# Preparation above leaves the running release available. Drain in this order.
coordinator_stopped=0
services_touched=0
resume_on_error() {
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
    ln -sfn "$previous" "$HOME/current.next"
    mv -Tf "$HOME/current.next" "$HOME/current"
    sudo /usr/bin/systemctl start psycode-web.service psycode-fragments.service psycode-coordinator.service || true
    if [[ "$storage_service_available" == 1 ]]; then
      sudo /usr/bin/systemctl start psycode-storage.service || true
    fi
  fi
}
trap resume_on_error ERR
coordinator_stopped=1
sudo /usr/bin/systemctl stop psycode-coordinator.service
if [[ -n "$previous" && -f "$HOME/shared/db.sqlite3" ]]; then
  # HTTP and worker stay available while agents finish their sessions.
  for ((attempt=0; attempt<60; attempt++)); do
    open_sessions=$(cd "$previous" && .venv/bin/python manage.py shell -c \
      'from backend.apps.capture.models import CaptureSession, OPEN_STATES; print(CaptureSession.objects.filter(state__in=OPEN_STATES, actual_end__isnull=True).count())' | tail -1)
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
  .venv/bin/python - <<'PY'
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
root = Path('/srv/psycode')
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
with sqlite3.connect(root / 'shared/db.sqlite3') as source:
    with sqlite3.connect(root / f'backups/db-{stamp}.sqlite3') as destination:
        source.backup(destination)
PY
fi
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py recover_capture_sessions
.venv/bin/python manage.py cleanup_capture_uploads
ln -sfn "$release" "$HOME/current.next"
mv -Tf "$HOME/current.next" "$HOME/current"
sudo /usr/bin/systemctl start psycode-web.service psycode-fragments.service psycode-coordinator.service
if [[ "$storage_service_available" == 1 ]]; then
  sudo /usr/bin/systemctl start psycode-storage.service
fi
healthy=0
probe_file="$HOME/shared/control-probe.json"
for ((attempt=0; attempt<30; attempt++)); do
  if curl --fail --silent --output /dev/null --max-time 5 \
      -H 'Host: 144.22.56.52' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/ &&
      [[ -r "$probe_file" ]] &&
      PSYCODE_CONTROL_PROBE="$probe_file" .venv/bin/python deployment/vps/check-control.py; then
    healthy=1
    break
  fi
  sleep 2
done
[[ "$healthy" == 1 ]]
sudo /usr/bin/systemctl is-active psycode-web.service psycode-fragments.service psycode-coordinator.service
if [[ "$storage_service_available" == 1 ]]; then
  sudo /usr/bin/systemctl is-active psycode-storage.service
fi
printf '%s\n' "$revision" > "$HOME/shared/deployed-revision"
trap - ERR
echo "Deployed successfully: $revision"

"""Ejecuta los flujos de navegador que solo requieren el servidor."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time


BROWSER_TESTS = (
    "auth.browser.cjs",
    "frontend.browser.cjs",
    "bitacora-notificaciones.browser.cjs",
    "almacenamiento.browser.cjs",
)

STORAGE_FIXTURE = """
import os
from pathlib import Path
import time

from django.conf import settings
from backend.apps.accounts.models import User

User.objects.create_user(username='storage-browser', email='storage@example.test',
                         password='Synthetic-browser-2026!', role='admin')
root = Path(settings.CAPTURE_FRAGMENT_ROOT)
root.mkdir(mode=0o700)
for key in ('a', 'b'):
    fragment = root / (key * 32 + '.blob')
    fragment.write_bytes(b'synthetic fixture')
    fragment.chmod(0o600)

old = time.time() - settings.CAPTURE_ORPHAN_MAX_AGE_SECONDS - 60
os.utime(root / ('a' * 32 + '.blob'), (old, old))
"""


def run_browser_tests(root, run, artifacts):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = dict(
        os.environ,
        DJANGO_SETTINGS_MODULE="backend.config.test_settings",
        SQLITE_PATH=str(run / "db.sqlite3"),
        PSYCODE_TEST_MONGODB_URI="",
        CAPTURE_FRAGMENT_ROOT=str(run / "fragments"),
        CAPTURE_ORPHAN_MAX_AGE_SECONDS="3600",
        FRONTEND_TEST_URL=f"http://127.0.0.1:{port}",
        FRONTEND_SCREENSHOT_DIR=str(artifacts),
        PLAYWRIGHT_MODULE=os.environ.get("PLAYWRIGHT_MODULE", str(root / "frontend/node_modules/playwright")),
    )
    manage = [sys.executable, "manage.py"]
    subprocess.run([*manage, "migrate", "--noinput", "--verbosity", "0"], cwd=root, env=env, check=True)
    subprocess.run([*manage, "shell", "-c", STORAGE_FIXTURE], cwd=root, env=env, check=True)

    log_path = artifacts / "server.log"
    command = [*manage, "runserver", f"127.0.0.1:{port}", "--insecure", "--noreload"]
    with log_path.open("w") as log, subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log) as server:
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("El servidor de navegador terminó durante el arranque")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("El servidor de navegador no abrió su puerto")

            for name in BROWSER_TESTS:
                print(f"Ejecutando {name}", flush=True)
                subprocess.run(["node", f"backend/apps/web/tests/{name}"], cwd=root, env=env, check=True, timeout=90)
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, help="Directorio para capturas y el log del servidor")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    with TemporaryDirectory(prefix="psycode-web-browser-") as temporary:
        run = Path(temporary)
        artifacts = args.artifacts_dir.resolve() if args.artifacts_dir else run
        if args.artifacts_dir:
            artifacts.mkdir(parents=True, exist_ok=True)
            print(f"Evidencia de navegador: {artifacts}", flush=True)
        try:
            run_browser_tests(root, run, artifacts)
        except (RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            log = artifacts / "server.log"
            if log.is_file():
                print("\n".join(log.read_text().splitlines()[-30:]), file=sys.stderr)
            raise


if __name__ == "__main__":
    main()

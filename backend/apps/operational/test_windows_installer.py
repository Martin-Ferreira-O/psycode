from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from backend.apps.accounts.models import User
from backend.apps.capture.pc_registry import create_agent, revoke_agent


METADATA = "/api/v1/internal/agent-updates/windows-x64"
DOWNLOAD = METADATA + "/1.3.0"
WEB_DOWNLOAD = "/api/v1/pcs/instalador/windows-x64/1.3.0"


def resolve_current(link, active_release):
    resolve = type(link).resolve

    def resolve_path(path, *, strict=False):
        return resolve(active_release() if path == link else path, strict=strict)

    return patch.object(type(link), "resolve", resolve_path)


class AgentUpdateTests(APITestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(PC_WINDOWS_INSTALLER_DIR=str(root)))
        self.agent, key = create_agent(name="PC sintético", box="box-3")
        self.client.credentials(HTTP_AUTHORIZATION=f"Agent {key}")
        self.release = root / "1.3.0"
        self.release.mkdir()
        self.exe = self.release / "PsycodeAgent-Setup-1.3.0-x64.exe"
        self.payload = b"MZ actualizacion sintetica"
        self.digest = sha256(self.payload).hexdigest()
        self.exe.write_bytes(self.payload)
        self.manifest = self.exe.with_suffix(".exe.sha256")
        self.manifest.write_text(f"{self.digest}  {self.exe.name}\n", encoding="ascii")
        self.current = root / "current"
        self.active_release = self.release
        try:
            self.current.symlink_to(self.release.name, target_is_directory=True)
        except OSError as exc:
            # Windows puede impedir enlaces aunque el directorio de prueba sea privado.
            if getattr(exc, "winerror", None) not in (5, 1314):
                raise
            self.enterContext(resolve_current(self.current, lambda: self.active_release))

    def test_metadata_and_binary_for_bound_agent(self):
        response = self.client.get(METADATA, secure=True)
        self.assertEqual(response.json(), {"version": "1.3.0", "size": len(self.payload), "sha256": self.digest})
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.get(DOWNLOAD, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.payload)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.get(METADATA + "/1.2.1", secure=True).status_code, 404)
        self.assertEqual(self.client.get(WEB_DOWNLOAD, secure=True).status_code, 401)

    def test_metadata_and_download_require_https_and_active_individual_key(self):
        browser = APIClient()
        admin = User.objects.create_user(
            username="admin-update", email="update@example.test", password="Synthetic-update-2026!", role="admin",
        )
        browser.get("/", secure=True)
        csrf = browser.cookies["csrftoken"].value
        login = browser.post(
            "/api/v1/auth/login", {"usuario": admin.username, "password": "Synthetic-update-2026!"},
            format="json", secure=True, HTTP_ORIGIN="https://testserver",
            HTTP_X_PSYCODE_BROWSER="1", HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(login.status_code, 200)
        response = browser.get(WEB_DOWNLOAD, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.payload)
        for url in (METADATA, DOWNLOAD):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(APIClient().get(url, secure=True).status_code, 401)
            self.assertEqual(browser.get(url, secure=True).status_code, 401)
            self.assertEqual(APIClient().get(url, secure=True, HTTP_AUTHORIZATION="Agent AAAAA").status_code, 401)
        revoke_agent(self.agent)
        for url in (METADATA, DOWNLOAD):
            self.assertEqual(self.client.get(url, secure=True).status_code, 401)

    def test_invalid_manifest_cannot_be_served(self):
        self.manifest.write_text(f"{self.digest}  otro.exe\n", encoding="ascii")
        for url in (METADATA, DOWNLOAD):
            self.assertEqual(self.client.get(url, secure=True).status_code, 404)

    def test_safe_correlation_for_authenticated_and_rejected_requests(self):
        correlation = str(uuid4())
        with patch("backend.apps.operational.windows_installer.AuditWriter.emit") as audit:
            response = self.client.get(METADATA, secure=True, HTTP_X_PSYCODE_UPDATE_REQUEST=correlation)
            self.assertEqual(response["X-Psycode-Update-Request"], correlation)
            event = audit.call_args.args[0]
            self.assertEqual(event["correlation_id"], correlation)
            self.assertEqual(event["agent_id"], str(self.agent.pk))
            unauthenticated = APIClient().get(DOWNLOAD, secure=True, HTTP_X_PSYCODE_UPDATE_REQUEST="private-input",
                HTTP_AUTHORIZATION="Agent invalid-private-token")
            event = audit.call_args.args[0]
            self.assertEqual(unauthenticated.status_code, 401)
            self.assertEqual(UUID(unauthenticated["X-Psycode-Update-Request"]).version, 4)
            self.assertEqual(event["correlation_id"], unauthenticated["X-Psycode-Update-Request"])
            self.assertEqual(event["http_status"], 401)
            self.assertNotIn("agent_id", event)
            self.assertNotIn("private", str(event))

    def test_publication_can_change_between_metadata_and_download(self):
        self.assertEqual(self.client.get(METADATA, secure=True).status_code, 200)
        release = self.release.parent / "1.3.1"
        release.mkdir()
        exe = release / "PsycodeAgent-Setup-1.3.1-x64.exe"
        exe.write_bytes(self.payload)
        exe.with_suffix(".exe.sha256").write_text(f"{self.digest}  {exe.name}\n", encoding="ascii")
        self.active_release = release
        if self.current.is_symlink():
            self.current.unlink()
            self.current.symlink_to(release.name, target_is_directory=True)
        self.assertEqual(self.client.get(DOWNLOAD, secure=True).status_code, 404)
        self.assertEqual(self.client.get(METADATA, secure=True).json()["version"], "1.3.1")

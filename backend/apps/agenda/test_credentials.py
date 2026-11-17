"""Entrega de secretos sintéticos; sin Smile institucional ni claves reales."""
from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from backend.apps.accounts.models import User
from backend.apps.capture.pc_registry import create_agent, revoke_agent
from backend.apps.capture.pairing import issue_pairing_code
from backend.apps.operational.models import OperationalConfiguration


@override_settings(SMILE_USERNAME="synthetic-user", SMILE_PASSWORD="synthetic-${literal}")
class SmileCredentialsTests(APITestCase):
    url = "/api/v1/internal/smile-credentials"

    def setUp(self):
        self.first, self.key = create_agent(name="Colector sintético", box="box-3")
        self.second, second_key = create_agent(name="Otro PC", box="box-4")
        self.config = OperationalConfiguration.load()
        self.config.smile_collector = self.first
        self.config.smile_url = "https://smile.example.test/index.php/"
        self.config.save()
        self.first_client, self.second_client = APIClient(), APIClient()
        self.first_client.credentials(HTTP_AUTHORIZATION="Agent " + self.key)
        self.second_client.credentials(HTTP_AUTHORIZATION="Agent " + second_key)

    def test_only_current_collector_receives_credentials_over_https_without_cache(self):
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 401)
        insecure = self.first_client.get(self.url)
        self.assertEqual(insecure.status_code, 400)
        self.assertNotIn("synthetic-user", str(insecure.data))
        response = self.first_client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {
            "version": "1", "revision": self.config.smile_revision, "source": "smile",
            "url": self.config.smile_url, "username": "synthetic-user", "password": "synthetic-${literal}",
        })
        self.assertIsNone(self.second_client.get(self.url, secure=True).data["data"])
        self.config.smile_collector = self.second
        self.config.save()
        self.assertIsNone(self.first_client.get(self.url, secure=True).data["data"])
        self.assertEqual(self.second_client.get(self.url, secure=True).data["data"]["username"], "synthetic-user")
        revoke_agent(self.second)
        self.assertEqual(self.second_client.get(self.url, secure=True).status_code, 401)
        for result in (response, insecure, self.client.get(self.url, secure=True)):
            self.assertIn("no-store", result["Cache-Control"])
            self.assertIn("Authorization", result["Vary"])

    def test_missing_or_invalid_server_credentials_fail_closed_without_echo(self):
        for value in ("", " ", "invalid\x00secret", "secret\nline", "x" * 1025):
            with self.subTest(value_length=len(value)), override_settings(SMILE_PASSWORD=value):
                result = self.first_client.get(self.url, secure=True)
                self.assertEqual(result.status_code, 503)
                self.assertEqual(result.data["error"]["code"], "SMILE_CREDENTIALS_UNAVAILABLE")
                self.assertNotIn("synthetic-user", str(result.data))
        with override_settings(SMILE_PASSWORD="rotated-fixture"):
            self.assertEqual(self.first_client.get(self.url, secure=True).data["data"]["password"], "rotated-fixture")

    def test_browser_admin_and_operational_profile_never_receive_secrets(self):
        admin = User.objects.create_user(username="secret-admin", email="secret@example.test", role="admin")
        self.client.force_authenticate(admin)
        # La sesión web no es una credencial de máquina.
        browser = APIClient()
        browser.credentials(HTTP_AUTHORIZATION="Bearer " + str(RefreshToken.for_user(admin).access_token))
        self.assertEqual(browser.get(self.url, secure=True).status_code, 401)
        for result in (self.client.get("/api/v1/configuracion-operativa"),
                       self.first_client.get("/api/v1/internal/smile-configuration", secure=True)):
            self.assertNotIn("synthetic-user", str(result.data))
            self.assertNotIn("synthetic-${literal}", str(result.data))

    def test_prepared_token_cannot_get_secrets_until_confirmation_and_retry_is_safe(self):
        _, code, _ = issue_pairing_code(self.first.pk)
        installation = str(uuid4())
        public = APIClient()
        prepared = public.post("/api/v1/internal/pcs/vincular", {
            "code": code, "installation_id": installation, "secret": "s" * 43,
        }, format="json", secure=True)
        self.assertEqual(prepared.status_code, 200, prepared.data)
        self.assertNotIn("synthetic-user", str(prepared.data))
        token = prepared.data["data"]["api_key"]
        machine = APIClient()
        machine.credentials(HTTP_AUTHORIZATION="Agent " + token)
        self.assertEqual(machine.get(self.url, secure=True).status_code, 401)
        for _ in range(2):
            confirmed = machine.post("/api/v1/internal/pcs/confirmar", {"installation_id": installation},
                                     format="json", secure=True)
            self.assertEqual(confirmed.status_code, 200, confirmed.data)
            self.assertEqual(confirmed.data["data"]["smile_credentials_version"], "1")
            self.assertNotIn("synthetic-user", str(confirmed.data))
            self.assertEqual(machine.get(self.url, secure=True).data["data"]["username"], "synthetic-user")
        self.assertEqual(self.first_client.get(self.url, secure=True).status_code, 401)

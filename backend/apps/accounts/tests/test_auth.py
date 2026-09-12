import io
import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from backend.apps.accounts.clients import EmailClient
from backend.apps.accounts.models import PasswordReset, RefreshSession, User
from backend.apps.accounts.repositories import AccountsRepository
from backend.apps.accounts.services import AccountsService, reset_digest
from backend.common.errors import ServiceError

PASSWORD = "Synthetic-passphrase-2026!"
NEW_PASSWORD = "Different-synthetic-credential-2027!"
PREFIX = "/api/v1/auth/"


class AuthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="martin", email="Martin@Example.test", password=PASSWORD,
                                           first_name="Martin", last_name="Prueba")

    def setUp(self):
        self.client = APIClient()

    def login(self, identifier="martin"):
        response = self.client.post(PREFIX + "login", {"usuario": identifier, "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"success", "data", "message", "timestamp"})
        return response.data["data"]

    def authorize(self, pair):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + pair["access_token"])

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, getattr(response, "data", response.content))
        data = response.json()
        self.assertEqual(set(data), {"success", "error", "timestamp"})
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], code)
        if status == 401:
            self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def request_reset(self):
        with patch.object(EmailClient, "send_password_reset") as sender:
            response = self.client.post(PREFIX + "password-reset", {"correo": self.user.email}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        return parse_qs(urlsplit(sender.call_args.args[1]).query)["token"][0]

    def confirm(self, token, password=NEW_PASSWORD):
        return self.client.post(PREFIX + "password-reset/confirm", {"token": token, "nueva_password": password}, format="json")

    def test_login_username_email_and_user_contract(self):
        pair = self.login(" MARTIN@EXAMPLE.TEST ")
        self.assertEqual(pair["expires_in"], 3600)
        self.assertEqual(pair["token_type"], "Bearer")
        self.authorize(pair)
        response = self.client.get(PREFIX + "me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {"id": str(self.user.pk), "usuario": "martin", "nombre": "Martin Prueba", "correo": "martin@example.test", "activo": True})
        self.assertNotIn(PASSWORD, self.user.password)
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertEqual(self.user.pk.version, 4)

    def test_invalid_credentials_do_not_distinguish_missing_user(self):
        for username in ("martin", "absent", "MARTIN"):
            response = self.client.post(PREFIX + "login", {"usuario": username, "password": "incorrect"}, format="json")
            self.assert_error(response, 401, "AUTH_INVALID_CREDENTIALS")

    def test_password_not_trimmed(self):
        response = self.client.post(PREFIX + "login", {"usuario": "martin", "password": PASSWORD + " "}, format="json")
        self.assert_error(response, 401, "AUTH_INVALID_CREDENTIALS")

    def test_inactive_login_only_disclosed_after_password_check(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.client.post(PREFIX + "login", {"usuario": "martin", "password": PASSWORD}, format="json")
        self.assert_error(response, 403, "AUTH_USER_INACTIVE")
        response = self.client.post(PREFIX + "login", {"usuario": "martin", "password": "bad"}, format="json")
        self.assert_error(response, 401, "AUTH_INVALID_CREDENTIALS")

    def test_inactive_user_cannot_use_access_or_refresh(self):
        pair = self.login()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.authorize(pair)
        self.assert_error(self.client.get(PREFIX + "me"), 403, "AUTH_USER_INACTIVE")
        self.assert_error(self.client.post(PREFIX + "refresh", {"refresh_token": pair["refresh_token"]}, format="json"), 403, "AUTH_USER_INACTIVE")

    def test_missing_invalid_expired_and_wrong_type_access(self):
        self.assert_error(self.client.get(PREFIX + "me"), 401, "AUTH_REQUIRED")
        refresh = RefreshToken.for_user(self.user)
        expired = refresh.access_token
        expired.set_exp(lifetime=timedelta(seconds=-1))
        for token in ("invalid", str(expired), str(refresh)):
            self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
            self.assert_error(self.client.get(PREFIX + "me"), 401, "AUTH_INVALID_TOKEN")

    def test_refresh_rotates_and_rejects_replay(self):
        pair = self.login()
        response = self.client.post(PREFIX + "refresh", {"refresh_token": pair["refresh_token"]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response.data["data"]["refresh_token"], pair["refresh_token"])
        self.assertEqual(RefreshSession.objects.filter(revoked_at__isnull=True).count(), 1)
        self.assert_error(self.client.post(PREFIX + "refresh", {"refresh_token": pair["refresh_token"]}, format="json"), 401, "AUTH_INVALID_REFRESH_TOKEN")

    def test_invalid_expired_untracked_and_access_as_refresh(self):
        untracked = RefreshToken.for_user(self.user)
        expired = RefreshToken.for_user(self.user)
        expired.set_exp(lifetime=timedelta(seconds=-1))
        for token in ("bad", str(untracked), str(expired), str(untracked.access_token)):
            self.assert_error(self.client.post(PREFIX + "refresh", {"refresh_token": token}, format="json"), 401, "AUTH_INVALID_REFRESH_TOKEN")

    def test_logout_is_idempotent_and_keeps_access_until_expiry(self):
        pair = self.login()
        self.authorize(pair)
        for _ in range(2):
            response = self.client.post(PREFIX + "logout", {"refresh_token": pair["refresh_token"]}, format="json")
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(PREFIX + "me").status_code, 200)
        self.assert_error(self.client.post(PREFIX + "refresh", {"refresh_token": pair["refresh_token"]}, format="json"), 401, "AUTH_INVALID_REFRESH_TOKEN")

    def test_logout_rejects_other_user_refresh(self):
        pair = self.login()
        User.objects.create_user(username="other", email="other@example.test", password=PASSWORD)
        other = self.login("other")
        self.authorize(pair)
        self.assert_error(self.client.post(PREFIX + "logout", {"refresh_token": other["refresh_token"]}, format="json"), 403, "AUTH_FORBIDDEN")

    def test_missing_extra_null_numeric_and_empty_fields(self):
        for data in ({}, {"usuario": None, "password": PASSWORD}, {"usuario": 123, "password": PASSWORD},
                     {"usuario": "martin", "password": 123}, {"usuario": "martin", "password": ""},
                     {"usuario": "martin", "password": PASSWORD, "admin": True}, []):
            self.assert_error(self.client.post(PREFIX + "login", data, format="json"), 400, "VALIDATION_ERROR")

    def test_malformed_json_and_media_type(self):
        self.assert_error(self.client.post(PREFIX + "login", "{", content_type="application/json"), 400, "VALIDATION_ERROR")
        self.assert_error(self.client.post(PREFIX + "login", "plain", content_type="text/plain"), 415, "UNSUPPORTED_MEDIA_TYPE")

    def test_queries_and_get_body_rejected(self):
        self.assert_error(self.client.post(PREFIX + "login?foo=1&foo=2", {"usuario": "martin", "password": PASSWORD}, format="json"), 400, "VALIDATION_ERROR")
        self.authorize(self.login())
        self.assert_error(self.client.generic("GET", PREFIX + "me", "{}", content_type="application/json"), 400, "VALIDATION_ERROR")

    def test_method_error_and_unknown_route(self):
        response = self.client.get(PREFIX + "login")
        self.assert_error(response, 405, "METHOD_NOT_ALLOWED")
        self.assertIn("POST", response["Allow"])
        self.assert_error(self.client.get("/api/v1/unknown"), 404, "RESOURCE_NOT_FOUND")

    @override_settings(DEBUG=True)
    def test_unknown_routes_and_trailing_slashes_stay_json_in_development(self):
        for path in ("/api/v1/unknown", PREFIX + "login/", "/api/v1/alerts"):
            self.assert_error(self.client.get(path), 404, "RESOURCE_NOT_FOUND")

    def test_cors_only_configured_origin(self):
        allowed = self.client.options(PREFIX + "login", HTTP_ORIGIN="http://localhost:5173", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST", HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,authorization")
        self.assertEqual(allowed["Access-Control-Allow-Origin"], "http://localhost:5173")
        denied = self.client.options(PREFIX + "login", HTTP_ORIGIN="https://other.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", denied)

    def test_persistence_errors_use_503_without_leaking_exception(self):
        with patch.object(AccountsRepository, "find_user", side_effect=OperationalError("private-db-uri")):
            response = self.client.post(PREFIX + "login", {"usuario": "martin", "password": PASSWORD}, format="json")
        self.assert_error(response, 503, "PERSISTENCE_UNAVAILABLE")
        self.assertNotIn("private-db-uri", response.content.decode())

    def test_unexpected_error_uses_safe_envelope(self):
        with patch.object(AccountsRepository, "find_user", side_effect=RuntimeError("private-token")):
            response = self.client.post(PREFIX + "login", {"usuario": "martin", "password": PASSWORD}, format="json")
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertNotIn("private-token", response.content.decode())

    def test_reset_stores_digest_and_invalidates_previous_request(self):
        first = self.request_reset()
        second = self.request_reset()
        record = PasswordReset.objects.get(user=self.user)
        self.assertEqual(record.token_hash, reset_digest(second))
        self.assertNotEqual(record.token_hash, second)
        self.assert_error(self.confirm(first), 400, "AUTH_INVALID_RESET_TOKEN")
        self.assertEqual(self.confirm(second).status_code, 200)

    def test_reset_confirm_changes_password_and_invalidates_all_old_tokens(self):
        pair = self.login()
        token = self.request_reset()
        self.assertEqual(self.confirm(token).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.check_password(PASSWORD))
        self.assertFalse(PasswordReset.objects.filter(user=self.user).exists())
        self.authorize(pair)
        self.assert_error(self.client.get(PREFIX + "me"), 401, "AUTH_INVALID_TOKEN")
        self.assert_error(self.client.post(PREFIX + "refresh", {"refresh_token": pair["refresh_token"]}, format="json"), 401, "AUTH_INVALID_REFRESH_TOKEN")
        self.assert_error(self.confirm(token), 400, "AUTH_INVALID_RESET_TOKEN")
        self.assertEqual(self.client.post(PREFIX + "login", {"usuario": "martin", "password": NEW_PASSWORD}, format="json").status_code, 200)

    def test_expired_reset_and_bad_password_do_not_change_user(self):
        token = self.request_reset()
        self.assert_error(self.confirm(token, "123"), 400, "VALIDATION_ERROR")
        self.assertTrue(PasswordReset.objects.filter(user=self.user).exists())
        PasswordReset.objects.filter(user=self.user).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assert_error(self.confirm(token), 400, "AUTH_INVALID_RESET_TOKEN")

    def test_external_password_change_invalidates_reset_and_jwt(self):
        pair = self.login()
        token = self.request_reset()
        self.user.set_password(NEW_PASSWORD)
        self.user.save()
        self.assert_error(self.confirm(token), 400, "AUTH_INVALID_RESET_TOKEN")
        self.authorize(pair)
        self.assert_error(self.client.get(PREFIX + "me"), 401, "AUTH_INVALID_TOKEN")
        self.assert_error(self.client.post(PREFIX + "refresh", {"refresh_token": pair["refresh_token"]}, format="json"), 401, "AUTH_INVALID_REFRESH_TOKEN")

    def test_reset_unknown_inactive_and_invalid_email(self):
        for email, status, code in (("missing@example.test", 404, "AUTH_USER_NOT_FOUND"), ("bad", 400, "VALIDATION_ERROR")):
            self.assert_error(self.client.post(PREFIX + "password-reset", {"correo": email}, format="json"), status, code)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assert_error(self.client.post(PREFIX + "password-reset", {"correo": self.user.email}, format="json"), 403, "AUTH_USER_INACTIVE")

    def test_reset_cannot_confirm_for_deactivated_user(self):
        token = self.request_reset()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assert_error(self.confirm(token), 403, "AUTH_USER_INACTIVE")

    def test_email_failure_discards_only_failed_reset(self):
        with patch.object(EmailClient, "send_password_reset", side_effect=ServiceError("PASSWORD_RESET_DELIVERY_FAILED", "No enviado", 503)):
            response = self.client.post(PREFIX + "password-reset", {"correo": self.user.email}, format="json")
        self.assert_error(response, 503, "PASSWORD_RESET_DELIVERY_FAILED")
        self.assertFalse(PasswordReset.objects.exists())

    def test_failed_older_email_does_not_delete_newer_reset(self):
        old = self.request_reset()
        new = self.request_reset()
        AccountsRepository().discard_reset(reset_digest(old))
        self.assertEqual(PasswordReset.objects.get(user=self.user).token_hash, reset_digest(new))

    def test_password_change_rolls_back_if_session_revocation_fails(self):
        token = self.request_reset()
        with patch("backend.apps.accounts.repositories.RefreshSession.objects.filter", side_effect=OperationalError("offline")):
            self.assert_error(self.confirm(token), 503, "PERSISTENCE_UNAVAILABLE")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(PasswordReset.objects.filter(user=self.user).exists())

    def test_user_constraints(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user(username="invalid@name", email="valid@example.test", password=PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="different", email="MARTIN@EXAMPLE.TEST", password=PASSWORD)

    @override_settings(DEBUG=True)
    def test_demo_user_command_is_idempotent(self):
        out = io.StringIO()
        call_command("seed_demo_user", stdout=out)
        demo = User.objects.get(username="martin.demo")
        original_hash = demo.password
        call_command("seed_demo_user", stdout=out)
        demo.refresh_from_db()
        self.assertEqual(demo.password, original_hash)
        self.assertFalse(demo.is_staff or demo.is_superuser)

    def test_demo_user_refused_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_user")


class EmailClientTests(SimpleTestCase):
    def test_worker_timeout_maps_to_delivery_error(self):
        with patch("backend.apps.accounts.clients.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 10)):
            with self.assertRaises(ServiceError) as caught:
                EmailClient().send_password_reset("user@example.test", "https://example.test/reset?token=secret")
        self.assertEqual(caught.exception.code, "PASSWORD_RESET_DELIVERY_FAILED")

    def test_worker_failure_maps_to_delivery_error(self):
        with patch("backend.apps.accounts.clients.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(ServiceError) as caught:
                EmailClient().send_password_reset("user@example.test", "https://example.test/reset?token=secret")
        self.assertEqual(caught.exception.status, 503)

    def test_real_worker_writes_private_local_email_without_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"EMAIL_BACKEND": "django.core.mail.backends.filebased.EmailBackend", "EMAIL_FILE_PATH": directory}):
                EmailClient().send_password_reset("user@example.test", "http://localhost:5173/password-reset/confirm?token=synthetic")
            messages = list(Path(directory).glob("*.log"))
            self.assertEqual(len(messages), 1)
            self.assertIn("token=synthetic", messages[0].read_text())
            self.assertEqual(messages[0].stat().st_mode & 0o077, 0)


class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="concurrent", email="concurrent@example.test", password=PASSWORD)

    def run_concurrently(self, operation):
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                operation(AccountsService(AccountsRepository(), EmailClient()))
                return "success"
            except ServiceError as exc:
                return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(pool.map(lambda _: run(), range(2)))

    def test_single_refresh_can_only_rotate_once(self):
        pair = AccountsService(AccountsRepository(), EmailClient()).login("concurrent", PASSWORD)
        results = self.run_concurrently(lambda service: service.refresh(pair["refresh_token"]))
        self.assertEqual(results, ["AUTH_INVALID_REFRESH_TOKEN", "success"])
        self.assertEqual(RefreshSession.objects.filter(revoked_at__isnull=True).count(), 1)

    def test_reset_token_can_only_be_consumed_once(self):
        with patch.object(EmailClient, "send_password_reset") as sender:
            AccountsService(AccountsRepository(), EmailClient()).request_password_reset(self.user.email)
        token = parse_qs(urlsplit(sender.call_args.args[1]).query)["token"][0]
        results = self.run_concurrently(lambda service: service.confirm_password_reset(token, NEW_PASSWORD))
        self.assertEqual(results, ["AUTH_INVALID_RESET_TOKEN", "success"])

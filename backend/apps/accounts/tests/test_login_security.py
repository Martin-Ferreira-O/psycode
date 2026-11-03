from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.core.management import call_command
from django.db import OperationalError, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from backend.apps.accounts.browser_sessions import ACCESS_COOKIE, REFRESH_COOKIE
from backend.apps.accounts.models import AuthRateLimit, RefreshSession, User
from backend.apps.accounts.rate_limits import consume_auth_attempt
from backend.apps.accounts.repositories import AccountsRepository
from backend.common.errors import ServiceError

PREFIX = "/api/v1/auth/"
PASSWORD = "Synthetic-security-test-2026!"


class LoginSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="security", email="security@example.test", password=PASSWORD)

    def setUp(self):
        self.client = APIClient()

    def login(self, identifier="security", **headers):
        return self.client.post(PREFIX + "login", {"usuario": identifier, "password": PASSWORD},
                                format="json", **headers)

    @override_settings(AUTH_LOGIN_IP_LIMIT=2)
    def test_ip_limits_even_malformed_requests_before_password_hashing(self):
        for _ in range(2):
            self.assertEqual(self.client.post(PREFIX + "login", "{", content_type="application/json").status_code, 400)
        with patch.object(AccountsRepository, "find_user") as lookup:
            response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["error"]["code"], "AUTH_RATE_LIMITED")
        self.assertGreater(int(response["Retry-After"]), 0)
        lookup.assert_not_called()
        self.assertEqual(self.login(REMOTE_ADDR="192.0.2.2").status_code, 200)

    @override_settings(AUTH_LOGIN_IP_LIMIT=1)
    def test_forwarded_headers_cannot_bypass_ip_limit(self):
        self.assertEqual(self.login(HTTP_X_FORWARDED_FOR="192.0.2.1").status_code, 200)
        self.assertEqual(self.login(HTTP_X_FORWARDED_FOR="192.0.2.2", HTTP_X_REAL_IP="192.0.2.3").status_code, 429)

    @override_settings(AUTH_LOGIN_ACCOUNT_LIMIT=2)
    def test_username_and_email_share_limit_across_ips_and_failed_transactions(self):
        for identifier, ip in [("security", "192.0.2.1"), (" SECURITY@EXAMPLE.TEST ", "192.0.2.2")]:
            response = self.client.post(PREFIX + "login", {"usuario": identifier, "password": "wrong"},
                                        format="json", REMOTE_ADDR=ip)
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.login(REMOTE_ADDR="192.0.2.3").status_code, 429)
        self.assertEqual(RefreshSession.objects.count(), 0)

    @override_settings(AUTH_LOGIN_ACCOUNT_LIMIT=1)
    def test_unknown_accounts_have_the_same_temporary_limit(self):
        self.assertEqual(self.login("absent", REMOTE_ADDR="192.0.2.1").status_code, 401)
        self.assertEqual(self.login("absent", REMOTE_ADDR="192.0.2.2").status_code, 429)
        self.assertEqual(self.login(REMOTE_ADDR="192.0.2.3").status_code, 200)
        self.assertEqual(self.login(REMOTE_ADDR="192.0.2.4").status_code, 429)

    @override_settings(AUTH_LOGIN_IP_LIMIT=1, AUTH_LOGIN_ACCOUNT_LIMIT=1)
    def test_expiry_allows_login_without_manual_unlock_and_does_not_extend_on_rejection(self):
        self.assertEqual(self.login().status_code, 200)
        expiry = AuthRateLimit.objects.get(count=1, key=AuthRateLimit.objects.first().key).expires_at
        self.assertEqual(self.login().status_code, 429)
        self.assertEqual(AuthRateLimit.objects.first().expires_at, expiry)
        AuthRateLimit.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.login().status_code, 200)
        self.assertTrue(all(c.count == 1 for c in AuthRateLimit.objects.all()))

    @override_settings(AUTH_REFRESH_IP_LIMIT=1, AUTH_RESET_IP_LIMIT=1)
    def test_refresh_and_reset_confirmation_are_limited_without_affecting_login(self):
        for path in ("refresh", "password-reset/confirm", "password-reset"):
            self.assertEqual(self.client.post(PREFIX + path, {}, format="json").status_code, 400)
            self.assertEqual(self.client.post(PREFIX + path, {}, format="json").status_code, 429)
        self.assertEqual(self.login().status_code, 200)

    def test_counter_failure_fails_closed_and_no_identity_is_stored(self):
        with patch("backend.apps.accounts.rate_limits.AuthRateLimit.objects.select_for_update",
                   side_effect=OperationalError("private database error")):
            response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private database error", response.content)
        self.assertEqual(RefreshSession.objects.count(), 0)
        self.assertEqual(self.login().status_code, 200)
        for counter in AuthRateLimit.objects.all():
            self.assertRegex(counter.key, r"^[a-f0-9]{64}$")

    def test_password_changed_while_checking_does_not_issue_a_session(self):
        original = User.check_password

        def changed(user, password):
            result = original(user, password)
            other = User.objects.get(pk=user.pk)
            other.set_password("Other-synthetic-credential-2026!")
            other.save(update_fields=["password"])
            return result

        with patch.object(User, "check_password", changed):
            self.assertEqual(self.login().status_code, 401)
        self.assertEqual(RefreshSession.objects.count(), 0)

    def test_cleanup_removes_only_expired_counters(self):
        self.login()
        active = AuthRateLimit.objects.count()
        AuthRateLimit.objects.create(key="a" * 64, expires_at=timezone.now() - timedelta(seconds=1))
        call_command("cleanup_auth_rate_limits", stdout=StringIO())
        self.assertEqual(AuthRateLimit.objects.count(), active)

    def test_auth_responses_and_html_have_browser_security_headers(self):
        for response in (self.client.get("/"), self.login(), self.client.post(PREFIX + "login", {}, format="json")):
            self.assertIn("no-store", response["Cache-Control"])
            self.assertIn("script-src 'self'", response["Content-Security-Policy"])
            self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
            self.assertEqual(response["X-Frame-Options"], "DENY")
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("csrftoken", self.client.cookies)


class BrowserSessionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username="security", email="security@example.test", password=PASSWORD)

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get("/", secure=True)

    def post(self, path, data=None, csrf=True):
        headers = {"HTTP_X_PSYCODE_BROWSER": "1", "HTTP_ORIGIN": "https://testserver"}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = self.client.cookies["csrftoken"].value
        return self.client.post(PREFIX + path, data if data is not None else {}, format="json", secure=True, **headers)

    def login(self, csrf=True):
        return self.post("login", {"usuario": "security", "password": PASSWORD}, csrf=csrf)

    def test_browser_login_requires_csrf_and_never_exposes_tokens_in_json(self):
        self.assertEqual(self.login(csrf=False).status_code, 403)
        old_csrf = self.client.cookies["csrftoken"].value
        response = self.login()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"], {"authenticated": True})
        self.assertNotEqual(old_csrf, self.client.cookies["csrftoken"].value)
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            cookie = response.cookies[name]
            self.assertTrue(cookie["httponly"])
            self.assertTrue(cookie["secure"])
            self.assertEqual(cookie["samesite"], "Strict")
            self.assertNotIn(cookie.value, response.content.decode())

    def test_cookie_auth_refresh_rotation_and_immediate_logout_revocation(self):
        self.assertEqual(self.login().status_code, 200)
        old_refresh = self.client.cookies[REFRESH_COOKIE].value
        self.assertEqual(self.client.get(PREFIX + "me", secure=True).status_code, 200)
        self.assertEqual(self.post("refresh", csrf=False).status_code, 403)
        self.assertEqual(self.post("refresh").status_code, 200)
        self.assertNotEqual(self.client.cookies[REFRESH_COOKIE].value, old_refresh)
        stolen = self.client.cookies[ACCESS_COOKIE].value
        self.assertEqual(self.post("logout", csrf=False).status_code, 403)
        self.assertEqual(self.post("logout").status_code, 204)
        self.assertFalse(self.client.cookies[ACCESS_COOKIE].value)
        self.client.cookies[ACCESS_COOKIE] = stolen
        self.assertEqual(self.client.get(PREFIX + "me", secure=True).status_code, 401)
        self.client.cookies[REFRESH_COOKIE] = old_refresh
        self.assertEqual(self.post("refresh").status_code, 401)

    def test_cookie_writes_need_csrf_without_browser_header_too(self):
        self.login()
        response = self.client.post(PREFIX + "logout", {}, format="json", secure=True)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RefreshSession.objects.filter(revoked_at__isnull=True).count(), 1)

    def test_bearer_api_stays_compatible_without_csrf_or_cookies(self):
        api = APIClient(enforce_csrf_checks=True)
        response = api.post(PREFIX + "login", {"usuario": "security", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.data["data"])
        self.assertNotIn(ACCESS_COOKIE, response.cookies)
        api.credentials(HTTP_AUTHORIZATION="Bearer " + response.data["data"]["access_token"])
        self.assertEqual(api.get(PREFIX + "me").status_code, 200)


class RateLimitConcurrencyTests(TransactionTestCase):
    def test_parallel_requests_cannot_spend_the_same_last_attempt(self):
        barrier = Barrier(4)

        def attempt(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                consume_auth_attempt("concurrent", "synthetic", limit=2, seconds=60)
                return "allowed"
            except ServiceError as exc:
                return exc.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
        self.assertEqual(results.count("allowed"), 2)
        self.assertEqual(results.count("AUTH_RATE_LIMITED"), 2)
        self.assertEqual(AuthRateLimit.objects.get().count, 2)

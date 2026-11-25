from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from backend.apps.accounts.models import Role, User

from .speechmatics_catalog import FRESH_SECONDS, RETRY_SECONDS, batch_catalog, parse_batch_rates


PRICING = """# Pricing

## Speech-to-text list rates (USD per hour)

| Mode | Model | Current list rate | Original rate before promotion |
| --- | --- | --- | --- |
| Pre-recorded | Enhanced | 0.9525 | 1.2 |
| Pre-recorded | New Batch | 0.24 | — |
| Real-time | Oak 1 | 0.46 | — |

## Add-on list rates (USD per hour)
| Add-on | Mode | List rate | Available models |
| --- | --- | --- | --- |
| Translation | Pre-recorded | 0.65 | Enhanced |
"""
MODULE = "backend.apps.operational.speechmatics_catalog"
URL = "/api/v1/configuracion-operativa/speechmatics"


class SpeechmaticsCatalogTests(SimpleTestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "prices.json"
        self.enterContext(self.settings(SPEECHMATICS_CATALOG_PATH=self.path))

    def test_parser_reads_batch_list_rates_and_new_models(self):
        self.assertEqual(parse_batch_rates(PRICING), [
            {"id": "enhanced", "name": "Enhanced", "usd_per_hour": 0.9525},
            {"id": "new-batch", "name": "New Batch", "usd_per_hour": 0.24},
        ])
        self.assertIsNone(parse_batch_rates(PRICING.replace("0.9525", "On request"))[0]["usd_per_hour"])
        for invalid in (PRICING.replace("USD per hour", "USD per minute"),
                        PRICING.replace("0.9525", "0,95"),
                        PRICING.replace("New Batch", "Enhanced"),
                        "<html>503</html>"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_batch_rates(invalid)

    def test_last_good_rates_survive_failures_and_refresh_after_backoff(self):
        models = parse_batch_rates(PRICING)
        changed = parse_batch_rates(PRICING.replace("0.9525", "0.76"))
        now = 1_800_000_000
        with (patch(f"{MODULE}.time", return_value=now) as clock,
              patch(f"{MODULE}._fetch_batch_rates", side_effect=[models, ValueError(), changed]) as fetch):
            first = batch_catalog()
            self.assertEqual(first["status"], "fresh")
            self.assertEqual(first["models"], models)
            self.assertEqual(batch_catalog(), first)
            fetch.assert_called_once()

            clock.return_value += FRESH_SECONDS
            with self.assertLogs(MODULE, level="WARNING"):
                stale = batch_catalog()
            self.assertEqual(stale, {**first, "status": "stale"})
            self.assertEqual(batch_catalog(), stale)
            self.assertEqual(fetch.call_count, 2)

            clock.return_value += RETRY_SECONDS
            updated = batch_catalog()
            self.assertEqual(updated["status"], "fresh")
            self.assertEqual(updated["models"], changed)
            self.assertNotEqual(updated["fetched_at"], first["fetched_at"])

    def test_first_fetch_timeout_returns_unavailable_and_limits_retries(self):
        with (patch(f"{MODULE}._fetch_batch_rates", side_effect=httpx.ReadTimeout("timeout")) as fetch,
              self.assertLogs(MODULE, level="WARNING")):
            self.path.write_text("{corrupt", encoding="utf-8")
            unavailable = {"status": "unavailable", "models": [], "fetched_at": None}
            self.assertEqual(batch_catalog(), unavailable)
            self.assertEqual(batch_catalog(), unavailable)
            fetch.assert_called_once()


class SpeechmaticsCatalogAccessTests(APITestCase):
    def test_only_admin_can_trigger_catalog_lookup(self):
        with patch("backend.apps.operational.views.batch_catalog", return_value={"models": []}) as lookup:
            self.assertEqual(self.client.get(URL).status_code, 401)
            supervisor = User.objects.create_user(
                username="pricing-supervisor", email="supervisor@example.test", role=Role.SUPERVISOR,
            )
            self.client.force_authenticate(supervisor)
            self.assertEqual(self.client.get(URL).status_code, 403)
            lookup.assert_not_called()

            admin = User.objects.create_user(username="pricing-admin", email="admin@example.test", role=Role.ADMIN)
            self.client.force_authenticate(admin)
            response = self.client.get(URL)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["data"], {"models": []})
            self.assertEqual(response["Cache-Control"], "no-store, private")
            lookup.assert_called_once()

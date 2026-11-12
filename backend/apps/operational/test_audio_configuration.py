from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from backend.apps.accounts.models import Role, User
from backend.common.errors import ServiceError

from .models import AudioChunkConfigurationChange, OperationalConfiguration
from .services import OperationalService


class AudioConfigurationTests(APITestCase):
    url = "/api/v1/configuracion-operativa"

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="audio_admin", email="admin@example.test", password="Test-password-123", role=Role.ADMIN,
        )
        cls.supervisor = User.objects.create_user(
            username="audio_supervisor", email="supervisor@example.test", password="Test-password-123",
            role=Role.SUPERVISOR,
        )

    def setUp(self):
        self.client.force_authenticate(self.admin)
        self.config = OperationalConfiguration.load()
        self.config.primary_email = "lista@example.test"
        self.config.save()

    def test_defaults_get_and_put_persistence_with_minimum_and_modes(self):
        data = self.client.get(self.url).data["data"]
        self.assertEqual((data["audio_chunk_duration"], data["audio_chunk_mode"]), (60, "fixed"))
        for duration, mode in ((10, "session"), (120, "fixed")):
            response = self.client.put(self.url, {
                "audio_chunk_duration": duration, "audio_chunk_mode": mode,
            }, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.config.refresh_from_db()
            self.assertEqual((self.config.audio_chunk_duration, self.config.audio_chunk_mode), (duration, mode))
            self.assertEqual(self.client.get(self.url).data["data"], response.data["data"])
        changes = list(AudioChunkConfigurationChange.objects.order_by("pk"))
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0].actor_id, str(self.admin.pk))
        self.assertEqual((changes[0].before_duration, changes[0].after_duration), (60, 10))
        self.assertEqual((changes[0].before_mode, changes[0].after_mode), ("fixed", "session"))
        self.assertIsNotNone(changes[0].created_at)
        self.assertEqual((changes[1].before_duration, changes[1].before_mode), (10, "session"))

    def test_partial_legacy_and_unchanged_updates_do_not_reset_or_audit(self):
        service = OperationalService()
        service.update_config(self.admin, {"audio_chunk_mode": "session"})
        service.update_config(self.admin, {"audio_chunk_duration": 90})
        service.update_config(self.admin, {"open_time": "09:00"})
        service.update_config(self.admin, {"audio_chunk_duration": 90, "audio_chunk_mode": "session"})
        self.config.refresh_from_db()
        self.assertEqual((self.config.audio_chunk_duration, self.config.audio_chunk_mode), (90, "session"))
        self.assertEqual(AudioChunkConfigurationChange.objects.count(), 2)

    def test_invalid_values_do_not_change_configuration_or_audit(self):
        before = self.config.updated_at
        invalid = {
            "audio_chunk_duration": [True, False, 9, 0, -10, 10.5, 10.0, "10", None, [], {}],
            "audio_chunk_mode": [True, False, 1, "", "other", None, [], {}],
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.put(self.url, {field: value}, format="json")
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn(field, response.data["error"]["details"]["fields"])
        self.config.refresh_from_db()
        self.assertEqual(self.config.updated_at, before)
        self.assertEqual((self.config.audio_chunk_duration, self.config.audio_chunk_mode), (60, "fixed"))
        self.assertFalse(AudioChunkConfigurationChange.objects.exists())

    def test_permissions_http_and_service(self):
        self.admin.is_active = False
        for actor in (self.supervisor, self.admin, AnonymousUser()):
            self.client = APIClient()
            if actor.is_authenticated:
                self.client.force_authenticate(actor)
            expected = 403 if actor.is_authenticated else 401
            self.assertEqual(self.client.get(self.url).status_code, expected)
            self.assertEqual(self.client.put(self.url, {"audio_chunk_duration": 10}, format="json").status_code, expected)
            with self.assertRaises(ServiceError):
                OperationalService().update_config(actor, {"audio_chunk_mode": "session"})
        self.config.refresh_from_db()
        self.assertEqual(self.config.audio_chunk_duration, 60)
        self.assertFalse(AudioChunkConfigurationChange.objects.exists())

    def test_audit_failure_rolls_back_configuration(self):
        before = self.config.updated_at
        with patch.object(AudioChunkConfigurationChange.objects, "create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                OperationalService().update_config(self.admin, {"audio_chunk_duration": 10})
        self.config.refresh_from_db()
        self.assertEqual(self.config.audio_chunk_duration, 60)
        self.assertEqual(self.config.updated_at, before)
        self.assertFalse(AudioChunkConfigurationChange.objects.exists())

    def test_database_minimum_and_choices(self):
        for payload in ({"audio_chunk_duration": 9}, {"audio_chunk_mode": "other"}):
            with self.subTest(payload=payload), self.assertRaises(IntegrityError), transaction.atomic():
                OperationalConfiguration.objects.filter(pk=1).update(**payload)


class AudioConfigurationMigrationTests(TransactionTestCase):
    def test_existing_configuration_preserved_with_audio_defaults(self):
        old = [("operational", "0002_notification_preferences")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(old)
        model = executor.loader.project_state(old).apps.get_model("operational", "OperationalConfiguration")
        model.objects.create(
            pk=1, enabled_days=[1, 3], open_time="09:00", close_time="16:00",
            primary_email="lista@example.test", backup_email="", timezone="UTC",
            notification_mode="supervisores_activos", backup_enabled=False,
        )
        before = model.objects.values().get(pk=1)
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        after = OperationalConfiguration.objects.values().get(pk=1)
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertEqual((after["audio_chunk_duration"], after["audio_chunk_mode"]), (60, "fixed"))
        self.assertFalse(AudioChunkConfigurationChange.objects.exists())

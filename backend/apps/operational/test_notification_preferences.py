from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from backend.apps.accounts.models import Role, User
from backend.common.errors import ServiceError

from .models import NotificationMode, OperationalConfiguration
from .services import OperationalService


class NotificationPreferencesTests(APITestCase):
    url = "/api/v1/configuracion-operativa"

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="preferences_admin", email="admin@example.test", password="Test-password-123",
            role=Role.ADMIN,
        )
        cls.supervisor = User.objects.create_user(
            username="preferences_supervisor", email="supervisor@example.test", password="Test-password-123",
            role=Role.SUPERVISOR,
        )

    def setUp(self):
        self.client.force_authenticate(user=self.admin)
        self.config = OperationalConfiguration.load()
        self.config.primary_email = "lista@example.test"
        self.config.backup_email = "respaldo@example.test"
        self.config.save()

    def put_ok(self, payload):
        response = self.client.put(self.url, payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.config.refresh_from_db()
        self.assertEqual(self.client.get(self.url).data["data"], response.data["data"])
        return response.data["data"]

    def assert_invalid(self, payload, fields):
        before = OperationalConfiguration.objects.get(pk=1).__dict__.copy()
        response = self.client.put(self.url, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(set(response.data["error"]["details"]["fields"]), set(fields))
        self.config.refresh_from_db()
        for field in self.config._meta.concrete_fields:
            self.assertEqual(getattr(self.config, field.attname), before[field.attname])

    def test_new_configuration_defaults(self):
        self.config.delete()
        data = self.client.get(self.url).data["data"]
        self.assertEqual(data["notification_mode"], NotificationMode.DISTRIBUTION_LIST)
        self.assertIs(data["backup_enabled"], False)
        self.assertEqual(data["primary_email"], "")
        self.assertEqual(data["backup_email"], "")
        self.assertEqual(data["enabled_days"], [0, 1, 2, 3, 4])
        self.assertEqual((data["open_time"], data["close_time"]), ("08:00", "18:00"))
        self.assertEqual(data["timezone"], "America/Santiago")

    def test_all_four_combinations_are_independent_and_persisted(self):
        for mode in NotificationMode.values:
            for enabled in (True, False):
                with self.subTest(mode=mode, backup_enabled=enabled):
                    data = self.put_ok({"notification_mode": mode, "backup_enabled": enabled})
                    self.assertEqual(data["notification_mode"], mode)
                    self.assertIs(data["backup_enabled"], enabled)
                    self.assertEqual(self.config.notification_mode, mode)
                    self.assertIs(self.config.backup_enabled, enabled)

    def test_active_destinations_require_valid_emails(self):
        for email in ("", "   ", "sin-arroba", "persona@", "a@example.test,b@example.test"):
            with self.subTest(email=email):
                self.assert_invalid({"primary_email": email}, {"primary_email"})
                self.assert_invalid(
                    {"backup_enabled": True, "backup_email": email}, {"backup_email"},
                )

    def test_only_active_destinations_validate_email_format(self):
        data = self.put_ok({
            "notification_mode": NotificationMode.ACTIVE_SUPERVISORS,
            "primary_email": "borrador", "backup_enabled": False, "backup_email": "pendiente",
        })
        self.assertEqual(data["primary_email"], "borrador")
        self.assertEqual(data["backup_email"], "pendiente")
        self.assert_invalid({"notification_mode": NotificationMode.DISTRIBUTION_LIST}, {"primary_email"})
        self.assert_invalid({"backup_enabled": True}, {"backup_email"})
        self.put_ok({"primary_email": "", "backup_email": ""})

    def test_enabling_uses_merged_state_and_reports_both_missing_emails(self):
        self.put_ok({
            "notification_mode": NotificationMode.ACTIVE_SUPERVISORS,
            "primary_email": "", "backup_email": "",
        })
        self.assert_invalid({
            "notification_mode": NotificationMode.DISTRIBUTION_LIST, "backup_enabled": True,
        }, {"primary_email", "backup_email"})
        self.put_ok({
            "notification_mode": NotificationMode.DISTRIBUTION_LIST,
            "primary_email": "lista@example.test", "backup_enabled": True,
            "backup_email": "respaldo@example.test",
        })
        self.assert_invalid({"backup_email": ""}, {"backup_email"})

    def test_switching_off_retains_addresses_for_later_reuse(self):
        self.put_ok({"backup_enabled": True})
        data = self.put_ok({"notification_mode": NotificationMode.ACTIVE_SUPERVISORS, "backup_enabled": False})
        self.assertEqual(data["primary_email"], "lista@example.test")
        self.assertEqual(data["backup_email"], "respaldo@example.test")
        self.put_ok({"notification_mode": NotificationMode.DISTRIBUTION_LIST, "backup_enabled": True})

    def test_rejects_invalid_mode_multiple_modes_types_and_unknown_fields(self):
        for mode in ("", "ambas", None, True, ["lista_distribucion", "supervisores_activos"], {}):
            with self.subTest(mode=mode):
                self.assert_invalid({"notification_mode": mode}, {"notification_mode"})
        for enabled in (None, "false", "true", 0, 1, [], {}):
            with self.subTest(backup_enabled=enabled):
                self.assert_invalid({"backup_enabled": enabled}, {"backup_enabled"})
        for field in ("primary_email", "backup_email"):
            for value in (None, True, 123, [], {}):
                with self.subTest(field=field, value=value):
                    self.assert_invalid({field: value}, {field})
            self.assert_invalid({field: "a" * 255}, {field})
        self.assert_invalid({"supervisor_ids": []}, {"supervisor_ids"})

    def test_normalizes_emails_and_accepts_old_payload_without_resetting_new_fields(self):
        self.put_ok({"notification_mode": NotificationMode.ACTIVE_SUPERVISORS, "backup_enabled": True})
        data = self.put_ok({
            "enabled_days": [4, 0, 4], "open_time": "09:00", "close_time": "17:00",
            "primary_email": "  LISTA@Example.Test  ", "backup_email": " RESPALDO@Example.Test ",
        })
        self.assertEqual(data["notification_mode"], NotificationMode.ACTIVE_SUPERVISORS)
        self.assertIs(data["backup_enabled"], True)
        self.assertEqual(data["primary_email"], "lista@example.test")
        self.assertEqual(data["backup_email"], "respaldo@example.test")
        self.assertEqual(data["enabled_days"], [0, 4])

    def test_notification_update_preserves_days_hours_and_timezone(self):
        self.config.enabled_days = [1, 3]
        self.config.open_time = "10:00"
        self.config.close_time = "16:00"
        self.config.timezone = "UTC"
        self.config.save()
        data = self.put_ok({"notification_mode": NotificationMode.ACTIVE_SUPERVISORS, "backup_enabled": True})
        self.assertEqual(data["enabled_days"], [1, 3])
        self.assertEqual((data["open_time"], data["close_time"], data["timezone"]), ("10:00", "16:00", "UTC"))
        self.assert_invalid({"timezone": "America/Lima"}, {"timezone"})

    def test_invalid_update_is_atomic_including_schedule_and_timestamp(self):
        self.assert_invalid({
            "enabled_days": [6], "open_time": "10:00", "close_time": "12:00",
            "backup_enabled": True, "backup_email": "",
        }, {"backup_email"})

    def test_invalid_first_update_does_not_create_configuration(self):
        self.config.delete()
        response = self.client.put(self.url, {"backup_enabled": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(OperationalConfiguration.objects.exists())

    def test_service_enforces_validation_without_http(self):
        with self.assertRaises(ServiceError) as error:
            OperationalService().update_config(self.admin, {"backup_enabled": True, "backup_email": ""})
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(set(error.exception.details["fields"]), {"backup_email"})
        self.config.refresh_from_db()
        self.assertFalse(self.config.backup_enabled)

    def test_unauthorized_http_and_internal_updates_do_not_write(self):
        before = self.config.updated_at
        self.admin.is_active = False
        for actor in (self.supervisor, self.admin, AnonymousUser()):
            with self.subTest(actor=actor.username):
                self.client = APIClient()
                if actor.is_authenticated:
                    self.client.force_authenticate(user=actor)
                for method in (self.client.get, self.client.put):
                    response = method(self.url, format="json")
                    self.assertEqual(response.status_code, 403 if actor.is_authenticated else 401)
                with self.assertRaises(ServiceError) as error:
                    OperationalService().update_config(actor, {"notification_mode": "supervisores_activos"})
                self.assertEqual(error.exception.status, 403)
        self.config.refresh_from_db()
        self.assertEqual(self.config.updated_at, before)

    def test_database_rejects_unknown_mode_even_without_service(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OperationalConfiguration.objects.filter(pk=1).update(notification_mode="ambas")

    def test_supervisors_mode_without_emails_preserves_capture_authorization(self):
        self.put_ok({
            "notification_mode": NotificationMode.ACTIVE_SUPERVISORS,
            "primary_email": "", "backup_enabled": False, "backup_email": "",
        })
        when = datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo("America/Santiago"))
        service = OperationalService()
        self.assertTrue(service.validate_current_operation(when)["authorized"])
        self.assertTrue(service.authorize_box_capture(3, when).authorized)

    def test_partial_schedule_update_validates_against_saved_other_bound(self):
        before = self.config.updated_at
        response = self.client.put(self.url, {"open_time": "19:00"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.config.refresh_from_db()
        self.assertEqual(self.config.open_time, "08:00")
        self.assertEqual(self.config.updated_at, before)


class NotificationPreferencesMigrationTests(TransactionTestCase):
    old_target = [("operational", "0001_initial")]
    new_target = [("operational", "0002_notification_preferences")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        self.latest_targets = executor.loader.graph.leaf_nodes()
        self.addCleanup(self.restore_schema)
        executor.migrate(self.old_target)
        self.legacy_model = executor.loader.project_state(self.old_target).apps.get_model(
            "operational", "OperationalConfiguration",
        )

    def restore_schema(self):
        MigrationExecutor(connection).migrate(self.latest_targets)

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.new_target)
        return executor.loader.project_state(self.new_target).apps.get_model(
            "operational", "OperationalConfiguration",
        )

    def test_existing_settings_preserved_and_reverse_keeps_legacy_fields(self):
        self.legacy_model.objects.create(
            pk=1, enabled_days=[1, 3], open_time="09:30", close_time="16:45",
            primary_email="LISTA@example.test", backup_email="RESPALDO@example.test", timezone="UTC",
        )
        before = self.legacy_model.objects.values().get(pk=1)
        model = self.migrate_forward()
        after = model.objects.values().get(pk=1)
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertEqual(after["notification_mode"], "lista_distribucion")
        self.assertIs(after["backup_enabled"], True)

        MigrationExecutor(connection).migrate(self.old_target)
        self.assertEqual(self.legacy_model.objects.values().get(pk=1), before)

    def test_existing_blank_emails_do_not_block_migration_or_disable_backup(self):
        self.legacy_model.objects.create(
            pk=1, enabled_days=[], open_time="", close_time="", primary_email="", backup_email="",
        )
        config = self.migrate_forward().objects.get(pk=1)
        self.assertEqual((config.primary_email, config.backup_email), ("", ""))
        self.assertEqual(config.notification_mode, "lista_distribucion")
        self.assertIs(config.backup_enabled, True)

    def test_fresh_installation_does_not_create_config_and_new_backup_defaults_off(self):
        model = self.migrate_forward()
        self.assertFalse(model.objects.exists())
        config = model.objects.create(pk=1, enabled_days=[0], open_time="08:00", close_time="18:00")
        self.assertEqual(config.notification_mode, "lista_distribucion")
        self.assertIs(config.backup_enabled, False)

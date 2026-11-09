import json
import os
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from backend.common.errors import ServiceError
from . import encryption


class EncryptionTests(SimpleTestCase):
    def test_all_backing_devices_must_be_crypt(self):
        self.assertTrue(encryption._encrypted_ancestry({'type': 'lvm', 'children': [{'type': 'crypt'}]}))
        self.assertFalse(encryption._encrypted_ancestry({'type': 'lvm', 'children': [{'type': 'crypt'}, {'type': 'disk'}]}))
        self.assertFalse(encryption._encrypted_ancestry({'type': 'disk'}))

    def test_plain_overlay_and_missing_utilities_never_count_as_encryption(self):
        with patch.object(encryption, '_json_command', return_value={'filesystems': [{'source': 'overlay'}]}):
            self.assertFalse(encryption._linux_encrypted(Path('/tmp')))
        with patch.object(encryption, '_json_command', side_effect=FileNotFoundError):
            self.assertFalse(encryption.encryption_status()['verified'])

    @override_settings(SENSITIVE_STORAGE_ENCRYPTION_REQUIRED=True)
    def test_production_ingestion_fails_closed_without_proof(self):
        with patch.object(encryption, '_CACHE', None), patch.object(encryption, 'encryption_status', return_value={'verified': False}):
            with self.assertRaises(ServiceError) as caught:
                encryption.require_encrypted_storage()
            self.assertEqual(caught.exception.code, 'ENCRYPTION_UNVERIFIED')

    @override_settings(SENSITIVE_STORAGE_ENCRYPTION_REQUIRED=True)
    def test_verified_volumes_and_keys_allow_work(self):
        with patch.object(encryption, '_CACHE', None), patch.object(encryption, 'encryption_status', return_value={'verified': True}):
            encryption.require_encrypted_storage()

    def test_key_in_repo_data_root_symlink_or_public_file_is_rejected(self):
        with TemporaryDirectory() as folder:
            key = Path(folder) / 'key'
            key.write_bytes(b'synthetic' * 8)
            self.assertFalse(encryption._key_protected(key, [folder]))
            key.chmod(0o644)
            self.assertFalse(encryption._key_protected(key, []))
            if os.name != 'nt':
                link = Path(folder) / 'link'
                link.symlink_to(key)
                self.assertFalse(encryption._key_protected(link, []))

    def test_verification_command_reports_failure_without_paths_or_key_bytes(self):
        output = StringIO()
        with patch.object(encryption, '_json_command', side_effect=OSError('PRIVATE')):
            with self.assertRaises(CommandError):
                call_command('verify_sensitive_storage', stdout=output)
        self.assertNotIn('PRIVATE', output.getvalue())
        report = json.loads(output.getvalue())
        self.assertEqual(report['code'], 'ENCRYPTION_UNVERIFIED')
        self.assertFalse(report['verified'])

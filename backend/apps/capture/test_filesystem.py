import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from .filesystem import lock_file, open_private, publish_file
from .storage import FragmentStorage


class PortableFilesystemTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_shared_allocations_coexist_but_exclude_cleanup(self):
        storage = FragmentStorage(self.root, 1024)
        with storage.allocation_lock(), storage.allocation_lock():
            with self.assertRaises(BlockingIOError):
                with storage.allocation_lock(cleanup=True):
                    self.fail("La limpieza no puede entrar durante una asignación.")
        with storage.allocation_lock(cleanup=True):
            pass

    def test_lease_excludes_another_process_and_releases_on_close(self):
        storage = FragmentStorage(self.root, 1024)
        incoming = storage.incoming()
        code = """
import os, sys
from backend.apps.capture.filesystem import lock_file, open_private
fd = open_private(sys.argv[1], os.O_RDWR)
try:
    try:
        lock_file(fd, blocking=False)
    except BlockingIOError:
        print('busy')
    else:
        print('locked')
finally:
    os.close(fd)
"""
        try:
            incoming.write(b"fixture")
            incoming.flush()
            child = subprocess.run([sys.executable, "-c", code, incoming.name],
                                   capture_output=True, text=True, check=True, timeout=10)
            self.assertEqual(child.stdout.strip(), "busy")
        finally:
            incoming.close()
        self.assertFalse(Path(incoming.name).exists())
        incoming.close()  # También lo cierra Django al finalizar el request.

        path = self.root / "released.blob"
        fd = open_private(path, os.O_RDWR | os.O_CREAT | os.O_EXCL)
        lock_file(fd)
        os.close(fd)
        child = subprocess.run([sys.executable, "-c", code, str(path)],
                               capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(child.stdout.strip(), "locked")

    def test_publication_handles_unicode_paths_and_never_replaces_a_file(self):
        source = self.root / "carga-á.part"
        destination = self.root / "fragmento-á.blob"
        source.write_bytes(b"fixture")
        publish_file(source, destination)
        self.assertEqual(destination.read_bytes(), b"fixture")
        self.assertFalse(source.exists())
        source.write_bytes(b"different")
        with self.assertRaises(OSError):
            publish_file(source, destination)
        self.assertEqual(destination.read_bytes(), b"fixture")
        self.assertEqual(source.read_bytes(), b"different")

    def test_failed_lock_never_allows_unprotected_work(self):
        with patch("backend.apps.capture.filesystem.locks.lock", return_value=False):
            with self.assertRaises(BlockingIOError):
                lock_file(1)

    def test_django_check_and_migrate_import_without_fcntl(self):
        # Reproduce el traceback original sin requerir Windows en la máquina
        # local. La matriz CI ejecuta además las pruebas sobre Windows real.
        code = """
import importlib.abc, os, sys
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.config.test_settings'
os.environ['SQLITE_PATH'] = sys.argv[1]
class NoFcntl(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'fcntl':
            raise ModuleNotFoundError("No module named 'fcntl'", name='fcntl')
sys.modules.pop('fcntl', None)
sys.meta_path.insert(0, NoFcntl())
import django
django.setup()
from django.core.management import call_command
call_command('check')
call_command('migrate', skip_checks=False, interactive=False, verbosity=0)
"""
        child = subprocess.run([sys.executable, "-c", code, str(self.root / "smoke.sqlite3")], capture_output=True,
                               text=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr)

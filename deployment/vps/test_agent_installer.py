from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


spec = spec_from_file_location("agent_installer", Path(__file__).with_name("agent-installer.py"))
installer = module_from_spec(spec)
spec.loader.exec_module(installer)


def frame(version, body=b"MZ prueba", *, name=None, digest=None, size=None):
    name = name or installer.names(version)[0]
    size = len(body) if size is None else size
    manifest = f"{digest or sha256(body).hexdigest()}  {name}\n"
    return BytesIO(f"{version}\n{size}\n{manifest}".encode("ascii") + body)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.publish("1.2.1")

    def publish(self, version, **kwargs):
        installer.operate(self.root, "receive", source=frame(version, **kwargs))

    def active(self):
        return (self.root / "current").readlink().name

    def test_activation_and_idempotent_retry(self):
        self.publish("1.3.0")
        self.assertEqual(self.active(), "1.3.0")
        previous_link = (self.root / "current").lstat().st_ino
        self.publish("1.3.0")
        self.assertEqual((self.root / "current").lstat().st_ino, previous_link)
        self.assertTrue((self.root / "1.2.1").is_dir())
        with self.assertRaisesRegex(ValueError, "otros bytes"):
            self.publish("1.3.0", body=b"MZ diferente")
        self.assertEqual(self.active(), "1.3.0")

    def test_bad_name_hash_partial_extra_and_unsafe_version_keep_current(self):
        for version, params in (
            ("1.3.0", {"name": "PsycodeAgent-Setup-1.2.1-x64.exe"}),
            ("1.3.0", {"digest": "a" * 64}),
            ("1.3.0", {"size": 1000}),
            ("1.3.0", {"size": 1}),
            ("../1.3.0", {}),
            ("1.3.0-rc.1", {}),
        ):
            with self.subTest(version=version, params=params), self.assertRaises(ValueError):
                self.publish(version, **params)
            self.assertEqual(self.active(), "1.2.1")
            self.assertFalse((self.root / "1.3.0").exists())
            self.assertFalse(list(self.root.glob(".incoming-*")))
        self.publish("1.3.0")
        self.assertEqual(self.active(), "1.3.0")

    def test_stale_retry_and_rollback_pause(self):
        self.publish("1.3.9")
        self.publish("1.3.10")
        self.publish("1.3.9")
        self.assertEqual(self.active(), "1.3.10")
        installer.operate(self.root, "rollback", "1.2.1")
        self.assertEqual(self.active(), "1.2.1")
        for version in ("1.3.10", "1.4.0"):
            with self.assertRaisesRegex(ValueError, "pausada"):
                self.publish(version)
        installer.operate(self.root, "resume")
        self.publish("1.3.9")
        self.assertEqual(self.active(), "1.2.1")
        self.publish("1.3.10")
        self.assertEqual(self.active(), "1.3.10")

    def test_corrupt_rollback_target_keeps_active_version(self):
        self.publish("1.3.0")
        (self.root / "1.2.1" / installer.names("1.2.1")[0]).write_bytes(b"rotura")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            installer.operate(self.root, "rollback", "1.2.1")
        self.assertEqual(self.active(), "1.3.0")
        self.assertFalse((self.root / installer.HOLD).exists())


if __name__ == "__main__":
    unittest.main()

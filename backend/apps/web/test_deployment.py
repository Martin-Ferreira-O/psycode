"""La interfaz del VPS debe poder publicarse sin el servidor estático de desarrollo."""
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class StaticDeploymentTests(SimpleTestCase):
    def test_login_assets_can_be_collected_for_the_reverse_proxy(self):
        self.assertTrue(settings.STATIC_ROOT)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        with TemporaryDirectory() as directory, override_settings(STATIC_ROOT=directory):
            call_command('collectstatic', interactive=False, verbosity=0, stdout=StringIO())
            for asset in ('web/js/login.js', 'web/js/solicitudes.js', 'web/css/login.css', 'web/img/logo.png'):
                with self.subTest(asset=asset):
                    self.assertTrue((Path(directory) / asset).is_file())
                    self.assertContains(response, f'/static/{asset}')

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class StaticDeploymentTests(SimpleTestCase):
    def test_react_assets_can_be_collected_for_the_reverse_proxy(self):
        self.assertTrue(settings.STATIC_ROOT)
        response = self.client.get("/")
        with TemporaryDirectory() as directory, override_settings(STATIC_ROOT=directory):
            call_command("collectstatic", interactive=False, verbosity=0, stdout=StringIO())
            root = Path(directory)
            for asset in ("web/react/app.js", "web/css/login.css", "web/css/ui.css", "web/img/logo.png"):
                with self.subTest(asset=asset):
                    self.assertTrue((root / asset).is_file(), "Ejecuta npm run build --prefix frontend antes de las pruebas.")
            self.assertTrue(list((root / "web/react/chunks").glob("Login-*.js")))
            self.assertTrue(list((root / "web/react/chunks").glob("Pcs-*.js")))
            self.assertContains(response, 'src="/static/web/react/app.js"')
            self.assertContains(response, 'href="/static/web/css/ui.css"')

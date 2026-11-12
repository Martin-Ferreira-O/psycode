"""Las plantillas deben admitir una jornada clínica completa sin cuerpo ilimitado."""
from pathlib import Path
import re

from django.conf import settings
from django.test import SimpleTestCase


class ChunkProxyLimitsTests(SimpleTestCase):
    def test_v2_proxy_limit_covers_longest_clinical_day_with_multipart_margin(self):
        # La autorización se acota al día clínico; DST puede añadir una hora.
        required = 25 * 3600 * 32000 + 2 * 65536
        for name in ("deployment/nginx-capture.conf", "deployment/vps/nginx.conf"):
            with self.subTest(config=name):
                text = (Path(settings.BASE_DIR) / name).read_text()
                location = re.search(r"location = /api/v2/internal/fragments\s*\{([^}]+)\}", text).group(1)
                value, unit = re.search(r"client_max_body_size\s+(\d+)([mg]);", location).groups()
                limit = int(value) * (1024 ** (2 if unit == "m" else 3))
                self.assertGreaterEqual(limit, required)
                self.assertIn("proxy_request_buffering off;", location)
                self.assertIn("client_max_body_size 26m;", text)

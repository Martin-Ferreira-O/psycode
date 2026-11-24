"""Las plantillas deben admitir una jornada clínica completa sin cuerpo ilimitado."""
from pathlib import Path
import re

from django.conf import settings
from django.test import SimpleTestCase


class ChunkProxyLimitsTests(SimpleTestCase):
    def test_audio_test_streams_with_the_existing_26m_limit(self):
        path = "/api/v2/internal/audio-tests/11111111-1111-4111-8111-111111111111/fragments"
        for name in ("deployment/nginx-capture.conf", "deployment/vps/nginx.conf"):
            with self.subTest(config=name):
                text = (Path(settings.BASE_DIR) / name).read_text()
                locations = re.findall(r'location ~ "([^"]+)"\s*\{([^}]+)\}', text)
                matches = [(pattern, body) for pattern, body in locations if re.fullmatch(pattern, path)]
                self.assertEqual(len(matches), 1)
                pattern, body = matches[0]
                self.assertIn("client_max_body_size 26m;", body)
                self.assertIn("proxy_request_buffering off;", body)
                self.assertNotIn("3g", body)
                self.assertIsNone(re.fullmatch(pattern, path + "/extra"))
                self.assertIsNone(re.fullmatch(pattern, path.replace("11111111-", "invalid-", 1)))

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

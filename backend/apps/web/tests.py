from django.test import SimpleTestCase
from django.urls import reverse


class FrontendShellTests(SimpleTestCase):
    def test_routes_mount_the_matching_react_page(self):
        screens = {
            "inicio": "login",
            "dashboard": "dashboard",
            "evaluaciones": "evaluaciones",
            "usuarios": "usuarios",
            "bitacora": "bitacora",
            "configuracion_operativa": "configuracion_operativa",
            "password_reset_confirm": "password_reset_confirm",
        }
        for route, page in screens.items():
            with self.subTest(route=route):
                response = self.client.get(reverse(f"web:{route}"))
                self.assertTemplateUsed(response, "web/app.html")
                self.assertContains(response, 'id="psycode-root"')
                self.assertContains(response, 'src="/static/web/react/app.js"')
                self.assertEqual(response.context["config"]["page"], page)
                self.assertNotContains(response, "SMTP_PASSWORD")

    def test_direct_links_and_token_referrer_policy_are_preserved(self):
        response = self.client.get(reverse("web:alertas"))
        self.assertRedirects(response, "/dashboard#historial-alertas", fetch_redirect_response=False)
        response = self.client.get(reverse("web:password_reset_confirm"), {"token": "token-sintetico"})
        self.assertContains(response, '<meta name="referrer" content="no-referrer">', html=True)
        self.assertNotContains(response, "token-sintetico")

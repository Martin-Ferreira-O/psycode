from django.test import SimpleTestCase
from django.urls import reverse


class OperationalConfigurationPageTests(SimpleTestCase):
    def test_page_has_operational_fields_and_keeps_form_hidden_until_role_check(self):
        response = self.client.get(reverse("web:configuracion_operativa"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Días habilitados")
        self.assertContains(response, 'name="enabled_days"')
        self.assertContains(response, 'type="time"')
        self.assertContains(response, 'type="email"')
        self.assertContains(response, "El correo de respaldo se utiliza solo")
        self.assertContains(response, 'id="contenidoConfiguracion" hidden')
        self.assertNotContains(response, "SMTP_PASSWORD")

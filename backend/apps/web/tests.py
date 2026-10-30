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

    def test_recipient_selector_options_and_guidance_texts_are_present(self):
        response = self.client.get(reverse("web:configuracion_operativa"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="notification_mode"')
        self.assertContains(response, 'value="lista_distribucion"')
        self.assertContains(response, 'value="supervisores_activos"')
        self.assertContains(
            response,
            "Las alertas se enviarán a la dirección configurada. Sus integrantes se administran fuera de Psycode",
        )
        self.assertContains(
            response,
            "Las alertas se enviarán al correo registrado de todos los supervisores habilitados, aunque no tengan una sesión iniciada",
        )
        self.assertContains(
            response,
            "Esta pantalla y sus datos están disponibles únicamente para administradores.",
        )

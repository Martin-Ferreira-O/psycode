from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from backend.apps.accounts.models import Role, User


class AdminUserManagementTests(APITestCase):
    def setUp(self):

        self.admin_user = User.objects.create_user(
            username="admin_test",
            email="admin@test.cl",
            password="Password-Segura-1234",
            role=Role.ADMIN,
            is_active=True,
        )
        refresh = RefreshToken.for_user(self.admin_user)
        self.admin_token = str(refresh.access_token)


        self.supervisor_user = User.objects.create_user(
            username="supervisor_test",
            email="supervisor@test.cl",
            password="Password-Segura-1234",
            role=Role.SUPERVISOR,
            is_active=True,
        )
        refresh_sup = RefreshToken.for_user(self.supervisor_user)
        self.supervisor_token = str(refresh_sup.access_token)

        self.url_users = "/api/v1/auth/admin/users"

    def test_creacion_usuario_por_admin(self):

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        payload = {
            "usuario": "nuevo_psicologo",
            "nombre": "Juan Perez",
            "correo": "juan@test.cl",
            "password": "Password-Segura-1234",
        }
        res = self.client.post(self.url_users, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["data"]["rol"], Role.SUPERVISOR)
        self.assertTrue(res.data["data"]["activo"])

    def test_listado_usuarios_por_admin(self):

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        res = self.client.get(self.url_users)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data["data"], list)
        self.assertGreaterEqual(len(res.data["data"]), 2)

    def test_listado_paginado_usuarios(self):
        User.objects.bulk_create(
            User(username=f"cuenta_{i}", email=f"cuenta_{i}@example.test")
            for i in range(98)
        )
        User.objects.update(date_joined=self.admin_user.date_joined)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        esperados = list(User.objects.order_by("-pk").values_list("username", flat=True))
        recibidos = []
        for offset in range(0, 100, 10):
            res = self.client.get(self.url_users, {"offset": offset})
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            data = res.data["data"]
            self.assertEqual((data["total"], data["limit"], data["offset"]), (100, 10, offset))
            self.assertEqual(len(data["items"]), 10)
            recibidos.extend(item["usuario"] for item in data["items"])
        self.assertEqual(recibidos, esperados)

        res = self.client.get(self.url_users, {"limit": 10, "offset": 100})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"], {"items": [], "total": 100, "limit": 10, "offset": 100})

    def test_rechaza_parametros_de_paginacion_invalidos(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        for query in (
            "limit=0", "limit=101", "offset=-1", "offset=2147483648", "limit=10&limit=20", "pagina=1",
            "activo=pendiente", "activo=true&activo=false",
        ):
            with self.subTest(query=query):
                res = self.client.get(f"{self.url_users}?{query}")
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        res = self.client.post(f"{self.url_users}?limit=10", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filtra_usuarios_por_estado_antes_de_paginar(self):
        User.objects.create_user(username="inactivo_antiguo", email="antiguo@example.test", is_active=False)
        User.objects.create_user(username="activo_reciente", email="activo@example.test", is_active=True)
        User.objects.create_user(username="inactivo_reciente", email="inactivo@example.test", is_active=False)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")

        for activo, total, esperado in (
            ("false", 2, "inactivo_antiguo"),
            ("true", 3, self.supervisor_user.username),
        ):
            with self.subTest(activo=activo):
                res = self.client.get(self.url_users, {"activo": activo, "limit": 1, "offset": 1})
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                data = res.data["data"]
                self.assertEqual((data["total"], data["limit"], data["offset"]), (total, 1, 1))
                self.assertEqual([item["usuario"] for item in data["items"]], [esperado])

    def test_actualizacion_usuario(self):

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        url = f"{self.url_users}/{self.supervisor_user.id}"
        payload = {
            "nombre": "Supervisor Modificado",
            "rol": Role.ADMIN,
        }
        res = self.client.patch(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["data"]["nombre"], "Supervisor Modificado")
        self.assertEqual(res.data["data"]["rol"], Role.ADMIN)

    def test_activacion_y_desactivacion_toggle(self):

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        url = f"{self.url_users}/{self.supervisor_user.id}/toggle-active"

        res = self.client.patch(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data["data"]["activo"])

        res2 = self.client.patch(url)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertTrue(res2.data["data"]["activo"])

    def test_correo_duplicado_falla(self):

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        payload = {
            "usuario": "otro_usuario",
            "nombre": "Otro Nombre",
            "correo": "supervisor@test.cl",
            "password": "Password-Segura-1234",
        }
        res = self.client.post(self.url_users, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

    def test_nombre_de_usuario_invalido_o_duplicado_tras_normalizar(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        payload = {"nombre": "Usuario QA", "correo": "nuevo@example.test", "password": "Password-Segura-1234"}
        for usuario in ("=1+1", "ｓｕｐｅｒｖｉｓｏｒ＿ｔｅｓｔ"):
            with self.subTest(usuario=usuario):
                res = self.client.post(self.url_users, {**payload, "usuario": usuario}, format="json")
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("usuario", res.data["error"]["details"]["fields"])
        self.assertEqual(User.objects.count(), 2)

    def test_permisos_insuficientes_supervisor(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.supervisor_token}")


        res_get = self.client.get(self.url_users)
        self.assertEqual(res_get.status_code, status.HTTP_403_FORBIDDEN)
        res_paginado = self.client.get(self.url_users, {"limit": 10, "offset": 0})
        self.assertEqual(res_paginado.status_code, status.HTTP_403_FORBIDDEN)


        payload = {
            "usuario": "intruso",
            "nombre": "Intruso",
            "correo": "intruso@test.cl",
            "password": "Password-Segura-1234",
        }
        res_post = self.client.post(self.url_users, payload, format="json")
        self.assertEqual(res_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_no_puede_autodesactivarse(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.admin_token}")
        url = f"{self.url_users}/{self.admin_user.id}/toggle-active"
        res = self.client.patch(url)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "VALIDATION_ERROR")

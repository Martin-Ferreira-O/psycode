from datetime import datetime, timedelta, timezone
from uuid import UUID

from django.test import SimpleTestCase

from backend.apps.alerts.domain import (
    DomainError,
    EstadoEvaluacion,
    Semaforo,
    alerta_con_evaluacion,
    alerta_nueva,
    es_revisada,
    evaluacion_nueva,
    normalizar_uuid,
    semaforo_desde_severidad,
    validar_alerta,
)

ALERTA_ID = "11111111-1111-4111-8111-111111111111"
SESION_ID = "33333333-3333-4333-8333-333333333333"
USUARIO_ID = "22222222-2222-4222-8222-222222222222"
MOMENTO = datetime(2026, 9, 12, 14, 5, 22, tzinfo=timezone.utc)


def alta(**overrides):
    datos = {
        "alerta_id": ALERTA_ID,
        "box": "box-3",
        "tipo_riesgo": "riesgo_suicida",
        "nivel_severidad": 2,
        "fecha_hora": MOMENTO,
        "sesion_id": SESION_ID,
        "origen": "datos_sinteticos",
        "descripcion": None,
        "registrada_en": MOMENTO + timedelta(seconds=1),
    }
    datos.update(overrides)
    return alerta_nueva(**datos)


class DomainTests(SimpleTestCase):
    def test_semaforo_derivado_del_anexo_a(self):
        esperado = {
            0: Semaforo.NULO,
            1: Semaforo.BAJO,
            2: Semaforo.BAJO,
            3: Semaforo.MEDIO,
            4: Semaforo.MEDIO,
            5: Semaforo.ALTO,
            6: Semaforo.ALTO,
            7: Semaforo.ALTO,
        }
        for nivel, semaforo in esperado.items():
            with self.subTest(nivel=nivel):
                self.assertEqual(semaforo_desde_severidad(nivel), semaforo)

    def test_severidad_invalida(self):
        for valor in (-1, 8, True, False, "2", 2.0):
            with self.subTest(valor=valor):
                with self.assertRaises(DomainError):
                    semaforo_desde_severidad(valor)

    def test_alta_pendiente_sin_evaluacion_y_semaforo_derivado(self):
        alerta = alta()
        self.assertEqual(alerta.semaforo, Semaforo.BAJO)
        self.assertEqual(alerta.estado_evaluacion, EstadoEvaluacion.PENDIENTE)
        self.assertIsNone(alerta.evaluacion)
        self.assertEqual(alerta.trazabilidad.registrada_en, alerta.trazabilidad.actualizada_en)
        self.assertFalse(es_revisada(alerta.estado_evaluacion))

    def test_uuid_se_normaliza_a_canonico_minusculas(self):
        alerta = alta(alerta_id="11111111-1111-4111-8111-111111111111".upper())
        self.assertEqual(alerta.alerta_id, ALERTA_ID)
        self.assertEqual(normalizar_uuid(UUID(ALERTA_ID), "alerta_id"), ALERTA_ID)

    def test_descripcion_vacia_queda_null(self):
        self.assertIsNone(alta(descripcion="   ").descripcion)

   
    def test_descripcion_normaliza_espacios(self):
        alerta = alta(descripcion="  No   quiero\nseguir\t sintiéndome   así.  ")

        self.assertEqual(alerta.descripcion,"No quiero seguir sintiéndome así.")

    def test_descripcion_normaliza_caracteres_unicode(self):
        alerta = alta(descripcion="Me siento asi\u0301")
        self.assertEqual(alerta.descripcion,"Me siento así")

    def test_descripcion_rechaza_tipo_no_texto(self):
        for valor in (123, True, ["texto"], {"texto": "ejemplo"}):
            with self.subTest(valor=valor):
                with self.assertRaises(DomainError):
                    alta(descripcion=valor)

    def test_descripcion_acepta_exactamente_500_caracteres(self):
        descripcion = "x" * 500

        alerta = alta(descripcion=descripcion)

        self.assertEqual(alerta.descripcion, descripcion)

    def test_limites_de_campos(self):
        with self.assertRaises(DomainError):
            alta(box="")
        with self.assertRaises(DomainError):
            alta(box="x" * 65)
        with self.assertRaises(DomainError):
            alta(descripcion="x" * 501)
        with self.assertRaises(DomainError):
            alta(alerta_id="no-es-uuid")
        with self.assertRaises(DomainError):
            alta(fecha_hora=datetime(2026, 9, 12, 14, 5, 22))

    def test_evaluacion_registra_autor_y_cambia_estado(self):
        alerta = alta()
        evaluacion = evaluacion_nueva(
            alerta_id=ALERTA_ID,
            resultado="correcta",
            usuario_id=USUARIO_ID,
            usuario="psicologo",
            fecha_hora=datetime(2026, 9, 12, 15, 10, tzinfo=timezone.utc),
        )
        revisada = alerta_con_evaluacion(alerta, evaluacion, evaluacion.fecha_hora)
        self.assertEqual(revisada.estado_evaluacion, EstadoEvaluacion.CORRECTA)
        self.assertEqual(revisada.evaluacion.usuario_id, USUARIO_ID)
        self.assertTrue(es_revisada(revisada.estado_evaluacion))
        self.assertEqual(revisada.semaforo, Semaforo.BAJO)
        self.assertEqual(revisada.fecha_hora, MOMENTO)

    def test_no_permite_reevaluar_ni_pendiente_como_resultado(self):
        alerta = alta()
        evaluacion = evaluacion_nueva(
            alerta_id=ALERTA_ID,
            resultado=EstadoEvaluacion.NEUTRO,
            usuario_id=USUARIO_ID,
            usuario="psicologo",
            fecha_hora=datetime(2026, 9, 12, 15, 10, tzinfo=timezone.utc),
        )
        revisada = alerta_con_evaluacion(alerta, evaluacion, evaluacion.fecha_hora)
        with self.assertRaises(DomainError):
            alerta_con_evaluacion(revisada, evaluacion, evaluacion.fecha_hora)
        with self.assertRaises(DomainError):
            evaluacion_nueva(
                alerta_id=ALERTA_ID,
                resultado="pendiente",
                usuario_id=USUARIO_ID,
                usuario="psicologo",
                fecha_hora=evaluacion.fecha_hora,
            )

    def test_invariante_semaforo_y_evaluacion_incrustada(self):
        alerta = alta()
        campos = {campo: getattr(alerta, campo) for campo in alerta.__slots__}
        contradictoria = alerta.__class__(**{**campos, "semaforo": Semaforo.ALTO})
        with self.assertRaises(DomainError):
            validar_alerta(contradictoria)
        evaluacion_ajena = evaluacion_nueva(
            alerta_id=SESION_ID,
            resultado="correcta",
            usuario_id=USUARIO_ID,
            usuario="psicologo",
            fecha_hora=datetime(2026, 9, 12, 15, 10, tzinfo=timezone.utc),
        )
        with self.assertRaises(DomainError):
            alerta_con_evaluacion(alerta, evaluacion_ajena, evaluacion_ajena.fecha_hora)

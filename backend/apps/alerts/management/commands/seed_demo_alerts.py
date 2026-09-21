import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backend.apps.alerts.demo import DEMO_ALERTA_IDS, DEMO_ALERTS, EVALUADOR_ID, EVALUADOR_USUARIO, ORIGEN
from backend.apps.alerts.documents import CAMPOS_ALERTA, CAMPOS_PROHIBIDOS, alerta_a_documento
from backend.apps.alerts.exceptions import AlertAlreadyExists, EvaluationAlreadyRegistered
from backend.apps.alerts.mongo import close_client, ping
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.common.errors import PersistenceUnavailable


class Command(BaseCommand):
    help = "Crea cinco alertas sintéticas locales y verifica que se puedan consultar."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Elimina las alertas de prueba y las vuelve a crear.")

    def handle(self, *args, **options):
        logging.getLogger("psycode.audit").setLevel(logging.WARNING)
        if not settings.DEBUG:
            raise CommandError("Las alertas de prueba solo se permiten con DJANGO_DEBUG=true.")
        if not settings.MONGODB_URI:
            raise CommandError("Configura MONGODB_URI. Ejemplo local en .env.example.")
        try:
            ping()
        except PersistenceUnavailable:
            close_client()
            raise CommandError("No se pudo conectar a MongoDB. Revisa MONGODB_URI y que el servidor esté en ejecución.") from None
        store = AlertsRepository()
        try:
            store.ensure_schema()
        except PersistenceUnavailable:
            close_client()
            raise CommandError("MongoDB no aceptó el esquema de alertas.") from None
        if options["reset"]:
            self._reset(store)
        service = AlertsService(store)
        creadas = 0
        existentes = 0
        for spec in DEMO_ALERTS:
            try:
                service.register_alert(
                    alerta_id=spec["alerta_id"],
                    box=spec["box"],
                    tipo_riesgo=spec["tipo_riesgo"],
                    nivel_severidad=spec["nivel_severidad"],
                    fecha_hora=spec["fecha_hora"],
                    sesion_id=spec["sesion_id"],
                    origen=ORIGEN,
                    descripcion=spec["descripcion"],
                )
                creadas += 1
            except AlertAlreadyExists:
                existentes += 1
            if spec["evaluacion"] is not None:
                try:
                    service.record_evaluation(
                        spec["alerta_id"],
                        spec["evaluacion"],
                        EVALUADOR_ID,
                        EVALUADOR_USUARIO,
                    )
                except EvaluationAlreadyRegistered:
                    pass
        self._verificar(store)
        self.stdout.write(
            self.style.SUCCESS(
                f"Alertas de prueba listas: {len(DEMO_ALERTS)} consultadas, {creadas} nuevas, {existentes} ya existían."
            )
        )

    def _reset(self, store):
        db = store._db()
        db["alerts"].delete_many({"alerta_id": {"$in": list(DEMO_ALERTA_IDS)}})
        db["audit_events"].delete_many({"alerta_id": {"$in": list(DEMO_ALERTA_IDS)}})
        self.stdout.write("Alertas de prueba anteriores eliminadas.")

    def _verificar(self, store):
        boxes, tipos, niveles, estados = set(), set(), set(), set()
        for spec in DEMO_ALERTS:
            alerta = store.get_alert(spec["alerta_id"])
            persistido = alerta_a_documento(alerta)
            if CAMPOS_PROHIBIDOS.intersection(persistido) or set(persistido) - set(CAMPOS_ALERTA):
                raise CommandError("Una alerta de prueba incluye un campo prohibido o no declarado.")
            if alerta.box != spec["box"] or alerta.nivel_severidad != spec["nivel_severidad"]:
                raise CommandError(f"La alerta {spec['alerta_id']} no conservó box o severidad.")
            if spec["evaluacion"] is None:
                if alerta.evaluacion is not None:
                    raise CommandError(f"La alerta {spec['alerta_id']} no debía tener evaluación.")
            elif alerta.evaluacion is None or alerta.evaluacion.evaluacion != spec["evaluacion"]:
                raise CommandError(f"La alerta {spec['alerta_id']} no conservó la evaluación.")
            boxes.add(alerta.box)
            tipos.add(alerta.tipo_riesgo)
            niveles.add(alerta.nivel_severidad)
            estados.add(str(alerta.estado_evaluacion))
        if len(boxes) < 2 or len(tipos) < 2 or len(niveles) < 2 or len(estados) < 2:
            raise CommandError("Las alertas de prueba no cubren la variedad exigida.")

from django.utils import timezone

from backend.common.errors import PersistenceUnavailable, ServiceError

from .domain import DomainError, alerta_nueva, evaluacion_nueva, normalizar_uuid
from .exceptions import AlertAlreadyExists, AlertNotFound, EvaluationAlreadyRegistered


class AlertsService:
    def __init__(self, store, notifier=None):
        self.store = store
        self.notifier = notifier

    def register_alert(
        self,
        *,
        alerta_id,
        box,
        tipo_riesgo,
        nivel_severidad,
        fecha_hora,
        sesion_id,
        origen,
        descripcion=None,
        analisis=None,
        before_notify=None,
    ):
        try:
            alerta = alerta_nueva(
                alerta_id=alerta_id,
                box=box,
                tipo_riesgo=tipo_riesgo,
                nivel_severidad=nivel_severidad,
                fecha_hora=fecha_hora,
                sesion_id=sesion_id,
                origen=origen,
                descripcion=descripcion,
                analisis=analisis,
                registrada_en=timezone.now(),
            )
        except DomainError as exc:
            raise ServiceError("VALIDATION_ERROR", str(exc), 400) from exc
        try:
            stored = self.store.insert_alert(alerta)
        except AlertAlreadyExists:
            if before_notify is None:
                raise
            stored = self.store.get_alert(alerta_id)
            self.store.ensure_registration_audit(stored)

        if self.notifier is not None and (before_notify is None or before_notify(stored.alerta_id)):
            from backend.apps.notifications.domain import NotificationPayload
            try:
                notification = self.notifier.notify_alert(stored.alerta_id, NotificationPayload(
                    str(stored.semaforo), "riesgo_suicida", stored.box, stored.fecha_hora.isoformat(),
                    es_prueba=stored.es_prueba))
            except Exception:
                if before_notify is not None:
                    raise
                self.store._audit("alerts.flow", "failure", alerta_id=stored.alerta_id,
                                  sesion_id=stored.sesion_id, error_code="NOTIFICATION_INTERNAL_ERROR")
            else:
                if before_notify is not None and notification.motivo_omision == "ALERTA_NO_ALMACENADA":
                    raise PersistenceUnavailable()
        return stored

    def get_alert(self, alerta_id):
        try:
            ident = normalizar_uuid(alerta_id, "alerta_id")
        except DomainError as exc:
            raise ServiceError("VALIDATION_ERROR", str(exc), 400) from exc
        try:
            return self.store.get_alert(ident)
        except AlertNotFound:
            raise
        except PersistenceUnavailable:
            raise

    def list_alerts(self, filters):
        try:
            return self.store.list_alerts(filters)
        except PersistenceUnavailable:
            raise

    def record_evaluation(self, alerta_id, resultado, usuario_id, usuario):
        try:
            ident = normalizar_uuid(alerta_id, "alerta_id")
            evaluacion = evaluacion_nueva(
                alerta_id=ident,
                resultado=resultado,
                usuario_id=usuario_id,
                usuario=usuario,
                fecha_hora=timezone.now(),
            )
        except DomainError as exc:
            raise ServiceError("VALIDATION_ERROR", str(exc), 400) from exc
        try:
            return self.store.record_evaluation(ident, evaluacion)
        except (AlertNotFound, EvaluationAlreadyRegistered, PersistenceUnavailable):
            raise

"""Casos de uso internos de persistencia. Sin HTTP público de alta de alertas."""

from django.utils import timezone

from backend.common.errors import PersistenceUnavailable, ServiceError

from .domain import DomainError, alerta_nueva, evaluacion_nueva, normalizar_uuid
from .exceptions import AlertAlreadyExists, AlertNotFound, EvaluationAlreadyRegistered


class AlertsService:
    def __init__(self, store):
        self.store = store

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
                registrada_en=timezone.now(),
            )
        except DomainError as exc:
            raise ServiceError("VALIDATION_ERROR", str(exc), 400) from exc
        try:
            return self.store.insert_alert(alerta)
        except AlertAlreadyExists:
            raise
        except PersistenceUnavailable:
            raise

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

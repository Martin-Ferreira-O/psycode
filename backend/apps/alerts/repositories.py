"""Persistencia PyMongo de alertas y bitácora. Sin tipos HTTP ni ObjectId en la API del puerto."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.common.audit import AuditWriter
from backend.common.errors import PersistenceUnavailable

from .documents import alerta_a_documento, documento_a_alerta, evaluacion_a_documento
from .domain import Alerta, DomainError, Evaluacion, EstadoEvaluacion, normalizar_uuid, validar_alerta
from .exceptions import AlertAlreadyExists, AlertNotFound, EvaluationAlreadyRegistered
from .mongo import schema_path
from .ports import AlertQueryFilters, AlertQueryPort, AlertWritePort


class AlertsRepository(AlertWritePort, AlertQueryPort):
    def __init__(self, database=None):
        self._injected = database
        self._schema_ready = False

    def _db(self):
        if self._injected is not None:
            return self._injected
        from .mongo import get_database
        return get_database()

    def _alerts(self):
        self.ensure_schema()
        return self._db()["alerts"]

    def _events(self):
        self.ensure_schema()
        return self._db()["audit_events"]

    def ensure_schema(self):
        if self._schema_ready:
            return
        try:
            db = self._db()
            self._apply_collection(db, "alerts.validator.json", "alerts.indexes.json")
            self._apply_collection(db, "audit_events.validator.json", "audit_events.indexes.json")
        except PersistenceUnavailable:
            raise
        except PyMongoError:
            raise PersistenceUnavailable() from None
        self._schema_ready = True

    def _apply_collection(self, db, validator_file, indexes_file):
        spec = json.loads(schema_path(validator_file).read_text(encoding="utf-8"))
        name = spec["collection"]
        if name not in db.list_collection_names():
            db.create_collection(
                name,
                validator=spec["validator"],
                validationLevel=spec["validationLevel"],
                validationAction=spec["validationAction"],
            )
        else:
            db.command(
                {
                    "collMod": name,
                    "validator": spec["validator"],
                    "validationLevel": spec["validationLevel"],
                    "validationAction": spec["validationAction"],
                }
            )
        indexes = json.loads(schema_path(indexes_file).read_text(encoding="utf-8"))
        collection = db[name]
        for item in indexes["indexes"]:
            collection.create_index(list(item["keys"].items()), **item["options"])

    def insert_alert(self, alert: Alerta) -> Alerta:
        validar_alerta(alert)
        if alert.evaluacion is not None or alert.estado_evaluacion != EstadoEvaluacion.PENDIENTE:
            raise DomainError("El alta solo persiste alertas pendientes, sin evaluación.")
        documento = alerta_a_documento(alert)
        try:
            self._alerts().insert_one(documento)
        except DuplicateKeyError:
            raise AlertAlreadyExists(alert.alerta_id) from None
        except PyMongoError:
            raise PersistenceUnavailable() from None
        self._audit("alerts.register", "success", alerta_id=alert.alerta_id)
        return alert

    def get_alert(self, alerta_id: str) -> Alerta:
        ident = normalizar_uuid(alerta_id, "alerta_id")
        try:
            documento = self._alerts().find_one({"alerta_id": ident}, {"_id": 0})
        except PyMongoError:
            raise PersistenceUnavailable() from None
        if documento is None:
            raise AlertNotFound(ident)
        return documento_a_alerta(documento)

    def list_alerts(self, filters: AlertQueryFilters) -> tuple[list[Alerta], int]:
        query: dict[str, any] = {}

        if filters.box:
            query["box"] = filters.box

        if filters.estado_evaluacion:
            query["estado_evaluacion"] = filters.estado_evaluacion

        if filters.revisadas is not None:
            if filters.revisadas:
                query["estado_evaluacion"] = {"$ne": EstadoEvaluacion.PENDIENTE.value}
            else:
                query["estado_evaluacion"] = EstadoEvaluacion.PENDIENTE.value

        fecha_cond: dict[str, any] = {}
        if filters.fecha_desde_utc:
            fecha_cond["$gte"] = filters.fecha_desde_utc
        if filters.fecha_hasta_utc:
            fecha_cond["$lt"] = filters.fecha_hasta_utc
        if fecha_cond:
            query["fecha_hora"] = fecha_cond

        if filters.q:
            import re
            patron = {"$regex": re.escape(filters.q.strip()), "$options": "i"}
            query["$or"] = [
                {"alerta_id": patron},
                {"box": patron},
                {"tipo_riesgo": patron},
            ]

        try:
            col = self._alerts()
            total = col.count_documents(query)
            cursor = (
                col.find(query, {"_id": 0})
                .sort([("fecha_hora", -1), ("alerta_id", 1)])
                .skip(filters.offset)
                .limit(filters.limit)
            )
            documentos = list(cursor)
        except PyMongoError:
            raise PersistenceUnavailable() from None

        return [documento_a_alerta(doc) for doc in documentos], total

    def record_evaluation(self, alerta_id: str, evaluation: Evaluacion) -> Evaluacion:
        ident = normalizar_uuid(alerta_id, "alerta_id")
        if evaluation.alerta_id != ident:
            raise DomainError("La evaluación debe referir el mismo alerta_id.")
        payload = evaluacion_a_documento(evaluation)
        try:
            resultado = self._alerts().update_one(
                {"alerta_id": ident, "estado_evaluacion": EstadoEvaluacion.PENDIENTE.value},
                {
                    "$set": {
                        "evaluacion": payload,
                        "estado_evaluacion": payload["evaluacion"],
                        "trazabilidad.actualizada_en": evaluation.fecha_hora,
                    }
                },
            )
        except PyMongoError:
            raise PersistenceUnavailable() from None
        if resultado.matched_count == 1:
            self._audit(
                "alerts.evaluate",
                "success",
                alerta_id=ident,
                actor_id=evaluation.usuario_id,
            )
            return evaluation
        try:
            existente = self._alerts().find_one({"alerta_id": ident}, {"_id": 1})
        except PyMongoError:
            raise PersistenceUnavailable() from None
        if existente is None:
            raise AlertNotFound(ident)
        raise EvaluationAlreadyRegistered(ident)

    def _audit(self, action, outcome, *, alerta_id, actor_id=None, error_code=None):
        AuditWriter.record(action, outcome, actor_id=actor_id, error_code=error_code, alerta_id=alerta_id)
        evento = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc),
            "action": action,
            "outcome": outcome,
            "actor_id": actor_id,
            "alerta_id": alerta_id,
            "channel": None,
            "contingencia": None,
            "motivo": None,
            "error_code": error_code,
            "duration_ms": None,
            "intentos": [],
        }
        try:
            self._events().insert_one(evento)
        except PyMongoError:
            logging.getLogger("psycode.audit").error(
                '{"action":"audit_events.write","outcome":"failure","alerta_id":"%s"}',
                alerta_id,
            )

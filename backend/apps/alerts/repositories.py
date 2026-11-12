"""Persistencia PyMongo de alertas y bitácora. Sin tipos HTTP ni ObjectId en la API del puerto."""

from __future__ import annotations

import json
import re

from pymongo.errors import DuplicateKeyError, PyMongoError

from .audit import AlertAudit, STORAGE_AUDIT_COUNTS, STORAGE_PROVIDER_AUDIT_COUNTS
from backend.common.errors import PersistenceUnavailable

from .documents import alerta_a_documento, documento_a_alerta, evaluacion_a_documento
from .domain import Alerta, DomainError, Evaluacion, EstadoEvaluacion, ORIGEN_PRUEBA_AUDIO, normalizar_uuid, validar_alerta
from .exceptions import AlertAlreadyExists, AlertNotFound, EvaluationAlreadyRegistered
from .mongo import ensure_alert_schema, schema_path
from .ports import AlertQueryFilters, AlertQueryPort, AlertWritePort


# Etiquetas de utils.js que representan códigos distintos del texto visible.
RISK_LABEL_ALIASES = {
    "Riesgo suicida": (
        "sin_ideacion_identificable",
        "deseo_pasivo_de_muerte",
        "ideacion_activa",
        "consideracion_de_metodo",
        "conducta_suicida",
    ),
    "Vulneración de derechos": ("vulneracion_derechos",),
    "Vulneracion de derechos": ("vulneracion_derechos",),
}


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
        return self.ensure_schema()["alerts"]

    def _events(self):
        return self.ensure_schema()["audit_events"]

    def ensure_schema(self):
        try:
            if self._injected is None:
                return ensure_alert_schema(self._apply_schema)
            if not self._schema_ready:
                self._apply_schema(self._injected)
                self._schema_ready = True
            return self._injected
        except PersistenceUnavailable:
            raise
        except PyMongoError:
            raise PersistenceUnavailable() from None

    def _apply_schema(self, db):
        self._apply_collection(db, "alerts.validator.json", "alerts.indexes.json")
        self._apply_collection(db, "audit_events.validator.json", "audit_events.indexes.json")

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
        self._audit("alerts.register", "success", alerta_id=alert.alerta_id, sesion_id=alert.sesion_id)
        return alert

    def has_alert_event(self, alerta_id, action):
        try:
            return self._events().find_one({"alerta_id": alerta_id, "action": action}, {"_id": 1}) is not None
        except PyMongoError:
            raise PersistenceUnavailable() from None

    def ensure_registration_audit(self, alert):
        if not self.has_alert_event(alert.alerta_id, "alerts.register"):
            self._audit("alerts.register", "success", alerta_id=alert.alerta_id, sesion_id=alert.sesion_id)

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

        estados = []
        if filters.estado_evaluacion:
            estados.append({"estado_evaluacion": filters.estado_evaluacion})
        if filters.revisadas is not None:
            estados.append({"estado_evaluacion": (
                {"$ne": EstadoEvaluacion.PENDIENTE.value}
                if filters.revisadas else EstadoEvaluacion.PENDIENTE.value
            )})
        if len(estados) == 1:
            query.update(estados[0])
        elif estados:
            query["$and"] = estados
        if filters.registro_evaluaciones:
            query.setdefault("$and", []).append({"$or": [
                {"estado_evaluacion": {"$ne": EstadoEvaluacion.PENDIENTE.value}},
                {"trazabilidad.origen": ORIGEN_PRUEBA_AUDIO},
            ]})
        else:
            query["trazabilidad.origen"] = {"$ne": ORIGEN_PRUEBA_AUDIO}

        fecha_cond: dict[str, any] = {}
        if filters.fecha_desde_utc:
            fecha_cond["$gte"] = filters.fecha_desde_utc
        if filters.fecha_hasta_utc:
            fecha_cond["$lt"] = filters.fecha_hasta_utc
        if fecha_cond:
            query["fecha_hora"] = fecha_cond

        if filters.q:
            text = filters.q.strip()
            separator = r"[\s_-]+"
            words_pattern = separator.join(re.escape(word) for word in re.split(separator, text))
            box_pattern = words_pattern
            box_number = re.fullmatch(r"box[\s_-]+0*([0-9]+)", text, re.IGNORECASE)
            if box_number:
                box_pattern = rf"box{separator}0*{box_number[1]}"

            query["$or"] = [
                {"alerta_id": {"$regex": re.escape(text), "$options": "i"}},
                {"box": {"$regex": box_pattern, "$options": "i"}},
                {"tipo_riesgo": {"$regex": words_pattern, "$options": "i"}},
            ]
            matching_aliases = sorted({
                code
                for label, codes in RISK_LABEL_ALIASES.items()
                if re.search(words_pattern, label, re.IGNORECASE)
                for code in codes
            })
            if matching_aliases:
                aliases_pattern = "^(?:" + "|".join(matching_aliases) + ")$"
                query["$or"].append({"tipo_riesgo": {"$regex": aliases_pattern, "$options": "i"}})

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

    def _audit(self, action, outcome, **metadata):
        return AlertAudit(self._events).record(action, outcome, **metadata)

    def list_events(self, filters):
        query = {}
        for field in ("alerta_id", "action", "outcome"):
            if filters.get(field) is not None:
                query[field] = filters[field]
        if query.get("action") in (None, "storage.cleanup"):
            query["$nor"] = [{
                "action": "storage.cleanup",
                "outcome": "success",
                "error_code": {"$in": [None, ""]},
                "storage.source": "automatic",
                **{f"storage.{name}": 0 for name in STORAGE_AUDIT_COUNTS},
                **{f"storage.{name}": {"$in": [0, None]} for name in STORAGE_PROVIDER_AUDIT_COUNTS},
            }]
        period = {}
        if filters.get("fecha_desde"):
            period["$gte"] = filters["fecha_desde"]
        if filters.get("fecha_hasta"):
            period["$lte"] = filters["fecha_hasta"]
        if period:
            query["timestamp"] = period
        direction = 1 if filters["order"] == "asc" else -1
        try:
            col = self._events()
            total = col.count_documents(query)
            items = list(col.find(query, {"_id": 0}).sort(
                [("timestamp", direction), ("event_id", direction)]
            ).skip(filters["offset"]).limit(filters["limit"]))
            return items, total
        except PyMongoError:
            raise PersistenceUnavailable() from None

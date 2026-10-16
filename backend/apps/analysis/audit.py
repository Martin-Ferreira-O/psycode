"""Conexión a la bitácora: exclusivamente códigos permitidos, sin excepciones libres."""
from datetime import datetime, timezone
import logging
from uuid import uuid4
from backend.common.audit import AuditWriter

FAILURE_CODES = frozenset({"SPEECHMATICS_FAILED", "SPEECHMATICS_DELETE_PENDING",
                           "JEV_FAILED", "JEV_SUBMISSION_UNCERTAIN"})


class AnalysisAudit:
    def __init__(self, events):
        self.events = events

    def failure(self, code):
        if code not in FAILURE_CODES:
            raise ValueError("Código técnico no permitido")
        action = "analysis.speechmatics" if code.startswith("SPEECHMATICS") else "analysis.jev"
        AuditWriter.record(action, "failure", error_code=code)
        event = {"event_id": str(uuid4()), "timestamp": datetime.now(timezone.utc),
                 "action": action, "outcome": "failure", "actor_id": None,
                 "alerta_id": None, "channel": None, "contingencia": None,
                 "motivo": None, "error_code": code, "duration_ms": None, "intentos": []}
        try:
            self.events().insert_one(event)
        except Exception:
            # La caída de la propia bitácora también debe dejar rastro, sin cuerpos.
            logging.getLogger("psycode.audit").error(
                '{"action":"audit_events.write","outcome":"failure","error_code":"ANALYSIS_AUDIT_UNAVAILABLE"}')

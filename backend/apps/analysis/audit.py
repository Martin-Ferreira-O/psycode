"""Fallos de integración sin texto libre ni respuestas de proveedores."""
from backend.apps.alerts.audit import AlertAudit

FAILURE_CODES = frozenset({"SPEECHMATICS_FAILED", "SPEECHMATICS_DELETE_PENDING",
                           "JEV_FAILED", "JEV_SUBMISSION_UNCERTAIN", "SPEECHMATICS_UNCERTAIN", "ANALYSIS_CONTEXT_LOST", "NOTIFICATION_UNCERTAIN",
                           "FLOW_INTERRUPTED", "ALERT_PERSISTENCE_FAILED"})


class AnalysisAudit:
    def __init__(self, events):
        self.trail = AlertAudit(events)

    def failure(self, code, *, alerta_id=None, sesion_id=None, sequence=None):
        if code not in FAILURE_CODES:
            raise ValueError("Código técnico no permitido")
        action = ("analysis.speechmatics" if code.startswith("SPEECHMATICS") else
                  "analysis.jev" if code.startswith("JEV") else "alerts.flow")
        return self.trail.record(action, "failure", error_code=code,
                                 alerta_id=alerta_id, sesion_id=sesion_id, sequence=sequence)

    def recovery(self, *, sesion_id=None, sequence=None):
        return self.trail.record(
            "alerts.flow",
            "success",
            sesion_id=sesion_id,
            sequence=sequence,
        )

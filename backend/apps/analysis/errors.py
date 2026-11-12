"""Errores técnicos internos, sin cuerpos de proveedor."""
class ProviderError(RuntimeError):
    pass


class AnalysisRetry(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SubmissionUncertain(ProviderError):
    """A POST may have been accepted. Do not create another job automatically."""


class JevContextLimit(ProviderError):
    """Bloque completo fuera de la cota operacional o rechazado por contexto."""

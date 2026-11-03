"""Errores técnicos internos, sin cuerpos de proveedor."""
class ProviderError(RuntimeError):
    pass


class SubmissionUncertain(ProviderError):
    """A POST may have been accepted. Do not create another job automatically."""

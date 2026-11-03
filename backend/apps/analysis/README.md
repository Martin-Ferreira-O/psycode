# Análisis interno

Integra Speechmatics Batch y JEV mediante puertos propios, sin endpoints nuevos. La composición está en `backend.config.composition.analysis_worker`; el punto de entrada del trabajador es `AnalysisService.process(Fragment, roles=...)`.

- `domain.py`: entrada PCM y salida tipada 1.0.
- `ports.py`: transcriptor, analizador, bitácora y reserva de fragmentos.
- `clients.py`, `providers/`: adaptadores HTTP, preguntas versionadas y validación.
- `rules.py`, `matrix.json`, `privacy.py`: reglas seleccionadas del origen y redacción.
- `services.py`: contexto por sesión y registro interno de alertas.
- `ledger.py`: rechazo durable de duplicados y secuencias incorrectas.
- `audit.py`: fallos técnicos en la bitácora existente.

Ver [implementación y pruebas](../../../docs/INTEGRACION-SPEECHMATICS-JEV.md) y [contrato 1.0](../../../docs/analysis/OUTPUT-1.0.md). El módulo no arranca procesos, realiza llamadas ni consume créditos al importarse o construirse.

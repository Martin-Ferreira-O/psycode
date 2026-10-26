
"""Ejecucion local de ordenes SCRUM-71 dentro del agente SCRUM-72."""

import threading
from datetime import datetime, timezone

from backend.apps.capture.domain import Command

from .capture_runner import CaptureRunner
from .obs_controller import OBSController


class SessionCoordinator:
    """
    Coordina OBS y CaptureRunner.

    control: adaptador compatible con BoxAgentControl.
    En pruebas se utiliza un simulador.
    El transporte remoto se conectara cuando este disponible.
    """

    def __init__(
        self,
        config,
        control,
        controller=None,
        runner_factory=CaptureRunner,
        stop_timeout=60,
        journal=None,
    ):
        self.config = config
        self.control = control
        self.controller = controller or OBSController(config)
        self.runner_factory = runner_factory
        self.stop_timeout = stop_timeout
        self.journal = journal

        self.session_id = None
        self.runner = None
        self.thread = None
        self.capture_error = None
        self._interruption_reported = False

        self._start_command_id = None
        self._stop_confirmation = None
        self._completed_commands = {}
        self._pending_start = None

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)


    def inspect_recovery(self, command: Command):
        """Inspecciona una orden persistida y el estado actual de OBS."""

        if not isinstance(command, Command):
            raise TypeError("Se esperaba un Command de SCRUM-71")

        if command.box != self.config.box_id:
            raise ValueError("La orden pertenece a otro box")

        if self.journal is None:
            raise RuntimeError("No existe un registro persistente configurado")

        if self.session_id is not None:
            raise RuntimeError("No se puede recuperar con una sesion activa")

        saved = self.journal.get(command.command_id)

        if saved is None:
            return None

        if (
            saved["session_id"] != str(command.session_id)
            or saved["box"] != command.box
            or saved["kind"] != command.kind
        ):
            raise ValueError("Los datos de la orden no coinciden")

        if saved["state"] not in ("prepared", "executed", "acknowledged"):
            raise ValueError("Estado persistido desconocido")

        try:
            self.controller.connect()
            obs_status = self.controller.status()
        finally:
            self.controller.disconnect()

        return {
            "command_id": command.command_id,
            "session_id": command.session_id,
            "kind": command.kind,
            "journal_state": saved["state"],
            "occurred_at": saved["occurred_at"],
            "last_sequence": saved["last_sequence"],
            "recording": obs_status["recording"],
            "streaming": obs_status["streaming"],
            "requires_reconciliation": True,
        }


    def handle_command(self, command: Command):
        """Ejecuta una orden previamente recibida del backend."""

        if not isinstance(command, Command):
            raise TypeError("Se esperaba un Command de SCRUM-71")

        if command.box != self.config.box_id:
            raise ValueError("La orden pertenece a otro box")

        if command.command_id in self._completed_commands:
            return self._completed_commands[command.command_id]

        if command.kind == "inicio":
            return self._start(command)

        if command.kind == "detencion":
            if self.session_id is None and self.journal is not None:
                saved = self.journal.get(command.command_id)

                if saved is not None and saved["state"] in (
                    "executed",
                    "acknowledged",
                ):
                    # Recuperar la detencion sin volver a ejecutar OBS.
                    return self.recover_stop_confirmation(command)

            return self._stop(command)


        raise ValueError("Tipo de orden desconocido")

    def _start(self, command):
        """Inicia OBS una sola vez y recupera confirmaciones pendientes."""

        if self.session_id is not None:
            raise RuntimeError("Ya existe una sesion en el agente")

        # Verificar si OBS ya fue iniciado para esta orden.
        if self._pending_start is not None:
            pending_id, pending_session, started_at, runner = (
                self._pending_start
            )

            if (
                pending_id != command.command_id
                or pending_session != command.session_id
            ):
                raise RuntimeError(
                    "Existe otra orden de inicio pendiente de confirmacion"
                )

        else:
            now = self._now()

            if not command.scheduled_start <= now < command.scheduled_end:
                raise RuntimeError(
                    "Inicio fuera de la ventana autorizada"
                )

            # Registrar la orden antes de ejecutar OBS.
            if self.journal is not None:
                existing = self.journal.get(command.command_id)

                if existing is not None:
                    # Evitar repetir una orden recuperada sin verificar OBS.
                    raise RuntimeError(
                        "Orden recuperada del disco: requiere "
                        "reconciliar el estado de OBS antes de continuar"
                    )

                self.journal.prepare(command)

            runner = self.runner_factory(self.config)

            try:
                self.controller.connect()
                self.controller.start_capture()

            except Exception:
                try:
                    self.control.acknowledge(
                        self.config.box_id,
                        command.command_id,
                        success=False,
                        error_code="AGENT_START_FAILED",
                        occurred_at=self._now(),
                    )
                finally:
                    self.controller.disconnect()

                raise

            started_at = self._now()

            # Conservar el inicio para evitar repetir OBS ante un timeout.
            self._pending_start = (
                command.command_id,
                command.session_id,
                started_at,
                runner,
            )

        # Registrar la ejecucion antes de confirmar al backend.
        if self.journal is not None:
            self.journal.mark_executed(
                command,
                occurred_at=started_at,
            )

        # Confirmar el inicio con SCRUM-71.
        self.control.acknowledge(
            self.config.box_id,
            command.command_id,
            success=True,
            occurred_at=started_at,
        )

        # Guardar la confirmacion en el registro persistente.
        if self.journal is not None:
            self.journal.mark_acknowledged(command)

        self._pending_start = None

        self.session_id = command.session_id
        self._start_command_id = command.command_id
        self.runner = runner
        self.capture_error = None
        self._interruption_reported = False

        def capture_task():
            try:
                self.runner.run(
                    session_id=command.session_id,
                    captured_at_start=started_at,
                )

            except Exception as exc:
                self.capture_error = exc

                # Comunicar solamente un codigo tecnico.
                try:
                    self.control.interrupted(
                        self.config.box_id,
                        command.session_id,
                        error_code="AGENT_INTERRUPTED",
                    )

                except Exception:
                    self._interruption_reported = False

                else:
                    self._interruption_reported = True

        self.thread = threading.Thread(
            target=capture_task,
            name=f"capture-{self.config.box_id}",
        )

        self.thread.start()

        self._completed_commands[command.command_id] = (
            command.session_id
        )

        return command.session_id

    def _stop(self, command):
        """Finaliza la captura y persiste la ultima secuencia."""

        if self.session_id != command.session_id:
            raise RuntimeError(
                "La orden no corresponde a la sesion activa"
            )

        if self._stop_confirmation is None:

            # Registrar la orden antes de detener OBS.
            if self.journal is not None:
                existing = self.journal.get(command.command_id)

                if existing is not None:
                    raise RuntimeError(
                        "Detencion recuperada del disco: requiere "
                        "reconciliar el estado de OBS antes de continuar"
                    )

                self.journal.prepare(command)

            try:
                if self.thread is not None:
                    self.runner.stop()
                    self.thread.join(timeout=self.stop_timeout)

                    if self.thread.is_alive():
                        raise RuntimeError(
                            "La captura no finalizo dentro del plazo"
                        )

                # Finalizar OBS despues de terminar FFmpeg.
                self.controller.stop_capture()

                last_sequence = self.runner.store.last_sequence(
                    command.session_id
                )

                ended_at = self._now()

            except Exception:
                self.control.acknowledge(
                    self.config.box_id,
                    command.command_id,
                    success=False,
                    error_code="AGENT_STOP_FAILED",
                    occurred_at=self._now(),
                )
                raise

            # Persistir la detencion antes de confirmarla al backend.
            if self.journal is not None:
                self.journal.mark_executed(
                    command,
                    occurred_at=ended_at,
                    last_sequence=last_sequence,
                )

            self._stop_confirmation = (
                command.command_id,
                ended_at,
                last_sequence,
            )

        saved_command_id, ended_at, last_sequence = (
            self._stop_confirmation
        )

        if saved_command_id != command.command_id:
            raise RuntimeError("Existe otra detencion pendiente")

        # Confirmar la detencion conservando su secuencia final.
        self.control.acknowledge(
            self.config.box_id,
            command.command_id,
            success=True,
            last_sequence=last_sequence,
            occurred_at=ended_at,
        )

        # Guardar la confirmacion recibida de SCRUM-71.
        if self.journal is not None:
            self.journal.mark_acknowledged(command)

        self.controller.disconnect()

        self._completed_commands[command.command_id] = last_sequence

        self.session_id = None
        self.runner = None
        self.thread = None
        self._start_command_id = None
        self._stop_confirmation = None

        return last_sequence


    def recover_stop_confirmation(self, command: Command):
        """Recupera la confirmacion de una detencion ya ejecutada."""

        if not isinstance(command, Command):
            raise TypeError("Se esperaba un Command de SCRUM-71")

        if command.box != self.config.box_id:
            raise ValueError("La orden pertenece a otro box")

        if command.kind != "detencion":
            raise ValueError("Solo se recuperan detenciones")

        if self.journal is None:
            raise RuntimeError("No existe un registro persistente")

        if self.session_id is not None:
            raise RuntimeError("Existe una sesion activa")

        saved = self.journal.get(command.command_id)

        if saved is None:
            raise RuntimeError("La orden no existe en el registro")

        if (
            saved["session_id"] != str(command.session_id)
            or saved["box"] != command.box
            or saved["kind"] != command.kind
        ):
            raise ValueError("Los datos de la orden no coinciden")

        # Verificar el estado antes de validar la secuencia.
        if saved["state"] not in ("executed", "acknowledged"):
            raise RuntimeError("La detencion requiere reconciliacion")

        last_sequence = saved["last_sequence"]

        if (
            not isinstance(last_sequence, int)
            or isinstance(last_sequence, bool)
            or last_sequence < -1
        ):
            raise ValueError("Ultima secuencia persistida invalida")

        if saved["state"] == "acknowledged":
            self._completed_commands[command.command_id] = last_sequence
            return last_sequence


        # Verificar OBS antes de reenviar la confirmacion.
        status = self.inspect_recovery(command)

        if status["recording"] or status["streaming"]:
            raise RuntimeError(
                "OBS sigue activo: no se puede confirmar la detencion"
            )

        occurred_at = datetime.fromisoformat(saved["occurred_at"])

        if occurred_at.tzinfo is None:
            raise ValueError("La fecha persistida requiere zona horaria")

        # Reutilizar los datos originales de la detencion.
        self.control.acknowledge(
            self.config.box_id,
            command.command_id,
            success=True,
            last_sequence=last_sequence,
            occurred_at=occurred_at,
        )

        self.journal.mark_acknowledged(command)

        self._completed_commands[command.command_id] = last_sequence

        return last_sequence


    def heartbeat(self):
        """Informa actividad mediante el adaptador de SCRUM-71."""

        if self.session_id is None:
            raise RuntimeError("No existe una sesion activa")

        if self.capture_error is not None:
            if not self._interruption_reported:
                self.control.interrupted(
                    self.config.box_id,
                    self.session_id,
                    error_code="AGENT_INTERRUPTED",
                )
                self._interruption_reported = True

            raise RuntimeError(
                "La captura termino con un fallo tecnico"
            ) from self.capture_error

        return self.control.heartbeat(
            self.config.box_id,
            self.session_id,
        )

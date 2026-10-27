"""Ciclo de consulta de ordenes y heartbeat del agente SCRUM-72."""

import threading
import time

import httpx

from .session_coordinator import SessionCoordinator
from .command_journal import CommandJournal


class AgentLoop:
    def __init__(
        self,
        config,
        control,
        coordinator=None,
        clock=None,
    ):
        self.config = config
        self.control = control
        if coordinator is None:
            state_root = getattr(config, "agent_state_root", "")

            if not state_root:
                raise ValueError(
                    "AGENT_STATE_ROOT no esta configurado"
                )

            journal = CommandJournal(
                root=state_root,
                box_id=config.box_id,
            )

            coordinator = SessionCoordinator(
                config=config,
                control=control,
                journal=journal,
            )

        self.coordinator = coordinator


        self.clock = clock or time.monotonic

        self.poll_interval = config.command_poll_interval
        self.heartbeat_interval = config.heartbeat_interval
        self.max_control_failures = getattr(
            config,
            "control_max_failures",
            6,
        )

        if self.poll_interval <= 0:
            raise ValueError("Intervalo de consulta invalido")

        if self.heartbeat_interval <= 0:
            raise ValueError("Intervalo de heartbeat invalido")

        if self.max_control_failures < 1:
            raise ValueError("Maximo de fallos invalido")

        self._last_heartbeat_at = None
        self._heartbeat_session_id = None


    def check_startup_recovery(self):
        """Verifica el journal y el estado de OBS antes de arrancar."""

        journal = getattr(self.coordinator, "journal", None)

        if not isinstance(journal, CommandJournal):
            return []

        unresolved = journal.unresolved_sessions()

        if unresolved:
            sessions = sorted(
                {item["session_id"] for item in unresolved}
            )

            raise RuntimeError(
                "AGENT_RECOVERY_REQUIRED: "
                + ", ".join(sessions)
            )

        # Comprobar OBS antes de aceptar nuevas sesiones.
        controller = self.coordinator.controller

        try:
            controller.connect()
            status = controller.status()

        except Exception as exc:
            raise RuntimeError(
                "AGENT_OBS_STATUS_UNAVAILABLE"
            ) from exc

        finally:
            try:
                controller.disconnect()
            except Exception as exc:
                raise RuntimeError(
                    "AGENT_OBS_DISCONNECT_FAILED"
                ) from exc

        if (
            not isinstance(status, dict)
            or not isinstance(status.get("recording"), bool)
            or not isinstance(status.get("streaming"), bool)
        ):
            raise RuntimeError("AGENT_OBS_STATUS_INVALID")

        if status["recording"] or status["streaming"]:
            raise RuntimeError("AGENT_OBS_BUSY_STARTUP")

        return []


    def tick(self):
        """Consulta ordenes y comunica actividad de la sesion."""

        self.coordinator.retry_pending_confirmation()
        orders = self.control.commands(self.config.box_id)

        for command in orders:
            self.coordinator.handle_command(command)

        session_id = self.coordinator.session_id

        if session_id is None:
            self._last_heartbeat_at = None
            self._heartbeat_session_id = None
            return

        now = self.clock()

        if session_id != self._heartbeat_session_id:
            self._last_heartbeat_at = None
            self._heartbeat_session_id = session_id

        if (
            self._last_heartbeat_at is None
            or now - self._last_heartbeat_at >= self.heartbeat_interval
        ):
            self.coordinator.heartbeat()
            self._last_heartbeat_at = self.clock()

    def run(self, stop_event=None):
        """Ejecuta el ciclo y tolera fallos temporales de transporte."""

        # Revisar sesiones anteriores antes de aceptar ordenes.
        self.check_startup_recovery()

        stop_event = (
            stop_event
            if stop_event is not None
            else threading.Event()
        )

        consecutive_failures = 0

        while not stop_event.is_set():
            try:
                self.tick()

            except (
                TimeoutError,
                ConnectionError,
                OSError,
                httpx.RequestError,
            ) as exc:
                consecutive_failures += 1

                if consecutive_failures >= self.max_control_failures:
                    try:
                        self.coordinator.shutdown_after_control_failure()
                    except Exception as shutdown_exc:
                        raise RuntimeError(
                            "Transporte agotado y cierre "
                            "de captura incompleto"
                        ) from shutdown_exc

                    raise RuntimeError(
                        "Transporte de control no disponible "
                        "tras agotar los reintentos"
                    ) from exc

            else:
                # Una comunicacion exitosa reinicia el contador.
                consecutive_failures = 0

            # Espera interrumpible, sin bloquear el apagado.
            stop_event.wait(self.poll_interval)

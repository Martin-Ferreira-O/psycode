"""Ciclo de consulta de ordenes y heartbeat del agente SCRUM-72."""

import threading
import time

import httpx

from .session_coordinator import SessionCoordinator


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
        self.coordinator = (
            coordinator
            if coordinator is not None
            else SessionCoordinator(config, control)
        )

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

    def tick(self):
        """Consulta ordenes y comunica actividad de la sesion."""

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
                    raise RuntimeError(
                        "Transporte de control no disponible "
                        "tras agotar los reintentos"
                    ) from exc

            else:
                # Una comunicacion exitosa reinicia el contador.
                consecutive_failures = 0

            # Espera interrumpible, sin bloquear el apagado.
            stop_event.wait(self.poll_interval)

"""Registro persistente de ordenes del agente SCRUM-72."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

from backend.apps.capture.filesystem import private_directory

class CommandJournal:
    """Conserva el estado de cada orden en archivos JSON."""

    def __init__(self, root, box_id):
        if box_id not in {f"box-{n}" for n in range(3, 8)}:
            raise ValueError("Box invalido")

        self.root = Path(root) / box_id
        private_directory(self.root)

    def _path(self, command_id):
        command_id = UUID(str(command_id))
        return self.root / f"{command_id}.json"

    def _write(self, command_id, data):
        """Escritura atomica para evitar JSON parcialmente escrito."""
        destination = self._path(command_id)
        temporary = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=".pending-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary, destination)

        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get(self, command_id):
        path = self._path(command_id)

        if not path.exists():
            return None

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def prepare(self, command):
        """Registra la intencion antes de ejecutar OBS."""

        if command.box != self.root.name:
            raise ValueError("La orden pertenece a otro box")

        existing = self.get(command.command_id)

        if existing is not None:
            if (
                existing["session_id"] != str(command.session_id)
                or existing["kind"] != command.kind
            ):
                raise ValueError(
                    "El command_id ya pertenece a otra orden"
                )

            return existing

        data = {
            "command_id": str(command.command_id),
            "session_id": str(command.session_id),
            "box": command.box,
            "kind": command.kind,
            "state": "prepared",
            "occurred_at": None,
            "last_sequence": None,
        }

        self._write(command.command_id, data)
        return data

    def mark_executed(
        self,
        command,
        occurred_at,
        last_sequence=None,
    ):
        """Registra una operacion fisica ya completada."""

        data = self.get(command.command_id)

        if data is None:
            raise RuntimeError("La orden no fue preparada")

        if (
            data["session_id"] != str(command.session_id)
            or data["kind"] != command.kind
            or data["box"] != command.box
        ):
            raise ValueError("La orden no coincide con el registro")

        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at requiere zona horaria")

        if command.kind == "detencion":
            if (
                not isinstance(last_sequence, int)
                or isinstance(last_sequence, bool)
                or last_sequence < -1
            ):
                raise ValueError(
                    "La detencion requiere last_sequence valido"
                )
        elif last_sequence is not None:
            raise ValueError(
                "El inicio no debe declarar last_sequence"
            )

        timestamp = occurred_at.isoformat()

        if data["state"] != "prepared":
            if (
                data["occurred_at"] != timestamp
                or data["last_sequence"] != last_sequence
            ):
                raise ValueError(
                    "La ejecucion ya tiene otros datos registrados"
                )

            return data

        data["state"] = "executed"
        data["occurred_at"] = timestamp
        data["last_sequence"] = last_sequence

        self._write(command.command_id, data)
        return data

    def mark_acknowledged(self, command):
        """Registra una confirmacion exitosa del backend."""

        data = self.get(command.command_id)

        if data is None:
            raise RuntimeError("La orden no fue preparada")

        if (
            data["session_id"] != str(command.session_id)
            or data["kind"] != command.kind
            or data["box"] != command.box
        ):
            raise ValueError("La orden no coincide con el registro")

        if data["state"] == "prepared":
            raise RuntimeError(
                "No se puede confirmar una orden sin ejecucion"
            )

        if data["state"] == "acknowledged":
            return data

        data["state"] = "acknowledged"

        self._write(command.command_id, data)
        return data

    def unresolved_sessions(self):
        """Identifica sesiones persistidas sin una detencion ejecutada."""

        records = []

        for path in sorted(self.root.glob("*.json")):
            try:
                command_id = UUID(path.stem)

                with path.open("r", encoding="utf-8") as file:
                    data = json.load(file)

                if not isinstance(data, dict):
                    raise ValueError("El registro no es un objeto")

                if (
                    data.get("command_id") != str(command_id)
                    or data.get("box") != self.root.name
                    or data.get("kind") not in ("inicio", "detencion")
                    or data.get("state") not in (
                        "prepared",
                        "executed",
                        "acknowledged",
                    )
                ):
                    raise ValueError("Datos inconsistentes")

                session_id = str(UUID(data["session_id"]))

                if data["session_id"] != session_id:
                    raise ValueError("UUID de sesion invalido")

            except (ValueError, TypeError, KeyError, OSError) as exc:
                raise RuntimeError(
                    "AGENT_JOURNAL_INVALID"
                ) from exc

            records.append(data)

        # Una detencion ejecutada indica que OBS fue detenido.
        completed_sessions = {
            record["session_id"]
            for record in records
            if record["kind"] == "detencion"
            and record["state"] in ("executed", "acknowledged")
        }

        unresolved = []

        for record in records:
            if record["session_id"] in completed_sessions:
                continue

            if (
                record["kind"] == "inicio"
                or (
                    record["kind"] == "detencion"
                    and record["state"] == "prepared"
                )
            ):
                unresolved.append(
                    {
                        "session_id": record["session_id"],
                        "command_id": record["command_id"],
                        "kind": record["kind"],
                        "state": record["state"],
                    }
                )

        return unresolved

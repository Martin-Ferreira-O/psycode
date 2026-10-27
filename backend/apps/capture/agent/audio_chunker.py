
import argparse
import hashlib
import json
import os
import subprocess
import threading
import wave

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from backend.apps.capture.filesystem import open_private, private_directory
from .config import AgentConfig


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
FFMPEG_STOP_TIMEOUT = 2.0


def save_fragment(
    folder: Path,
    box: str,
    session_id: UUID,
    sequence: int,
    audio: bytes,
    captured_at: datetime,
):
    """Guarda un WAV y su manifiesto local."""

    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at debe incluir zona horaria")

    if sequence < 0:
        raise ValueError("La secuencia no puede ser negativa")

    private_directory(folder)

    filename = f"{sequence:06d}.wav"
    destination = folder / filename
    temporary = folder / f"{filename}.part"

    with os.fdopen(open_private(temporary, os.O_CREAT | os.O_TRUNC | os.O_RDWR), "w+b") as audio_file:
        with wave.open(audio_file, "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(audio)

    os.replace(temporary, destination)

    checksum = hashlib.sha256(
        destination.read_bytes()
    ).hexdigest()

    captured_at_utc = captured_at.astimezone(timezone.utc)

    metadata = {
        "box": box,
        "session_id": str(session_id),
        "sequence": sequence,
        "filename": filename,
        "checksum_sha256": checksum,
        "captured_at": captured_at_utc.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "duration_seconds": len(audio) / (
            SAMPLE_RATE * SAMPLE_WIDTH
        ),
        "status": "pending",
        "attempts": 0,
    }

    metadata_path = folder / f"{sequence:06d}.json"
    metadata_temp = folder / f"{sequence:06d}.json.part"

    with os.fdopen(open_private(metadata_temp, os.O_CREAT | os.O_TRUNC | os.O_RDWR),
                   "w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2)
        file.flush()
        os.fsync(file.fileno())

    os.replace(metadata_temp, metadata_path)

    print(
        f"Fragmento {sequence}: "
        f"{metadata['duration_seconds']:.3f} s"
    )

    return metadata


def capture_audio(
    config: AgentConfig,
    seconds: int | None,
    session_id: UUID,
    captured_at_start: datetime,
    stop_event: threading.Event | None = None,
    on_fragment_saved: Callable[[dict], None] | None = None,
):
    """
    Captura y fragmenta audio RTSP.

    seconds:
        Duración limitada en segundos, o None para captura continua.

    stop_event:
        Permite solicitar una detención externa.

    on_fragment_saved:
        Notifica después de guardar un fragmento completo.

    captured_at_start:
        Referencia temporal de laboratorio.
        No representa necesariamente el PTS real del audio.
    """

    if seconds is not None and seconds <= 0:
        raise ValueError("La duración debe ser positiva")

    if seconds is None and stop_event is None:
        raise ValueError(
            "La captura continua requiere un stop_event"
        )

    if (
        captured_at_start.tzinfo is None
        or captured_at_start.utcoffset() is None
    ):
        raise ValueError(
            "captured_at_start debe incluir zona horaria"
        )

    session_id = UUID(str(session_id))

    duration = config.chunk_duration
    overlap = config.chunk_overlap

    bytes_per_second = SAMPLE_RATE * SAMPLE_WIDTH

    chunk_size = int(duration * bytes_per_second)

    step_size = int(
        (duration - overlap) * bytes_per_second
    )

    overlap_size = int(overlap * bytes_per_second)

    output = (
        Path(__file__).resolve().parent
        / "fragments"
        / str(session_id)
    )

    command = [
        "ffmpeg",
        "-nostdin",
        "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", config.stream_url,
        "-map", "0:a:0",
        "-vn",
        *(
            ["-t", str(seconds)]
            if seconds is not None
            else []
        ),
        "-af", "aresample=async=1000:first_pts=0",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        "-f", "s16le",
        "pipe:1",
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    capture_finished = threading.Event()

    def stop_process():
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=FFMPEG_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=FFMPEG_STOP_TIMEOUT)

    def watch_stop_request():
        """Detiene FFmpeg ante una solicitud externa."""

        while not capture_finished.wait(0.1):
            if stop_event is not None and stop_event.is_set():
                stop_process()
                return

    watcher = None

    if stop_event is not None:
        watcher = threading.Thread(
            target=watch_stop_request,
            name="capture-stop-watcher",
            daemon=True,
        )
        watcher.start()

    buffer = bytearray()
    sequence = 0

    def fragment_timestamp(number: int) -> datetime:
        offset = number * (duration - overlap)
        return captured_at_start + timedelta(seconds=offset)

    def publish_fragment(audio: bytes):
        """Guarda y notifica un fragmento."""

        nonlocal sequence

        metadata = save_fragment(
            folder=output,
            box=config.box_id,
            session_id=session_id,
            sequence=sequence,
            audio=audio,
            captured_at=fragment_timestamp(sequence),
        )

        if on_fragment_saved is not None:
            on_fragment_saved(metadata)

        sequence += 1

    try:
        while True:
            block = process.stdout.read(bytes_per_second)

            if not block:
                break

            buffer.extend(block)

            while len(buffer) >= chunk_size:
                audio = bytes(buffer[:chunk_size])

                publish_fragment(audio)

                del buffer[:step_size]

        # Guardar el último fragmento cuando contenga audio nuevo y no solo muestras de solapamiento.
        if buffer and (
            sequence == 0 or len(buffer) > overlap_size
        ):
            publish_fragment(bytes(buffer))

        return_code = process.wait()

        if return_code != 0 and not (
            stop_event is not None and stop_event.is_set()
        ):
            raise RuntimeError("FFmpeg terminó con error")

    finally:
        capture_finished.set()

        if watcher is not None:
            watcher.join(timeout=2 * FFMPEG_STOP_TIMEOUT + 1)

        stop_process()

        if process.stdout:
            process.stdout.close()

    print(f"Total de fragmentos: {sequence}")

    return output


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--seconds",
        type=int,
        default=35,
    )

    args = parser.parse_args()
    config = AgentConfig.from_env()

    if not config.stream_url:
        raise ValueError("Falta STREAM_URL en .env")

    # UUID de laboratorio.
    # SCRUM-71 proporcionará el UUID real.
    session_id = uuid4()

    # Referencia temporal aproximada de laboratorio.
    captured_at_start = datetime.now(timezone.utc)

    capture_audio(
        config=config,
        seconds=args.seconds,
        session_id=session_id,
        captured_at_start=captured_at_start,
    )


if __name__ == "__main__":
    main()


import argparse
import hashlib
import json
import os
import subprocess
import wave

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from .config import AgentConfig


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2


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

    folder.mkdir(parents=True, exist_ok=True)

    filename = f"{sequence:06d}.wav"
    destination = folder / filename
    temporary = folder / f"{filename}.part"

    with wave.open(str(temporary), "wb") as wav:
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
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "duration_seconds": len(audio) / (
            SAMPLE_RATE * SAMPLE_WIDTH
        ),
        "status": "pending",
        "attempts": 0,
    }

    metadata_path = folder / f"{sequence:06d}.json"
    metadata_temp = folder / f"{sequence:06d}.json.part"

    with metadata_temp.open("w", encoding="utf-8") as file:
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
    seconds: int,
    session_id: UUID,
    captured_at_start: datetime,
):
    """
    Captura y fragmenta audio RTSP.

    captured_at_start es una referencia temporal de laboratorio.
    No representa necesariamente el PTS real del primer audio.
    """

    if seconds <= 0:
        raise ValueError("La duración debe ser positiva")

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
        "-t", str(seconds),
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

    buffer = bytearray()
    sequence = 0

    def fragment_timestamp(number: int) -> datetime:
        offset = number * (duration - overlap)
        return captured_at_start + timedelta(seconds=offset)

    try:
        while True:
            block = process.stdout.read(bytes_per_second)

            if not block:
                break

            buffer.extend(block)

            while len(buffer) >= chunk_size:
                audio = bytes(buffer[:chunk_size])

                save_fragment(
                    folder=output,
                    box=config.box_id,
                    session_id=session_id,
                    sequence=sequence,
                    audio=audio,
                    captured_at=fragment_timestamp(sequence),
                )

                sequence += 1
                del buffer[:step_size]

        if buffer and (
            sequence == 0 or len(buffer) > overlap_size
        ):
            save_fragment(
                folder=output,
                box=config.box_id,
                session_id=session_id,
                sequence=sequence,
                audio=bytes(buffer),
                captured_at=fragment_timestamp(sequence),
            )
            sequence += 1

        if process.wait() != 0:
            raise RuntimeError("FFmpeg terminó con error")

    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()

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

    # Exclusivamente para pruebas manuales.
    # SCRUM-71 deberá proporcionar el UUID en producción.
    session_id = uuid4()

    # Referencia aproximada de laboratorio.
    # No equivale al timestamp verificado del audio RTSP.
    captured_at_start = datetime.now(timezone.utc)

    capture_audio(
        config=config,
        seconds=args.seconds,
        session_id=session_id,
        captured_at_start=captured_at_start,
    )


if __name__ == "__main__":
    main()

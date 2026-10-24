
import argparse
import hashlib
import json
import os
import subprocess
import wave

from pathlib import Path
from uuid import uuid4

from .config import AgentConfig


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # PCM de 16 bits


def save_fragment(folder, box, session_id, sequence, audio):
    folder.mkdir(parents=True, exist_ok=True)

    filename = f"{sequence:06d}.wav"
    destination = folder / filename
    temporary = folder / f"{filename}.part"

    # Primero generar completamente el WAV.
    with wave.open(str(temporary), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio)

    # Publicar el archivo terminado.
    os.replace(temporary, destination)

    checksum = hashlib.sha256(
        destination.read_bytes()
    ).hexdigest()

    metadata = {
        "box": box,
        "session_id": str(session_id),
        "sequence": sequence,
        "filename": filename,
        "checksum_sha256": checksum,
        "duration_seconds": len(audio) / (
            SAMPLE_RATE * SAMPLE_WIDTH
        ),
    }

    metadata_path = folder / f"{sequence:06d}.json"
    metadata_temp = folder / f"{sequence:06d}.json.part"

    metadata_temp.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    os.replace(metadata_temp, metadata_path)

    print(
        f"Fragmento {sequence}: "
        f"{metadata['duration_seconds']:.3f} s"
    )

    return metadata


def capture_audio(config, seconds, session_id):
    duration = config.chunk_duration
    overlap = config.chunk_overlap

    bytes_per_second = SAMPLE_RATE * SAMPLE_WIDTH
    chunk_size = duration * bytes_per_second
    step_size = (duration - overlap) * bytes_per_second
    overlap_size = overlap * bytes_per_second

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
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        "-f", "s16le",
        "pipe:1",
    ]

    print(f"Box: {config.box_id}")
    print(f"Sesión de prueba: {session_id}")
    print(f"Duración: {duration} s")
    print(f"Solapamiento: {overlap} s")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    buffer = bytearray()
    sequence = 0

    try:
        while True:
            block = process.stdout.read(bytes_per_second)

            if not block:
                break

            buffer.extend(block)

            while len(buffer) >= chunk_size:
                audio = bytes(buffer[:chunk_size])

                save_fragment(
                    output,
                    config.box_id,
                    session_id,
                    sequence,
                    audio,
                )

                sequence += 1
                del buffer[:step_size]

        # Guardar el último fragmento parcial,
        # evitando publicar solo el solapamiento.
        if buffer and (sequence == 0 or len(buffer) > overlap_size):
            save_fragment(
                output,
                config.box_id,
                session_id,
                sequence,
                bytes(buffer),
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
    print(f"Archivos guardados en: {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seconds",
        type=int,
        default=35,
    )
    args = parser.parse_args()

    if args.seconds <= 0:
        parser.error("--seconds debe ser positivo")

    config = AgentConfig.from_env()

    if not config.stream_url:
        raise ValueError("Falta STREAM_URL en .env")

    capture_audio(config, args.seconds, uuid4())


if __name__ == "__main__":
    main()

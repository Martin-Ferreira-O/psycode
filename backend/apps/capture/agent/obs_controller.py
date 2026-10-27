import subprocess
import time
import obsws_python as obs


class OBSController:
    def __init__(self, config):
        self.config = config
        self.client = None

    def connect(self):
        self.client = obs.ReqClient(
            host=self.config.obs_host,
            port=self.config.obs_port,
            password=self.config.obs_password,
            timeout=5,
        )

        version = self.client.get_version()
        return version.obs_version

    def status(self):
        if self.client is None:
            raise RuntimeError("No existe conexión con OBS")

        recording = self.client.get_record_status()
        streaming = self.client.get_stream_status()

        return {
            "recording": recording.output_active,
            "streaming": streaming.output_active,
        }

    def start_capture(self):
        current = self.status()

        if current["recording"] or current["streaming"]:
            raise RuntimeError(
                "OBS ya está grabando o transmitiendo"
            )

        recording_started = False
        streaming_started = False

        try:
            print("Iniciando grabación...")
            self.client.start_record()
            recording_started = True

            print("Iniciando streaming...")
            self.client.start_stream()
            streaming_started = True

            # Esperar hasta 10 segundos por ambas salidas
            deadline = time.monotonic() + 10

            while time.monotonic() < deadline:
                current = self.status()

                if current["recording"] and current["streaming"]:
                    print("Grabación y streaming activos")
                    return current

                time.sleep(0.5)

            raise RuntimeError(
                "OBS no activó ambas salidas en 10 segundos"
            )

        except Exception:
            # Recuperación de un inicio parcial
            if streaming_started:
                try:
                    self.client.stop_stream()
                except Exception:
                    print("No se pudo detener el streaming")

            if recording_started:
                try:
                    self.client.stop_record()
                except Exception:
                    print("No se pudo detener la grabación")

            raise


    def wait_for_audio_stream(self, timeout=15.0, retry_interval=0.5):
        """Espera hasta que MediaMTX publique una pista de audio."""

        if timeout <= 0 or retry_interval <= 0:
            raise ValueError("Intervalos de espera invalidos")

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()

            command = [
                "ffprobe",
                "-v", "error",
                "-rtsp_transport", "tcp",
                "-i", self.config.stream_url,
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
            ]

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=min(3.0, max(0.1, remaining)),
                )

                if (
                    result.returncode == 0
                    and "audio" in result.stdout.splitlines()
                ):
                    return

            except FileNotFoundError as exc:
                raise RuntimeError(
                    "AGENT_FFPROBE_UNAVAILABLE"
                ) from exc

            except subprocess.TimeoutExpired:
                pass

            remaining = deadline - time.monotonic()

            if remaining > 0:
                time.sleep(min(retry_interval, remaining))

        raise RuntimeError("AGENT_STREAM_NOT_READY")


    def stop_capture(self):
        current = self.status()

        if current["streaming"]:
            print("Deteniendo streaming...")
            self.client.stop_stream()

        if current["recording"]:
            print("Deteniendo grabación...")
            self.client.stop_record()

        # Esperar hasta 10 segundos por la detención
        deadline = time.monotonic() + 10

        while time.monotonic() < deadline:
            current = self.status()

            if not current["streaming"] and not current["recording"]:
                print("Grabación y streaming detenidos")
                return current

            time.sleep(0.5)

        raise RuntimeError(
            "OBS no detuvo ambas salidas en 10 segundos"
        )

    def disconnect(self):
        if self.client is not None:
            self.client.disconnect()
            self.client = None

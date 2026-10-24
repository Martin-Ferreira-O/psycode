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
            # Recuperación de un inicio parcial.
            # Solo intentar detener las salidas iniciadas
            # por esta operación.
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

    def stop_capture(self):
        current = self.status()

        if current["streaming"]:
            self.client.stop_stream()

        if current["recording"]:
            self.client.stop_record()

        current = self.status()

        if any(current.values()):
            raise RuntimeError(
                "OBS no detuvo ambas salidas"
            )

        return current

    def disconnect(self):
        if self.client is not None:
            self.client.disconnect()
            self.client = None

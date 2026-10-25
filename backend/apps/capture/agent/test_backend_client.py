
import hashlib
import tempfile
import unittest
import wave

from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from .backend_client import BackendClient
from .config import AgentConfig


class BackendClientTests(unittest.TestCase):
    """Pruebas del cliente HTTP del agente SCRUM-72."""

    def setUp(self):
        self.session_id = "11111111-1111-4111-8111-111111111111"
        self.captured_at = "2026-10-24T15:00:10Z"

        # Configuración simulada. No utiliza credenciales reales.
        self.config = AgentConfig(
            box_id="box-5",
            obs_host="127.0.0.1",
            obs_port=4455,
            obs_password="test",
            stream_url="rtsp://localhost/test",
            chunk_duration=10,
            chunk_overlap=1,
            backend_url="http://localhost:8000",
            agent_token="agent-box-5.token-de-prueba",
            http_timeout=15,
            max_retries=3,
            retry_backoff=0,
        )

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.path = Path(self.temp_dir.name) / "fragmento.wav"

        # Generar WAV sintético: PCM 16-bit, mono, 16 kHz.
        with wave.open(str(self.path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)

        self.original_bytes = self.path.read_bytes()
        self.checksum = hashlib.sha256(
            self.original_bytes
        ).hexdigest()

        self.client = BackendClient(self.config)

    def crear_respuesta(self, status_code=201):
        """Construir una confirmación válida de SCRUM-73."""

        response = Mock()
        response.status_code = status_code

        response.json.return_value = {
            "success": True,
            "data": {
                "job_id": "22222222-2222-4222-8222-222222222222",
                "session_id": self.session_id,
                "box": "box-5",
                "secuencia": 0,
                "formato": "wav",
                "checksum": self.checksum,
                "size_bytes": len(self.original_bytes),
                "estado": "aceptado",
            },
        }

        return response

    def enviar_fragmento(self):
        """Enviar el fragmento usando los datos de prueba."""

        return self.client.upload_fragment(
            file_path=self.path,
            session_id=self.session_id,
            sequence=0,
            captured_at=self.captured_at,
            checksum=self.checksum,
        )

    def comprobar_archivo_intacto(self):
        """Comprobar que el cliente no alteró ni eliminó el WAV."""

        self.assertTrue(self.path.exists())
        self.assertEqual(
            self.path.read_bytes(),
            self.original_bytes,
        )

    def comprobar_metadatos_reintento(self, mock_post):
        """Comprobar que ambos intentos conservan su identidad."""

        self.assertEqual(mock_post.call_count, 2)

        first_call = mock_post.call_args_list[0]
        second_call = mock_post.call_args_list[1]

        first_data = first_call.kwargs["data"]
        second_data = second_call.kwargs["data"]

        self.assertEqual(first_data, second_data)

        self.assertEqual(first_data["box"], "box-5")
        self.assertEqual(
            first_data["session_id"],
            self.session_id,
        )
        self.assertEqual(first_data["secuencia"], "0")
        self.assertEqual(
            first_data["checksum"],
            self.checksum,
        )
        self.assertEqual(
            first_data["captured_at"],
            self.captured_at,
        )


    def test_upload_fragment_201(self):
        response = self.crear_respuesta(201)

        with patch(
            "backend.apps.capture.agent.backend_client.httpx.post",
            return_value=response,
        ) as mock_post:

            result = self.enviar_fragmento()

        self.assertEqual(result["estado"], "aceptado")
        self.assertEqual(result["secuencia"], 0)

        mock_post.assert_called_once()
        self.comprobar_archivo_intacto()



    def test_timeout_then_200(self):
        response = self.crear_respuesta(200)

        with patch(
            "backend.apps.capture.agent.backend_client.httpx.post",
            side_effect=[
                httpx.ReadTimeout("Timeout simulado"),
                response,
            ],
        ) as mock_post:

            result = self.enviar_fragmento()

        self.assertEqual(result["estado"], "aceptado")

        self.comprobar_metadatos_reintento(mock_post)
        self.comprobar_archivo_intacto()


    def test_error_500_then_201(self):
        error_response = Mock()
        error_response.status_code = 500

        success_response = self.crear_respuesta(201)

        with patch(
            "backend.apps.capture.agent.backend_client.httpx.post",
            side_effect=[
                error_response,
                success_response,
            ],
        ) as mock_post:

            result = self.enviar_fragmento()

        self.assertEqual(result["estado"], "aceptado")

        self.comprobar_metadatos_reintento(mock_post)
        self.comprobar_archivo_intacto()

    def test_respuesta_incompleta_then_200(self):
        incomplete_response = Mock()
        incomplete_response.status_code = 201

        incomplete_response.json.return_value = {
            "success": True,
            "data": {
                "estado": "aceptado",
            },
        }

        valid_response = self.crear_respuesta(200)

        with patch(
            "backend.apps.capture.agent.backend_client.httpx.post",
            side_effect=[
                incomplete_response,
                valid_response,
            ],
        ) as mock_post:

            result = self.enviar_fragmento()

        self.assertEqual(result["estado"], "aceptado")

        self.comprobar_metadatos_reintento(mock_post)
        self.comprobar_archivo_intacto()


if __name__ == "__main__":
    unittest.main()

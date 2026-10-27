
import unittest
from unittest.mock import Mock, patch

from backend.apps.capture.agent.obs_controller import OBSController


class TestOBSController(unittest.TestCase):

    def setUp(self):
        self.controller = OBSController(config=Mock())
        self.controller.client = Mock()

    def test_stop_capture_espera_detencion(self):
        """
        OBS demora en actualizar el estado.
        El controlador debe esperar y no lanzar un error.
        """

        self.controller.status = Mock(
            side_effect=[
                {"recording": True, "streaming": True},
                {"recording": True, "streaming": True},
                {"recording": False, "streaming": True},
                {"recording": False, "streaming": False},
            ]
        )

        with patch(
            "backend.apps.capture.agent.obs_controller.time.sleep"
        ):
            result = self.controller.stop_capture()

        self.assertEqual(
            result,
            {"recording": False, "streaming": False},
        )

        self.controller.client.stop_stream.assert_called_once()
        self.controller.client.stop_record.assert_called_once()

    def test_stop_capture_ya_detenido(self):
        """
        Si OBS ya está detenido, no debe enviar
        órdenes innecesarias.
        """

        self.controller.status = Mock(
            return_value={
                "recording": False,
                "streaming": False,
            }
        )

        result = self.controller.stop_capture()

        self.assertEqual(
            result,
            {"recording": False, "streaming": False},
        )

        self.controller.client.stop_stream.assert_not_called()
        self.controller.client.stop_record.assert_not_called()

    def test_stop_capture_solo_streaming(self):
        """
        Si OBS solamente transmite, debe detener
        el streaming sin intentar detener una grabación.
        """

        self.controller.status = Mock(
            side_effect=[
                {"recording": False, "streaming": True},
                {"recording": False, "streaming": True},
                {"recording": False, "streaming": False},
            ]
        )

        with patch(
            "backend.apps.capture.agent.obs_controller.time.sleep"
        ):
            result = self.controller.stop_capture()

        self.assertEqual(
            result,
            {"recording": False, "streaming": False},
        )

        self.controller.client.stop_stream.assert_called_once()
        self.controller.client.stop_record.assert_not_called()


if __name__ == "__main__":
    unittest.main()

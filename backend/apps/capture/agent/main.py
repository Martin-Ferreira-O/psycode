
import argparse

from config import AgentConfig
from obs_controller import OBSController


def main():
    parser = argparse.ArgumentParser(
        description="Agente de captura SCRUM-72"
    )

    parser.add_argument(
        "action",
        choices=["status", "start", "stop"],
    )

    args = parser.parse_args()

    config = AgentConfig.from_env()
    controller = OBSController(config)

    try:
        version = controller.connect()

        print(f"Box: {config.box_id}")
        print(f"OBS conectado: {version}")

        if args.action == "status":
            result = controller.status()

        elif args.action == "start":
            result = controller.start_capture()

        else:
            result = controller.stop_capture()

        print("Estado:", result)

    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()

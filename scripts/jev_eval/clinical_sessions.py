
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from os import environ
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from dotenv import dotenv_values
import httpx

from backend.apps.analysis.clients import JevAnalizador
from backend.apps.analysis.domain import Fragment, Transcription, Word
from backend.apps.analysis.providers.settings import Settings
from backend.apps.analysis.services import AnalysisService
from backend.common.processing_models import JevVersion


CONFIRMED_ROLES = {"E": "professional", "P": "patient"}
THRESHOLD = .4
SESSIONS = (
    {
        "id": "negacion_y_ejemplo",
        "roles": CONFIRMED_ROLES,
        "turns": (
            ("E", "¿Cómo anduviste esta semana, sobre todo al salir de la pega?"),
            ("P", "Anduve reventada, así que el sábado dormí hasta tarde. Me sirvió descansar."),
            ("E", 'Para explicar la diferencia, un ejemplo sería: «He pensado en quitarme la vida». ¿Se entiende?'),
            ("P", "Sí, se entiende el ejemplo. Nunca he pensado en quitarme la vida."),
            ("E", "¿Y cuando hablaste de apagar todo, a qué te referías?"),
            ("P", "A apagar el celu y descansar un rato. Igual me entusiasma ir a la feria mañana."),
        ),
        "expected": (),
    },
    {
        "id": "terceros_y_respuesta_ambigua",
        "roles": {"E": "professional"},
        "turns": (
            ("E", "Cuéntame qué fue lo más pesado de esta semana."),
            (None, "Mi hermano me contó que intentó quitarse la vida hace años. Me dejó preocupada por él."),
            ("E", "¿Pensaste en quitarte la vida o en salir de la casa para despejarte?"),
            (None, "Sí, po. Eso me ayudó a acostumbrarme al barrio."),
            ("E", "¿Al final probaste salir a caminar después de almuerzo?"),
            (None, "Sí, lo intenté ayer y se me pasó un poco el susto. Caminé hasta la plaza."),
        ),
        "expected": (),
    },
    {
        "id": "intento_remoto_y_negacion_actual",
        "roles": CONFIRMED_ROLES,
        "turns": (
            ("E", "¿De qué época era eso que mencionabas la otra vez?"),
            ("P", "Intenté quitarme la vida hace años, cuando todavía iba al colegio."),
            ("E", "¿Desde ese tiempo te ha vuelto a pasar algo parecido?"),
            ("P", "No he vuelto a intentarlo y no he pensado en matarme. Eso quedó atrás."),
            ("E", "¿Qué te ha servido estas últimas semanas?"),
            ("P", "Mi mamá me acompaña a la micro y salimos a caminar. Ahora estoy más tranquila."),
        ),
        "expected": (),
    },
    {
        "id": "intento_esta_manana_confirmado",
        "roles": CONFIRMED_ROLES,
        "turns": (
            ("E", "¿Qué te hizo venir hoy? Te escucho con calma."),
            ("P", "Mi hermana me llamó por la pega, pero esta mañana intenté quitarme la vida y me detuve."),
            ("E", "¿Y qué pasó después de que te detuviste?"),
            ("P", "Tomé la micro y vine para acá. No tengo intención de volver a intentarlo ahora."),
            ("E", "Ya. Gracias por contármelo. Tomémonos un momento."),
        ),
        "expected": (("t1", 7, 3, None),),
    },
    {
        "id": "intento_ayer_voz_sin_confirmar",
        "roles": {"E": "professional"},
        "turns": (
            ("E", "Dijiste que anoche podías hablar poco. ¿Qué había pasado antes?"),
            (None, "No hallaba cómo contarlo, me daba vergüenza."),
            ("E", "¿Ayer intentaste quitarte la vida?"),
            (None, "Sí, intenté quitarme la vida ayer, pero paré y pedí ayuda."),
            ("E", "Gracias por decirlo. ¿Pudiste hablar con alguien después?"),
            (None, "Sí, mi primo me acompañó un rato. Hoy pude venir a conversar."),
        ),
        "expected": (("t3", 7, 3, None),),
    },
)


class ObservedTransport:
    def __init__(self, client):
        self.client = client
        self.attempts = []
        self.answers = {}
        self.usage = None

    def request(self, method, url, **kwargs):
        payload = kwargs["json"]
        attempt = {"questions": len(payload["questions"])}
        self.attempts.append(attempt)
        response = self.client.request(method, url, **kwargs)
        attempt["status"] = response.status_code
        if response.is_success:
            try:
                data = response.json()
            except ValueError:
                return response
            if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                return response
            self.answers = {
                key: {field: answer[field] for field in ("noul", "choice", "confidence", "probabilities") if field in answer}
                for key, answer in data["answers"].items() if key in payload["questions"] and isinstance(answer, dict)
            }
            usage = data.get("usage")
            if isinstance(usage, dict):
                self.usage = {key: usage[key] for key in ("input_tokens", "output_tokens", "cost") if key in usage}
        return response


def evaluate(session, settings, client):
    fragment = Fragment(str(uuid4()), 0, "caja-ficticia", datetime.now(timezone.utc),
                        Path("sesion-ficticia.wav"), end=len(session["turns"]) * 2 * 16000,
                        analysis_unit="fragment")
    words = tuple(Word(text, index * 2., index * 2. + 1., speaker)
                  for index, (speaker, text) in enumerate(session["turns"]))
    transcriber = Mock()
    transcriber.transcribe.return_value = Transcription(" ".join(word.text for word in words), words, "deleted")
    transport = ObservedTransport(client)
    alerts = Mock()
    analysis = AnalysisService(transcriber, JevAnalizador(settings, transport), Mock(), alerts, Mock(),
                               threshold_loader=lambda: THRESHOLD)
    result = analysis.process(fragment)
    signals = [(f"t{int(signal.start // 2)}", signal.matrix_level, signal.severity, signal.speaker)
               for signal in result.signals]
    sent = [(f"t{int(item['inicio'] // 2)}", item["nivel_matriz"], call.kwargs["origen"])
            for call in alerts.register_alert.call_args_list for item in call.kwargs["analisis"]["evidencias"]]
    expected = session["expected"]
    expected_alerts = [(turn, level, "analysis.speechmatics-jev/1.0") for turn, level, _, _ in expected]
    expected_alert_count = int(bool(expected))
    counts = Counter(signals)
    gold = Counter(expected)
    return {
        "session": session["id"], "expected": expected, "signals": signals,
        "expected_alerts": expected_alerts, "alerts": sent,
        "state": str(result.state), "errors": result.error_codes, "questions_version": result.questions_version,
        "http": transport.attempts, "answers": transport.answers, "usage": transport.usage,
        "localized": result.decisions[0].evidence_turns if result.decisions else {},
        "verdicts": result.decisions[0].review_verdicts if result.decisions else {},
        "fp": list((counts - gold).elements()), "fn": list((gold - counts).elements()),
        "passed": (bool(result.decisions) and counts == gold and Counter(sent) == Counter(expected_alerts)
                   and alerts.register_alert.call_count == expected_alert_count),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 6))
    args = parser.parse_args()
    key = environ.get("TYPESAFE_API_KEY") or dotenv_values(".env").get("TYPESAFE_API_KEY")
    if not key:
        parser.error("Falta TYPESAFE_API_KEY.")
    settings = Settings(jev_key=key, jev_provider="typesafe", jev_model=JevVersion.V114.typesafe_id,
                        external_enabled=True, timeout=40)
    digest = sha256(json.dumps(SESSIONS, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    args.output.touch(mode=0o600, exist_ok=False)
    rows = []
    with args.output.open("w", encoding="utf-8") as output, httpx.Client(
            headers={"Authorization": f"Bearer {key}"}, timeout=30, trust_env=False, follow_redirects=False) as client:
        for repetition in range(1, args.repeat + 1):
            for session in SESSIONS:
                row = {"repetition": repetition, **evaluate(session, settings, client)}
                rows.append(row)
                print(f"{repetition}/{args.repeat} {row['session']} {row['state']} {row['signals']} {row['errors']}", flush=True)
        json.dump({"provider": settings.analysis_provider, "model": settings.analysis_model, "threshold": THRESHOLD,
                   "fixture_sha256": digest, "rows": rows}, output, ensure_ascii=False, indent=2)
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

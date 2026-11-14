"""Experimental, reviewable signals. Scores are not clinical probabilities."""
import re
import unicodedata

from backend.common.processing_models import JEV_DEFAULT_THRESHOLD

HYPOTHESES = [
    "La persona expresa malestar psicológico sin expresar deseos de morir.",
    "La persona expresa el deseo de estar muerta o no despertar.",
    "La persona expresa pensamientos propios de suicidarse.",
    "La persona ha considerado una forma de suicidarse.",
    "La persona expresa intención de actuar sobre sus pensamientos suicidas.",
    "La persona expresa un plan de suicidio y la intención de llevarlo a cabo.",
    "La persona relata acciones de preparación para suicidarse.",
    "La persona relata un intento de suicidio, interrumpido, abortado o realizado.",
]
THRESHOLDS = {"candidate": JEV_DEFAULT_THRESHOLD}


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def context_flags(text):
    t = normalize(text)
    flags = []
    patterns = {
        "pregunta": r"[¿?]|\b(?:has|ha|habias) pensado\b",
        "antecedente_temporal": r"\b(?:antes|hace anos|hace meses|el ano pasado|cuando era|en el pasado|intente)\b",
        "referencia_a_terceros": r"\b(?:mi (?:amigo|amiga|hermano|hermana|padre|madre)|el paciente|ella dijo|el dijo|me dijo)\b",
        "cita": r'[«»“”"]',
        "negacion": r"\b(?:no|nunca|jamas)\b",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, t):
            flags.append(name)
    return flags


def literal_candidates(text):
    """High-specificity lexical evidence only; ambiguous matrix examples need NLI."""
    t = normalize(text)
    patterns = {
        1: r"(?:ojala|quisiera|preferiria).{0,30}(?:no despert|no estar vivo|no existir)|(?:quiero|quisiera) dejar de existir|no (?:quiero|deseo) (?:seguir )?vivir",
        2: r"(?:pienso|pense|pensaba|pensado|pensando|pensamientos).{0,30}(?:suicid|quitarme la vida|matarme)",
        4: r"(?:tengo|siento).{0,10}intencion de (?:suicidarme|matarme|quitarme la vida)",
    }
    found = []
    for level, pattern in patterns.items():
        if re.search(pattern, t):
            found.append(level)
    return found


def explicit_denial(text):
    t = normalize(text)
    return bool(re.search(r"\b(?:no|nunca|jamas) (?:he |estoy |tengo |quiero |pienso |pensado |en |pensando |pensamientos |de |ganas |intencion |deseo ){0,7}(?:suicidar|suicidio|matarme|quitarme la vida)", t))


def evidence_dimensions(text, context=""):
    """Do not let generic NLI invent a method, intention, plan, or action.

    These conservative lexical gates are experimental, not a clinical instrument.
    Missing explicit evidence means abstention, even for a high model score.
    """
    t = normalize(text)
    domain = bool(re.search(r"suicid|quitar.{0,12}vida|matarme|(?:dejar de|no quiero) vivir|morir|muert", normalize(text + " " + context)))
    intent = bool(re.search(r"intencion|(?:voy|quiero|decidido) a (?:hacerlo|actuar)|decidid[oa]|voy a terminar haciendolo|podria hacerlo|poder detenerme|siento que voy a actuar", t))
    intent = intent and not re.search(r"\b(?:no|sin|ninguna|nunca)\s+(?:tengo |hay |tiene |ninguna )?intencion\b", t)
    plan = bool(re.search(r"\bplan\b|decidido cuando|se como voy|lo tengo pensado", t))
    plan = plan and not re.search(r"\b(?:no (?:tengo|hay|existe)|sin) (?:un |ningun )?plan\b", t)
    method = bool(re.search(r"\bcomo\b|\bforma\b|\bmanera\b|\bmetodo\b", t))
    method = method and not re.search(r"\bno (?:he )?(?:pensado|se|imaginado) (?:en )?(?:como|una forma|una manera)", t)
    return {3: domain and method,
            4: domain and intent,
            5: domain and plan and intent,
            6: domain and bool(re.search(r"preparativ|preparar|preparado|despidiendo|despedid|asuntos en orden|cosas arregladas", t)),
            7: domain and bool(re.search(r"\bintente\b|\bintentado\b|empece pero|me detuve|me interrump|lo intente", t))}


def jev_candidates(text, values, matrix, context="", *, threshold=JEV_DEFAULT_THRESHOLD):
    """Experimental review cutoff; a Noul value is never a clinical probability."""
    return _candidates(text, values, [v >= threshold for v in values],
                       matrix, context, "JEV Noul sin calibración clínica")


def _candidates(text, values, supported_values, matrix, context, score_kind):
    flags = context_flags(text)
    # A denial is not evidence of affirmative ideation. Mixed/contrasting utterances
    # remain reviewable rather than letting one negation cancel a later disclosure.
    denied = explicit_denial(text) and not re.search(r"\b(?:pero|aunque|ahora|sin embargo)\b", normalize(text))
    literal = literal_candidates(text)
    # A denial of active ideation can coexist with a passive death wish.
    if denied:
        literal = [level for level in literal if level == 1]
    dimensions = evidence_dimensions(text, context)
    result = []
    for category, value, supported in zip(matrix["categories"], values, supported_values):
        level = category["level"]
        if level == 0 or (denied and level not in literal) or not (supported or level in literal):
            continue
        if level >= 3 and not dimensions[level]:
            continue
        result.append({"category_id": category["id"], "category": category["name"],
                       "matrix_level": level, "source": category["source"],
                       "score": round(value, 4), "score_kind": score_kind,
                       "basis": "regla y modelo" if level in literal and supported else "regla explícita" if level in literal else "modelo",
                       "context_flags": flags, "review": "pending", "correction": None,
                       "interpretation": "Requiere contexto" if flags else "Hipótesis para revisión",
                       # Do not duplicate potentially operational method details into summaries.
                       "evidence": "Revisar la transcripción y el audio del intervalo indicado."})
    return result


def align_words(words, turns):
    """Midpoint alignment; preserve overlap/unknown and bound utterances to 15 s."""
    utterances = []
    for word in words:
        midpoint = (word["start"] + word["end"]) / 2
        active = [t for t in turns if t["start"] <= midpoint < t["end"]]
        labels = {t["speaker"] for t in active}
        # Multiple original turns are retained, even if both have unknown identity.
        overlap = len(active) > 1
        speaker = next(iter(labels)) if len(labels) == 1 and not overlap else None
        state = "overlap" if overlap else "assigned" if speaker else "unknown"
        if (utterances and utterances[-1]["speaker"] == speaker and utterances[-1]["attribution"] == state
                and not re.search(r"[.!?…][\s\"»”]*$", utterances[-1]["text"])
                and word["start"] - utterances[-1]["end"] < 1.2
                and word["end"] - utterances[-1]["start"] <= 15):
            utterances[-1]["text"] += word["text"]
            utterances[-1]["end"] = word["end"]
            utterances[-1]["words"].append(word)
        else:
            utterances.append({"start": word["start"], "end": word["end"], "speaker": speaker,
                               "attribution": state, "text": word["text"], "words": [word]})
    return utterances


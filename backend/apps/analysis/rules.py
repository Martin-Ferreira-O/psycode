"""Experimental, reviewable signals. Scores are not clinical probabilities."""
import json
from pathlib import Path
import re
import unicodedata

from backend.common.processing_models import JEV_DEFAULT_THRESHOLD

MATRIX = json.loads(Path(__file__).with_name("matrix.json").read_text(encoding="utf-8"))
HYPOTHESES = [
    f"{row['name']}. {row['description']} Indicador de la matriz: {row['limitation']}."
    for row in MATRIX["categories"]
]


def review_priority(level):
    """Prioridad operativa de revisión. La matriz conserva sus ocho categorías."""
    return (0, 1, 2, 2, 3, 3, 3, 3)[level]


THRESHOLDS = {"candidate": JEV_DEFAULT_THRESHOLD}


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def context_flags(text):
    t = normalize(text)
    flags = []
    patterns = {
        "pregunta": r"[¿?]|\b(?:has|ha|habias) pensado\b",
        "antecedente_temporal": r"\b(?:antes|hace anos|hace meses|el ano pasado|cuando era|en el pasado)\b",
        "referencia_a_terceros": rf"\b(?:{_THIRD_PERSON}|el paciente|ella dijo|el dijo|me dijo)\b",
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


_SELF_HARM_ACTION = r"(?:suicidarme|matarme|quitarme la vida|(?:acabar|terminar) con mi vida)"
_THIRD_PERSON = r"mi (?:amig[oa]|herman[oa]|padre|madre|papa|mama|prim[oa]|ti[oa]|pareja|companero|companera)"
_PASSIVE_WISH = re.compile(
    r"\b(?:ojala (?:que )?no (?:despertar(?:a)?|despierte|existir|exista|estar viv[oa])|"
    r"no me importaria morir|estaria mejor si no existiera|(?:preferiria|quisiera|desearia|me gustaria) (?:no (?:despertar|existir|estar viv[oa]|seguir viv[oa])|"
    r"(?:estar|seguir) muert[oa]|morir(?:me)?)|(?:quiero|quisiera) dejar de (?:existir|vivir)|"
    r"(?:quiero|deseo) (?:morir(?:me)?|estar muert[oa])|no (?:quiero|deseo) (?:seguir )?viv(?:ir|iendo))\b"
)
# Formulaciones inequívocas de Gradiente clínico, filas 3 y 4.
# El "no" pertenece a la expresión afirmativa de estas filas.
_AFFIRMATIVE_THOUGHT = re.compile(r"\bno dejo de pensar en (?:suicidarme|quitarme la vida|matarme)\b")
_ACTIVE_THOUGHT = r"(?:pienso|he pensado|estoy pensando|sigo pensando) (?:en )?"
_ACTIVE_INTENT = r"(?:voy a|he decidido|estoy decidid[oa] a|tengo (?:la )?intencion de) "
# Ayer, hoy y las franjas de ambos días son recientes. Un pasado sin fecha
# no establece que el episodio sea remoto.
_RECENT_TIME = r"(?:hoy|ayer|anoche|esta (?:manana|tarde|noche)|ayer (?:en la|por la) (?:manana|tarde|noche))"
# El inicio en primera persona evita tomar "que intente ..." como un intento propio.
_ATTEMPT_REPORT = re.compile(
    rf"^\s*(?:si,\s*)?(?:yo\s+)?(?:{_RECENT_TIME}[, ]+)?(?:intente|empece a) {_SELF_HARM_ACTION}\b"
)
_REVIEW_PATTERNS = {
    2: re.compile(rf"\b(?:{_ACTIVE_THOUGHT}|(?:he pensado que deberia|tengo (?:ganas|pensamientos) de|quiero|quisiera|deseo|me gustaria) ){_SELF_HARM_ACTION}\b|"
                  r"\b(?:me (?:quiero|deseo) (?:matar|suicidar|quitar la vida)|tengo pensamientos suicidas)\b"),
    3: re.compile(rf"\b(?:{_ACTIVE_THOUGHT}|(?:se|ya se|he decidido) )"
                  rf"(?:como|(?:una manera|una forma|la forma) de|el metodo para) {_SELF_HARM_ACTION}\b"),
    4: re.compile(rf"\b{_ACTIVE_INTENT}{_SELF_HARM_ACTION}\b|\bme voy a (?:matar|suicidar|quitar la vida)\b"),
    5: re.compile(rf"\btengo (?:un |el |mi )?plan (?:para|de) {_SELF_HARM_ACTION}\b"),
    6: re.compile(rf"\b(?:he preparado|estoy preparando|prepare|hice (?:los )?preparativos|"
                  rf"he hecho (?:los )?preparativos)\b[^.!?]{{0,60}}\bpara {_SELF_HARM_ACTION}\b"),
    7: re.compile(rf"\b(?:acabo de intentar|hoy he intentado|hoy empece a) {_SELF_HARM_ACTION}\b|"
                  rf"\b(?:he intentado|empece a) {_SELF_HARM_ACTION} hoy\b"),
}
_REVIEW_EXCLUDED_CONTEXT = re.compile(
    r"['‘’‹›]|\b(?:ejemplos?|supongamos|imaginemos|imagina(?:te)?|digamos que|hipoteticamente|"
    r"en un caso hipotetico|(?:dice|dijo|decia|dije|diria|dijera|conto|cito|repito|niego)|"
    r"(?:cree[n]?|piensa[n]?|opina[n]?|sospecha[n]?|les? parece) que|"
    r"hace (?:(?:\w+ ){0,4}(?:tiempo|dias|semanas|meses|anos))|"
    r"la semana pasada|en (?:19|20)\d{2}|en aquel (?:entonces|momento)|"
    r"cuando (?:era|tenia|estaba)|ya no|sin (?:ganas|deseo|intencion|pensar)|"
    r"(?:matar(?:me)?|morir(?:me)?) (?:de (?:risa|verguenza|hambre)|trabajando|estudiando)|"
    r"sone|en (?:un|mi) sueno|en mis suenos|dentro de un sueno)\b"
)
_CLAUSE_BOUNDARY = re.compile(
    rf"(?<=[.!…;])\s+|(?:,\s*|\s+)(?:pero|sin embargo|en cambio|y(?= +(?:yo|{_THIRD_PERSON})\b)|"
    r"porque(?= +(?:yo +)?(?:me|tengo|intente|siento|he|quiero|deseo|estoy|pienso)\b))\b[ ,]+"
)
_NEGATION = re.compile(r"\b(?:no|nunca|jamas|tampoco|ni)\b")
_DENIED_RISK = re.compile(
    r"\b(?:no|nunca|jamas|tampoco)\b[^.!?]{0,70}\b(?:intencion|intentarlo|intentar(?:lo|me)?|"
    r"intentad[oa]|intente|suicid\w*|matarme|quitarme la vida)\b"
)
_UNSUCCESSFUL_ATTEMPT = re.compile(r"\b(?:y )?no (?:resulto|lo logre|pude hacerlo)\b")
_REPORT_TIME_QUALIFIER = re.compile(r"^\s*(?:(?:eso|esto|lo que conte)\s+)?(?:fue|ocurrio|paso|sucedio)\b")
_REVIEW_QUOTE_REQUEST = re.compile(
    r"\b(?:supongamos|imaginemos|simulemos|"
    r"(?:en|durante) (?:una|la|esta) simulacion|"
    r"(?:hagamos|practiquemos|ensayemos) (?:un |una )?(?:simulacion|juego de roles|role[ -]?play)|"
    r"(?:repite|repita|repeti) (?:esta frase|la frase|lo siguiente|despues de mi|conmigo|mis palabras)|"
    r"(?:lee|lea) (?:esta frase|la frase|lo siguiente|en voz alta)|"
    r"(?:actua|actue) como|como si fueras|"
    r"(?:lo|algo) que (?:diria|dijera) (?:otra persona|una persona|alguien))\b"
)


def requests_non_literal_speech(text):
    """Recognize an explicit request to quote, repeat, or simulate speech."""
    return bool(_REVIEW_QUOTE_REQUEST.search(normalize(text)))


def unattributed_levels(text):
    """High-specificity self-statements that can be checked without a role."""
    return tuple(sorted({level for claim in block_claims(text) for level in _claim_levels(claim)}))


def _without_affirmative_negations(claim):
    # A negation inside an affirmative passive wish is part of the evidence.
    remaining = _AFFIRMATIVE_THOUGHT.sub(" ", _PASSIVE_WISH.sub(" ", claim))
    if _ATTEMPT_REPORT.match(claim) or _REVIEW_PATTERNS[7].search(claim):
        remaining = _UNSUCCESSFUL_ATTEMPT.sub(" ", remaining)
    return remaining


def block_claims(text):
    """Keep the clauses that can contain a current own claim in a block turn."""
    normalized = normalize(text.strip())
    if not normalized or _REVIEW_QUOTE_REQUEST.search(normalized):
        return ()
    flags = {"pregunta", "cita", "referencia_a_terceros", "antecedente_temporal"}
    # Quotes and questions can span a contrast or a sentence boundary.
    if re.search(r"['‘’‹›:]", normalized) or set(context_flags(normalized)).intersection({"pregunta", "cita"}):
        return ()
    claims = []
    excluded_risk = False
    for clause in _CLAUSE_BOUNDARY.split(normalized):
        excluded_context = _REVIEW_EXCLUDED_CONTEXT.search(clause)
        if excluded_context and _REPORT_TIME_QUALIFIER.match(clause) and claims:
            # Una aclaración posterior puede fechar la afirmación inmediatamente anterior.
            claims.pop()
        if (excluded_context or set(context_flags(clause)).intersection(flags)
                or re.search(r"\bsi\b", re.sub(r"^si,\s*", "", clause))
                or _NEGATION.search(_without_affirmative_negations(clause))):
            excluded_risk |= bool(_DENIED_RISK.search(clause) or
                                  any(pattern.search(clause) for pattern in _REVIEW_PATTERNS.values()) or
                                  _ATTEMPT_REPORT.match(clause) or _PASSIVE_WISH.search(clause))
            continue
        claims.append(clause)
    # An unrelated sentence in a denial or historical report cannot inherit its signal.
    if excluded_risk:
        claims = [claim for claim in claims if _claim_levels(claim)]
    return tuple(claims)


def _claim_levels(claim):
    levels = [1] if _PASSIVE_WISH.search(claim) else []
    for level, pattern in _REVIEW_PATTERNS.items():
        matched = pattern.search(claim)
        if level == 2:
            matched = matched or _AFFIRMATIVE_THOUGHT.search(claim)
        elif level == 7:
            matched = matched or _ATTEMPT_REPORT.match(claim)
        has_intent = 4 in levels or re.search(r"\bvoy a hacerlo\b", claim)
        if matched and (level != 5 or has_intent):
            levels.append(level)
    return tuple(levels)


def explicit_denial(text):
    t = normalize(text)
    return bool(re.search(r"\b(?:no|nunca|jamas) (?:he |estoy |tengo |quiero |pienso |pensado |en |pensando |pensamientos |de |ganas |intencion |deseo ){0,7}(?:suicidar|suicidio|matarme|quitarme la vida)", t))


def expressed_time(text):
    """Solo un plazo contiguo a la declaración de intención verificada."""
    timing = r"(?:ahora(?: mismo)?|hoy|manana|esta noche)"
    intent = _REVIEW_PATTERNS[4].pattern
    normalized = normalize(text)
    match = re.search(rf"(?:{intent})\s+({timing})\b", normalized)
    if match:
        return match[1].replace("manana", "mañana")
    match = re.search(rf"\b({timing})[, ]+(?:{intent})", normalized)
    return match[1].replace("manana", "mañana") if match else None


def evidence_dimensions(text, context=""):
    """Do not let generic NLI invent a method, intention, plan, or action.

    These conservative lexical gates are experimental, not a clinical instrument.
    Missing explicit evidence means abstention, even for a high model score.
    """
    t = normalize(text)
    domain = bool(re.search(r"suicid|quitar.{0,12}vida|matarme|(?:dejar de|no quiero) vivir|morir|muert", normalize(text + " " + context)))
    intent = bool(re.search(r"intencion|(?:voy|quiero|decidido) a (?:hacerlo|actuar)|decidid[oa]|voy a terminar haciendolo|podria hacerlo|poder detenerme|siento que voy a actuar", t))
    direct_levels = unattributed_levels(text)
    domain = domain or 4 in direct_levels
    intent = (intent or 4 in direct_levels) and not re.search(r"\b(?:no|sin|ninguna|nunca)\s+(?:tengo |hay |tiene |ninguna )?intencion\b", t)
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
    direct = unattributed_levels(text)
    literal = set(literal_candidates(text)).union(direct)
    # A denial of active ideation can coexist with a passive death wish.
    if denied:
        literal = [level for level in literal if level == 1]
    dimensions = evidence_dimensions(text, context)
    result = []
    for category, value, supported in zip(matrix["categories"], values, supported_values):
        level = category["level"]
        if level == 0 or (denied and level not in literal) or not supported:
            continue
        if level >= 3 and not dimensions[level] and level not in direct:
            continue
        result.append({"category_id": category["id"], "category": category["name"],
                       "matrix_level": level, "source": category["source"],
                       "score": round(value, 4), "score_kind": score_kind,
                       "basis": "regla y modelo" if level in literal else "modelo",
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


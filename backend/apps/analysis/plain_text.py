"""Chronological evidence spans independent of acoustic speaker labels."""
from bisect import bisect_right
import re

from .domain import EvidenceIssue, Signal
from .rules import MATRIX, explicit_denial, requests_non_literal_speech, review_priority, unattributed_levels

PLAIN_TEXT_VERSION = "bloque-texto-1"
PAUSE_SECONDS = 1.2
CONTEXT_CHARS = 300
SENTENCE_END = re.compile(r'[.!?…][»”\"]*$')
TEXT_BOUNDARY = re.compile(
    r'(?<=[.!?…;])\s+|(?<=[.!?…][»”\"])\s+|'
    r'(?:,\s*|\s+)(?=(?:pero|aunque|sin embargo|en cambio|además|por otra parte)\b|'
    r'y\s+(?:también\s+)?(?=(?:yo|hoy|ayer|anoche|pienso|ojalá|he pensado|intenté|'
    r'me (?:quiero|voy a)|tengo (?:la )?(?:intención|pensamientos|un plan)|'
    r'hice preparativos|no (?:quiero|he pensado))\b))',
    re.IGNORECASE,
)


def text_segments(words, origin, redact):
    """Split at pauses and textual boundaries while retaining word timestamps."""
    segments, run, offsets = [], [], []
    length = 0

    def flush():
        if not run:
            return
        text = " ".join(word["text"] for word in run)
        start = 0
        for left, right in [(m.start(), m.end()) for m in TEXT_BOUNDARY.finditer(text)] + [(len(text), len(text))]:
            excerpt = " ".join(redact(text[start:left].strip()).split())
            if excerpt:
                first = bisect_right(offsets, start)
                last = bisect_right(offsets, left - 1)
                segments.append({"text": excerpt, "start": run[first]["start"] + origin,
                                 "end": max(word["end"] for word in run[first:last + 1]) + origin})
            start = right
        run.clear()
        offsets.clear()

    previous_end = None
    for word in sorted(words, key=lambda item: (item["start"], item["end"])):
        text = word["text"].strip()
        if not text:
            continue
        if previous_end is not None and word["start"] - previous_end >= PAUSE_SECONDS:
            flush()
            length = 0
            previous_end = None
        length += len(text)
        offsets.append(length)
        run.append(dict(word, text=text))
        length += 1
        previous_end = max(previous_end, word["end"]) if previous_end is not None else word["end"]
    flush()
    return segments


def join_previous(segments, previous, boundary):
    if not segments or not previous or boundary is None:
        return segments
    last = previous[-1]
    first = segments[0]
    # Only connect consecutive audio at the capture boundary. The prior span
    # can be context or the unfinished beginning of the first new sentence.
    if not (last["end"] <= boundary <= first["start"]
            and first["start"] - last["end"] < PAUSE_SECONDS):
        return segments
    if not last.get("confirmed") and not last["text"].startswith("¿") and not SENTENCE_END.search(last["text"]):
        return [{"text": f'{last["text"]} {first["text"]}', "start": last["start"], "end": first["end"]},
                *segments[1:]]
    return [last, *segments]


def plain_signals(fragment, segments, decision, threshold):
    signals, issues = [], []
    boundary = fragment.new_audio_start_sample
    for index, segment in enumerate(segments):
        start, end = segment["start"], segment["end"]
        if boundary is not None and end <= boundary / 16000:
            continue
        text = segment["text"]
        before = segments[index - 1]["text"] if index else ""
        after = segments[index + 1]["text"] if index + 1 < len(segments) else ""
        if (text.startswith(("¿", "«", "“", '"')) or text.endswith("?") or requests_non_literal_speech(text)
                or requests_non_literal_speech(before) or (explicit_denial(text) and not unattributed_levels(text))):
            continue
        answer = decision.text_evidence.get(f"t{index}", {})
        choice, score = answer.get("choice"), answer.get("score")
        level = int(choice[-1]) if choice and choice.startswith("nivel_") else None
        if score is None or choice == "indeterminado" or (choice == "ninguna" and score < .55):
            issues.append(EvidenceIssue("JEV_EVIDENCE_UNCERTAIN", start, end))
        elif level is not None and score < threshold:
            issues.append(EvidenceIssue("JEV_BELOW_THRESHOLD", start, end, level))
        elif level is not None:
            signals.append(Signal(MATRIX["categories"][level]["id"], level, review_priority(level), text,
                                  start, end, None, score, threshold,
                                  before[-CONTEXT_CHARS:], after[:CONTEXT_CHARS]))
    return tuple(signals), tuple(issues)

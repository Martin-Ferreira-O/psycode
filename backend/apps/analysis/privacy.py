"""Redacción adaptada del prototipo; no garantiza anonimización."""
import re

def redact(text, terms=()):
    # Best effort, not de-identification. Names/addresses require a local list.
    for term in sorted(terms, key=len, reverse=True):
        text = re.sub(re.escape(term), "[IDENTIFICADOR]", text, flags=re.IGNORECASE)
    for pattern, label in [
        (r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        (r"(?<!\w)(?:\d{1,2}\.\d{3}\.\d{3}|\d{7,8})-[\dkK]\b", "[RUT]"),
        (r"(?<!\w)(?:\+?56[\s-]*)?(?:9|2)(?:[\s-]*\d){8}(?!\d)", "[TELEFONO]"),
    ]:
        text = re.sub(pattern, label, text)
    return text


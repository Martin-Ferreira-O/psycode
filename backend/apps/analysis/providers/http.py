"""Bounded HTTP retries; never expose response bodies or request payloads."""
import time
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


from ..errors import ProviderError, SubmissionUncertain


def request(client, method, url, *, attempts=3, safe=True, sleep=time.sleep,
            deadline=None, accepted_statuses=(), **kwargs):
    for attempt in range(attempts):
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError("Tiempo máximo del proveedor agotado")
            kwargs["timeout"] = min(30., remaining)
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if not safe and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                raise SubmissionUncertain("Envío incierto; requiere reconciliación antes de repetir") from None
            if attempt == attempts - 1:
                raise ProviderError("Proveedor sin conexión") from None
            delay = 2 ** attempt
        else:
            if (response.is_success or response.status_code in accepted_statuses
                    or (method == "DELETE" and response.status_code in {404, 410})):
                return response
            # A rate-limit refusal did not create a job. Ambiguous 5xx POSTs
            # must not be retried, because Batch has no idempotency guarantee.
            if not safe and (response.status_code == 408 or response.status_code >= 500):
                raise SubmissionUncertain("Envío incierto; requiere reconciliación antes de repetir")
            if response.status_code not in {429, 500, 502, 503, 504, 529} or attempt == attempts - 1:
                raise ProviderError(f"Proveedor respondió HTTP {response.status_code}")
            try:
                delay = float(response.headers.get("retry-after", 2 ** attempt))
            except ValueError:
                try:
                    retry_time = parsedate_to_datetime(response.headers["retry-after"])
                    delay = (retry_time - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, KeyError, TypeError):
                    delay = 2 ** attempt
            if not math.isfinite(delay) or delay > 30:
                raise ProviderError("Proveedor requiere una espera mayor; reintento suspendido")
            delay = max(0., delay)
        if deadline is not None and time.monotonic() + delay >= deadline:
            raise ProviderError("Tiempo máximo del proveedor agotado")
        sleep(delay)
    raise ProviderError("Proveedor no disponible")


def json_body(response):
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except ValueError:
        raise ProviderError("Respuesta del proveedor inválida") from None

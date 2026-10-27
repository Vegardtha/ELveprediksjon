"""GET med nye forsøk ved nettverksfeil, 429 og 5xx (f.eks. TLS-timeout fra delte GitHub-runnere)."""
import time

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


def get(url: str, attempts: int = 5, **kwargs) -> httpx.Response:
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            r = httpx.get(url, **kwargs)
        except httpx.TransportError:
            if last:
                raise
        else:
            if r.status_code not in RETRY_STATUS or last:
                r.raise_for_status()
                return r
        time.sleep(min(5 * 2 ** attempt, 60))
    raise AssertionError("unreachable")

"""HTTP fetching: retries, politeness, and accounting.

Every request goes through `Fetcher.get`, which counts requests and bytes so each
run can report what it cost. Knowing the cost matters here — one of the sources
looks cheap by request count and expensive by wall time, and you only notice if
you measure.
"""

import gzip
import io
import time
import urllib.error
import urllib.parse
import urllib.request

import config


class FetchError(Exception):
    """Raised when a URL could not be retrieved after retries."""


class Fetcher:
    def __init__(self, delay=None, timeout=None):
        self.delay = config.REQUEST_DELAY if delay is None else delay
        self.timeout = config.REQUEST_TIMEOUT if timeout is None else timeout
        self.requests = 0
        self.bytes = 0
        self._last_host = None
        self._last_at = 0.0

    # ── politeness ────────────────────────────────────────────────────────────
    def _wait(self, host):
        if host == self._last_host:
            gap = time.monotonic() - self._last_at
            if gap < self.delay:
                time.sleep(self.delay - gap)
        self._last_host = host
        self._last_at = time.monotonic()

    # ── fetching ──────────────────────────────────────────────────────────────
    def get(self, url, headers=None, expect=None):
        """GET a URL and return the decoded body as text.

        `expect` is an optional (status,) tuple of acceptable codes; anything else
        raises FetchError rather than silently returning an error page. Several of
        these sites answer a bad request with HTTP 200 and a valid-looking envelope
        containing nothing, so status alone is never the whole check — but a status
        that is plainly wrong should still stop us.
        """
        hdrs = {
            "User-Agent": config.USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-GB,en;q=0.9",
        }
        if headers:
            hdrs.update(headers)

        host = urllib.parse.urlsplit(url).netloc
        last_err = None

        for attempt in range(config.MAX_RETRIES):
            self._wait(host)
            req = urllib.request.Request(url, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    self.requests += 1
                    self.bytes += len(raw)
                    if resp.headers.get("Content-Encoding") == "gzip":
                        try:
                            raw = gzip.decompress(raw)
                        except OSError:
                            pass
                    if expect and resp.status not in expect:
                        raise FetchError(f"{resp.status} from {url}")
                    return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                self.requests += 1
                self.bytes += len(e.read() or b"")
                last_err = f"HTTP {e.code}"
                # 4xx will not improve with a retry
                if 400 <= e.code < 500:
                    raise FetchError(f"HTTP {e.code} from {url}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = str(e)

            if attempt < config.MAX_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))

        raise FetchError(f"failed after {config.MAX_RETRIES} attempts: {last_err} ({url})")

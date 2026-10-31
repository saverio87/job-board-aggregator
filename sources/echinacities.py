"""jobs.echinacities.com — PHP + Vue, whole result set embedded as a JS variable.

Same trick as several modern sites: the data is not in the visible markup, which
is what makes it easy to misread as "loaded by JavaScript, needs a browser." It is
in fact sitting in the HTML as `var _searchJobList = {...}`.

This board also has something none of the others do — a **30/90-day recency
filter** in its search UI. The parameter for it was not identified, so we fetch
broad and filter locally, which is what we do everywhere else anyway.

Pagination is the trap here. `page`, `p`, `pageNum` and `page_no` are all silently
ignored and return the same 25 jobs. The real parameter is `per_page`, and it is an
**offset**, not a page size: `per_page=50` means "skip the first fifty". The name is
actively misleading because the same page has a genuine 25/50 results-per-page
selector next to it.
"""

import html
import json
import re
from datetime import datetime

from core.guards import check_nonempty, check_pages_differ, check_totals
from core.model import Job
from sources.base import Source as BaseSource

SEARCH = "https://jobs.echinacities.com/jobs/search/"
DETAIL = "https://jobs.echinacities.com/jobchapter/"

PAGE_SIZE = 25
MAX_OFFSET = 200

# The search is full-text with roughly 7% precision on our category — 182 hits for
# "computer science" narrowing to 13 real matches. Treat it purely as a candidate
# generator.
#
# Two keywords, not five. More terms mostly re-fetch the same jobs (the results
# overlap heavily) and this host rate-limits: a five-keyword run drew HTTP 403
# after about fourteen requests. Partial coverage with an honest warning beats
# being blocked outright, and the tag filter does the real narrowing anyway.
KEYWORDS = ["computer", "ICT"]

_payload = re.compile(r"var _searchJobList\s*=\s*(\{.*?\})\s*;", re.S)

# 服务器负载过高，请稍后重试 — returned with HTTP 200 and content-type text/plain.
THROTTLE = "服务器负载过高"


def _clean(s):
    s = html.unescape(s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def _parse_refresh(text, now=None):
    """refresh_time arrives as "Oct 30" with no year. Infer it.

    If the day/month is in the future relative to today, it belongs to last year —
    otherwise "Dec 28" read in January would be dated eleven months ahead.
    """
    now = now or datetime.now()
    try:
        dt = datetime.strptime(text.strip(), "%b %d")
    except (ValueError, AttributeError):
        return ""
    year = now.year if dt.replace(year=now.year) <= now else now.year - 1
    return dt.replace(year=year).date().isoformat()


class Source(BaseSource):
    id = "echinacities"
    name = "eChinaCities Jobs"
    homepage = "https://jobs.echinacities.com"

    def fetch(self, http, result):
        seen = set()

        for kw in KEYWORDS:
            prev_ids = []
            kw_reported = 0
            kw_ids = set()
            offset = 0
            while offset <= MAX_OFFSET:
                url = f"{SEARCH}?employeeId=0&keyword={kw}&lang=en"
                if offset:
                    # Despite the name this is an offset, not a page size.
                    url += f"&per_page={offset}"
                try:
                    body = http.get(url)
                except Exception as e:
                    result.warn(f"keyword '{kw}' offset {offset}: {e}")
                    break

                m = _payload.search(body)
                if not m:
                    # This host throttles with HTTP 200 and a plain-text message
                    # rather than a 4xx: "服务器负载过高，请稍后重试" (server load too
                    # high). A status-code check would sail straight past it.
                    if THROTTLE in body:
                        result.warn(
                            f"keyword '{kw}' offset {offset}: server asked us to back "
                            f"off (load too high) — not resuming this run"
                        )
                    elif len(body) < 2000:
                        result.warn(
                            f"keyword '{kw}' offset {offset}: tiny non-page response "
                            f"({len(body)} bytes, {body.strip()[:60]!r})"
                        )
                    else:
                        result.warn(f"keyword '{kw}' offset {offset}: no payload found")
                    break

                try:
                    data = json.loads(m.group(1)).get("data") or {}
                except json.JSONDecodeError:
                    result.warn(f"keyword '{kw}' offset {offset}: malformed payload")
                    break

                if offset == 0:
                    kw_reported = data.get("num") or 0

                rows = data.get("list") or []
                if not rows:
                    break

                ids = []
                for r in rows:
                    jid = str(r.get("id") or "")
                    if not jid:
                        continue
                    ids.append(jid)
                    kw_ids.add(jid)
                    if jid in seen:
                        continue
                    seen.add(jid)
                    result.jobs.append(Job(
                        source=self.id,
                        src_job_id=jid,
                        title=_clean(r.get("title")),
                        employer=_clean(r.get("company_name")),
                        location_raw=_clean(r.get("city")),
                        location_city=_clean(r.get("city")),
                        salary_raw=_clean(r.get("salaryRmb") or r.get("salary")),
                        posted_at=_parse_refresh(r.get("refresh_time")),
                        description_html=_clean(r.get("description")),
                        url=DETAIL + jid,
                        raw_json=json.dumps({
                            k: r.get(k) for k in
                            ("id", "job_type", "tage", "sktag", "refresh_time")
                        }),
                    ))

                if not check_pages_differ(prev_ids, ids, offset, result):
                    break
                prev_ids = ids

                if len(rows) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

            # Per keyword, `num` is a genuine total for that query, so the
            # comparison means something. Across keywords it does not: the union
            # of five searches is smaller than the sum of their five counts.
            check_totals(len(kw_ids), kw_reported, result, f"hits for '{kw}'")

        result.reported = 0
        result.collected = len(result.jobs)
        check_nonempty(result.collected, result)
        return result

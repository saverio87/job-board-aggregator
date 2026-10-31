"""echinacareers.com — HTML fragments, one big employer, no dates at all.

Transport is the worst of the four: everything returns `text/html`, there is no
JSON anywhere, and the list endpoint ignores the `employerID` parameter entirely
(six spellings tried, all ignored; the site's search is effectively hardcoded to
one employer).

So we go the other way round: enumerate employers from the sitemap, then read each
employer's profile, which inlines that employer's *entire* job list. One request
per employer for everything they have.

Two things worth knowing before touching this:

* **97.9% of the board is one employer.** empID 1521 (China Global Connections)
  holds ~1,011 of 1,027 jobs. The other 99 employers share about 22 between them,
  and in sampling every one of them returned zero. Hence the wall-time profile:
  ~100 requests, ~2.5 MB, 4-5 minutes, almost all of it spent on employers who
  have nothing. This is the source that most wants its own cadence.

* **No dates in the list data.** `first_seen` is the only way to know a job here
  is new.
"""

import html
import json
import re

from core.guards import check_nonempty
from core.model import Job
from sources.base import Source as BaseSource

BASE = "https://www.echinacareers.com"
SITEMAP = BASE + "/Home/SiteMap"
PROFILE = BASE + "/Home/CompanyProfile?empID={}&isPartial=true"

MAX_EMPLOYERS = 150

_emp = re.compile(r"empID=(\d+)")
_call = re.compile(r'AJAXJobFetch\((\d+),\s*(\d+),\s*"([^"]*)"')
_vacancies = re.compile(r'id="jobs-available"[^>]*>([\d,]+)<', re.I)


def _span(name, chunk):
    m = re.search(r'class="job-' + name + r'">(.*?)</span>', chunk, re.S)
    return m.group(1) if m else ""


def _clean(s):
    # This site double-escapes descriptions and its titles carry entities.
    # Unescape twice, strip tags, collapse whitespace.
    s = html.unescape(html.unescape(s or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


class Source(BaseSource):
    id = "echinacareers"
    name = "eChinaCareers"
    homepage = BASE

    def fetch(self, http, result):
        try:
            sm = http.get(SITEMAP)
        except Exception as e:
            result.fail(f"sitemap: {e}")
            return result

        employers = sorted(set(_emp.findall(sm)))[:MAX_EMPLOYERS]
        if not employers:
            result.fail("no employer ids found on the sitemap")
            return result

        total_reported = 0
        empty = 0

        for emp in employers:
            try:
                page = http.get(PROFILE.format(emp))
            except Exception as e:
                result.warn(f"empID {emp}: {e}")
                continue

            vac = _vacancies.search(page)
            if vac:
                total_reported += int(vac.group(1).replace(",", ""))

            calls = list(_call.finditer(page))
            if not calls:
                empty += 1
                continue

            # The card's spans follow its onclick handler, so slice the page at
            # each handler and read the spans inside that slice.
            for i, m in enumerate(calls):
                jid, employer_id, onclick_title = m.group(1), m.group(2), m.group(3)
                end = calls[i + 1].start() if i + 1 < len(calls) else len(page)
                chunk = page[m.end():end]

                title = _clean(_span("title", chunk)) or _clean(onclick_title)
                result.jobs.append(Job(
                    source=self.id,
                    src_job_id=jid,
                    title=title,
                    employer=_clean(_span("employer-name", chunk)),
                    src_employer_id=employer_id,
                    location_raw=_clean(_span("location", chunk)),
                    url=f"{BASE}/Jobs/ViewSingleJob2?jobID={jid}&employerID={employer_id}",
                    raw_json=json.dumps({"empID": employer_id}),
                ))

        result.reported = total_reported
        result.collected = len(result.jobs)
        result.note(f"{empty}/{len(employers)} employers had no jobs")
        check_nonempty(result.collected, result)
        if total_reported and result.collected < total_reported:
            result.warn(
                f"{result.collected} job rows against {total_reported} advertised vacancies"
            )
        return result

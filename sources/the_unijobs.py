"""timeshighereducation.com/unijobs — the best-structured of the four.

Runs on Madgex, a job-board platform, so these findings should transfer to other
Madgex boards. Browse by *discipline facet*, not keyword: the facet is structured
and complete for the discipline, while the keyword search over-matches (66 keyword
hits for Computer Science in China against 44 actual CS-classified jobs).

The listing cards are complete — title, employer, location, salary and a
description snippet — so no per-job detail fetch is needed.

Two traps: the RSS feed is capped at 20 items while declaring its true total in
`<opensearch:totalResults>`, and `sort=Date` must be capitalised (lowercase is
silently ignored and stays on Relevance).
"""

import html
import json
import re

from core.guards import check_pages_differ, check_totals
from core.model import Job
from sources.base import Source as BaseSource

SEARCH = "https://www.timeshighereducation.com/unijobs/searchjobs/"

# AcademicDiscipline facet values, read off the site's own checkboxes.
DISCIPLINES = {5: "Computer Science", 9: "Engineering & Technology"}

# We browse Computer Science only. Engineering & Technology is 315 jobs and
# mostly chemical, civil and mechanical.
QUERY_DISCIPLINES = [5]

MAX_PAGES = 25

_item = re.compile(r'<li class="lister__item.*?(?=<li class="lister__item|</ul>)', re.S)
_jid = re.compile(r'id="item-(\d+)"')
_href = re.compile(r'<h3[^>]*>\s*<a\s+href="([^"]+)"', re.S)
_title = re.compile(r'<h3[^>]*>.*?<span>(.*?)</span>', re.S)
_desc = re.compile(r'lister__description[^>]*>(.*?)</p>', re.S)
_returned = re.compile(r"'returned\\x2dresults':\s*'([^']*)'")


def _meta(name, block):
    m = re.search(r'lister__meta-item--' + name + r'">(.*?)</li>', block, re.S)
    return m.group(1) if m else ""


def _clean(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or ""))).strip()


class Source(BaseSource):
    id = "the_unijobs"
    name = "THE UniJobs"
    homepage = "https://www.timeshighereducation.com/unijobs/"

    def fetch(self, http, result):
        total_reported = 0

        for disc in QUERY_DISCIPLINES:
            prev_ids = []
            for page in range(1, MAX_PAGES + 1):
                url = f"{SEARCH}?AcademicDiscipline={disc}&sort=Date&page={page}"
                try:
                    body = http.get(url)
                except Exception as e:
                    result.warn(f"discipline {disc} page {page}: {e}")
                    break

                m = _returned.search(body)
                if m and page == 1:
                    total_reported += int(m.group(1) or 0)

                blocks = _item.findall(body)
                if not blocks:
                    break

                ids = []
                for b in blocks:
                    jid = _jid.search(b)
                    if not jid:
                        continue
                    jid = jid.group(1)
                    ids.append(jid)

                    href = _href.search(b)
                    ttl = _title.search(b)
                    dsc = _desc.search(b)

                    result.jobs.append(Job(
                        source=self.id,
                        src_job_id=jid,
                        title=_clean(ttl.group(1)) if ttl else "",
                        employer=_clean(_meta("recruiter", b)),
                        location_raw=_clean(_meta("location", b)),
                        salary_raw=_clean(_meta("salary", b)),
                        # The description snippet is real text from the ad and is
                        # what a classifier would use later. Keep it.
                        description_html=_clean(dsc.group(1)) if dsc else "",
                        url=("https://www.timeshighereducation.com" + href.group(1)
                             if href else ""),
                        raw_json=json.dumps({"discipline": DISCIPLINES.get(disc, disc)}),
                    ))

                # A page parameter that parses and is then ignored returns page one
                # forever. Stop rather than loop to MAX_PAGES collecting duplicates.
                if not check_pages_differ(prev_ids, ids, page, result):
                    break
                prev_ids = ids

                if len(ids) < 20:
                    break

        result.reported = total_reported
        result.collected = len(result.jobs)
        check_totals(result.collected, result.reported, result, "Computer Science jobs")
        return result

"""eslcafe.com — the one true JSON API of the four.

Clean, unauthenticated, well-shaped. Also the emptiest for our category: about one
relevant job across 304. Kept because the adapter is nearly free and this board is
where ESL/English teaching roles live, should a second dashboard ever want them.

Two traps, both recorded in the registry and both handled here:

* omit `jobType` and you get HTTP 200 with **zero rows** — indistinguishable from
  a quiet day. Always send it.
* omit `sortColumn`/`sortType` and you get a 500 with a full .NET stack trace.
"""

import json

from core.model import Job
from sources.base import Source as BaseSource

API = "https://www.eslcafe.com/api/list/PostAJobList"
DETAIL = "https://www.eslcafe.com/postajob-detail/"

BOARDS = ["china", "korea", "international"]
JOB_TYPES = [1, 2]        # 1 = regular, 2 = sponsored


class Source(BaseSource):
    id = "eslcafe"
    name = "ESL Cafe"
    homepage = "https://www.eslcafe.com"

    def fetch(self, http, result):
        total_reported = 0
        for board in BOARDS:
            for job_type in JOB_TYPES:
                url = (
                    f"{API}?jobBoardSlug={board}&jobType={job_type}"
                    f"&sortColumn=SortOrder&sortType=asc&page=1&size=1000"
                )
                try:
                    data = json.loads(http.get(url))
                except Exception as e:
                    result.warn(f"{board}/jobType={job_type}: {e}")
                    continue

                if not data.get("success"):
                    result.warn(f"{board}/jobType={job_type}: success=false")
                    continue

                page = data.get("paging") or {}
                total_reported += page.get("total") or 0

                rows = data.get("data") or []
                if not rows and page.get("total"):
                    # The silent-zero trap: a valid envelope reporting a non-zero
                    # total but carrying no rows means the request was malformed.
                    result.warn(
                        f"{board}/jobType={job_type}: reported total "
                        f"{page.get('total')} but returned no rows"
                    )

                for r in rows:
                    slug = r.get("slug") or ""
                    if not slug:
                        continue
                    result.jobs.append(Job(
                        source=self.id,
                        src_job_id=slug,
                        title=r.get("jobTitle") or "",
                        employer=r.get("company") or "",
                        posted_at=(r.get("statusStartDate") or "")[:19],
                        url=DETAIL + slug,
                        raw_json=json.dumps(r),
                    ))

        result.reported = total_reported
        result.collected = len(result.jobs)
        return result

"""The common record every adapter produces, and the per-source run result."""

import hashlib
import re
from dataclasses import dataclass, field


_ws = re.compile(r"[^a-z0-9]+")


def _norm(s):
    return _ws.sub(" ", (s or "").lower()).strip()


def dedupe_key(title, employer, location=""):
    """A cross-source fingerprint.

    The same job can appear on more than one board, and per-source IDs will never
    catch that. Normalising title + employer + location catches the common case
    where one board copies another's title verbatim.

    Location is not optional in practice. One agency on echinacareers advertises
    fifteen distinct roles all titled "Computer Science Teacher"; on title and
    employer alone those collapse into a single key and fourteen real jobs look
    like duplicates of each other. Adding the city separates them.

    Even so, treat a shared key as a *suggestion*, never as permission to hide a
    row. Grouping is for annotation ("also listed on X"), not for dropping jobs.
    """
    basis = f"{_norm(title)}|{_norm(employer)}|{_norm(location)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class Job:
    source: str
    src_job_id: str
    title: str
    employer: str = ""
    src_employer_id: str = ""
    location_raw: str = ""
    location_country: str = ""
    location_city: str = ""
    salary_raw: str = ""
    posted_at: str = ""          # the source's own date, if it has one
    url: str = ""
    apply_url: str = ""
    description_html: str = ""
    tags_subject: list = field(default_factory=list)
    tags_role: list = field(default_factory=list)
    raw_json: str = ""

    def dedupe_key(self):
        return dedupe_key(self.title, self.employer, self.location_raw)


@dataclass
class SourceResult:
    """What one adapter's run cost and found.

    `reported` is the count the source itself claims. Comparing it against
    `collected` catches silent truncation, which is the single most common way
    these sites fail: two of them return page one for every page number while
    cheerfully reporting a full total.
    """
    source: str
    jobs: list = field(default_factory=list)
    requests: int = 0
    bytes: int = 0
    collected: int = 0
    reported: int = 0
    status: str = "ok"           # ok | warn | error
    notes: list = field(default_factory=list)

    def note(self, msg):
        self.notes.append(msg)

    def warn(self, msg):
        self.notes.append(msg)
        if self.status == "ok":
            self.status = "warn"

    def fail(self, msg):
        self.notes.append(msg)
        self.status = "error"

    def summary(self):
        bits = [f"{self.requests} req", f"{self.bytes / 1024:.0f} KB"]
        if self.reported:
            bits.append(f"{self.collected}/{self.reported} reported")
        else:
            bits.append(f"{self.collected} collected")
        return " · ".join(bits)

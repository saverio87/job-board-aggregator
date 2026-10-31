"""Configuration: sources to run, and the dashboards rendered from the corpus.

A *dashboard* is just a filter over the stored corpus. Scraping and viewing are
deliberately separate: the fetcher stores everything a source's list endpoint will
give it, and each dashboard picks out what it cares about. Adding a maths-teaching
dashboard later is an entry in DASHBOARDS, not a new scraper.
"""

# ── Sources ───────────────────────────────────────────────────────────────────
# teast.co is deliberately excluded: it is itself an aggregator that scrapes other
# boards (its payload carries `scrapedFrom: "ESL Cafe"`), so ingesting it would
# duplicate sources we already fetch directly.

ENABLED_SOURCES = [
    "eslcafe",
    "the_unijobs",
    "echinacareers",
    "echinacities",
]

# Per-source cadence, in days. The runner skips a source whose last successful run
# is younger than this. Daily everywhere for now; echinacareers costs 100 requests
# and ~4-5 minutes, mostly spent on 99 employers that have no jobs, so it is the
# first candidate for a longer interval.
CADENCE_DAYS = {
    "eslcafe": 1,
    "the_unijobs": 1,
    "echinacareers": 1,
    "echinacities": 1,
}

# ── Tag vocabulary ────────────────────────────────────────────────────────────
# A job matches when it hits one SUBJECT term AND one ROLE term. One flat keyword
# list is too blunt: "Computer Science Teacher" should match, "Software Engineer"
# should not (no role), "English Teacher" should not (no subject).

SUBJECT_TERMS = [
    {"p": r"computer science"},
    {"p": r"comput(er|ing)s?"},
    {"p": r"\bict\b"},
    # Uppercase IT only. Case-insensitively, "it" is one of the commonest words in
    # English and would match half the board.
    {"p": r"\bIT\b", "cs": True},
    {"p": r"information technology"},
    {"p": r"coding"},
    {"p": r"programming"},
    {"p": r"software"},
    {"p": r"robotics"},
    {"p": r"digital literacy"},
    {"p": r"edtech"},
    {"p": r"informatics"},
    {"p": r"\bstem\b"},
    {"p": r"\bsteam\b"},
    {"p": r"design (and|&) technology"},
    {"p": r"data science"},
    # Leading word boundary, no trailing one: catches data, database, datasets,
    # data-driven; excludes metadata, where "data" sits mid-word.
    {"p": r"\bdata"},
]

ROLE_TERMS = [
    {"p": r"\bteach(er|ing|ers)\b"},
    {"p": r"\binstructor"},
    {"p": r"\blecturer"},
    {"p": r"\btutor"},
    {"p": r"\bfaculty\b"},
    {"p": r"\bprofessor"},
    {"p": r"\beducator"},
    {"p": r"\bhead of\b"},
]

# ── Dashboards ────────────────────────────────────────────────────────────────
# Each dashboard renders to docs/<slug>/ as index.html + jobs.json.

DASHBOARDS = {
    "cs-ict-teaching": {
        "title": "CS & ICT Teaching Jobs",
        "subtitle": (
            "Computer science, ICT and adjacent subjects, scraped daily from four "
            "job boards. Bodies are not stored; each row links to the original ad."
        ),
        "subject_terms": SUBJECT_TERMS,
        "role_terms": ROLE_TERMS,
        # Show only jobs still appearing at the source.
        "active_only": True,
    },
}

# ── Fetching ──────────────────────────────────────────────────────────────────

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Seconds between requests to the same host. These are small boards being polled
# daily by one person; there is no reason to hurry and every reason not to.
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3

# Per-source overrides. echinacities started returning HTTP 403 after roughly
# fourteen quick requests in one run, so it gets a longer gap and a shorter
# keyword list. Being asked to slow down is a message worth taking literally.
SOURCE_DELAY = {
    "echinacities": 2.0,
}

# Fetch full job bodies for matched jobs. Off by default: the list endpoints
# already give title, employer and location, which is a complete dashboard row,
# and each body costs one request per job.
FETCH_BODIES = False

DB_PATH = "data/jobs.db"
DOCS_DIR = "docs"

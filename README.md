# Job Board Aggregator

Scrapes computer-science and ICT teaching jobs from four public job boards daily,
stores them in SQLite, and publishes a static dashboard you can open from anywhere.

Python 3.9+ and the standard library. No dependencies to install.

```
python3 run.py all --publish     # fetch, build, publish
python3 run.py fetch --force     # fetch regardless of per-source cadence
python3 run.py build             # render dashboards from what is stored
python3 run.py status            # last run per source, with warnings
python3 run.py tags --title "Secondary Computer Science Teacher"
```

## Layout

```
config.py          sources on/off, cadence, tag vocabulary, dashboards
core/
  http.py          retries, politeness, per-source delay, request/byte accounting
  model.py         the common record + the cross-source dedupe key
  store.py         SQLite schema, upsert, retirement, run history
  tags.py          subject ∧ role matching
  guards.py        the integrity checks
sources/           one adapter per board
render.py          static HTML + JSON per dashboard
run.py             entry point
data/jobs.db       the corpus (gitignored)
docs/              published output (committed)
  index.html       the dashboard
  jobs.json        the same records, for anything that wants to read them
```

## How it works

Each source adapter returns records in one common shape. Everything reusable —
retries, politeness, tag matching, storage, retirement, and the integrity checks —
lives in `core/`, so an adapter only has to know its endpoints and its traps.

**Scraping and viewing are separate.** The fetcher stores everything a source's
list endpoint will give it; a dashboard is a *filter over that corpus*. Matching
happens at read time, not write time, so adding a tag works over the whole history
immediately rather than only on jobs scraped after the change.

**Job bodies are not fetched.** The list endpoints already give title, employer and
location, which is a complete dashboard row, and each body would cost one request
per job. Every row links to the original advertisement instead. Turn it on with
`FETCH_BODIES` if you want the text stored.

## The sources

| Source | Transport | Yield | Notes |
|---|---|---|---|
| THE UniJobs | JSON embedded in page | 196 | Browsed by discipline facet, not keyword |
| eChinaCareers | HTML fragments | 1,027 | 96% one employer; no dates at all |
| ESL Cafe | JSON API | 306 | Cleanest API, emptiest for this category |
| eChinaCities | JSON in a JS variable | ~220 | Rate-limits; see below |

teast.co is deliberately excluded: it is itself an aggregator (its payload carries
`scrapedFrom: "ESL Cafe"`), so ingesting it would duplicate sources we already
fetch directly.

Full endpoint detail, parameters and pitfalls: `source-registry.md`.

## What the guards are for

Every one of these exists because a source failed this way *silently*.

- **`check_pages_differ`** — a page parameter that parses and is then ignored
  returns page one forever. Two sources do this. Identical ids on consecutive pages
  is the tell, and the run stops rather than collecting duplicates to the end.
- **`check_totals`** — compares what we collected against what the source says
  exists. THE's RSS publishes its own true total in `<opensearch:totalResults>`
  while returning 20 of 66 items. Free to check, because the number is already in
  the payload.
- **`check_nonempty`** — a run returning nothing is not a day with no new jobs.
  Omitting one parameter on the ESL Cafe API yields HTTP 200, a valid envelope and
  zero rows.
- **Retirement only on a clean run** — the pass that marks vanished jobs inactive
  is skipped unless the fetch was verified. A truncated fetch would otherwise
  delist everything past page one.
- **Cadence measured against the last *successful* run** — a failed attempt must
  not buy a source a day of silence before it is retried.

A source that errors makes the run exit non-zero, so a scheduled job surfaces the
failure rather than passing quietly. The dashboard also renders a **fetch health**
strip, because a truncated run otherwise looks exactly like a quiet week.

## Adding a source

1. Write `sources/yoursite.py` implementing `fetch(self, http, result)`, appending
   `Job` records and setting `result.reported` when the site publishes a total.
2. Add its id to `ENABLED_SOURCES` in `config.py`.
3. Register the class in `sources/__init__.py`.

Use the guards. If the site paginates, call `check_pages_differ`. If it reports a
total, call `check_totals`.

## Adding a dashboard

A dashboard is a filter, not a scraper. Add an entry to `DASHBOARDS` in
`config.py` with its own `subject_terms` and `role_terms`:

```python
"maths-teaching": {
    "title": "Maths Teaching Jobs",
    "subject_terms": [{"p": r"\bmath(s|ematics)\b"}],
    "role_terms": ROLE_TERMS,
    "active_only": True,
},
```

Then `python3 run.py build`. It renders to `docs/maths-teaching/`, and the root
`docs/index.html` becomes a landing page linking both. No scraping changes — the
corpus is already there.

## Scheduling

`deploy/com.jobboard.aggregator.plist` runs `run.py all --publish` daily at 07:30.

```sh
cp deploy/com.jobboard.aggregator.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jobboard.aggregator.plist
```

Check the `Python` path in the plist matches your interpreter (`which python3`).

**What happens if the machine is asleep at 07:30.** It runs on wake.
`StartCalendarInterval` coalesces missed events, which is the reason for using
`launchd` rather than `cron` — `cron` silently drops a job it slept through.

**What happens if the machine is shut down at 07:30.** A calendar event that passes
while the machine is *off* is lost; `launchd` does not backfill past events on boot.
So `RunAtLoad` is set, and the job also fires at login. It is cheap to do this
because cadence is compared by **calendar date**: if a run already happened today,
the job looks, finds nothing to do, and exits.

The date comparison also fixes a subtler bug. Comparing *elapsed time* against a
24-hour threshold means a run that starts at 07:30 and finishes at 07:34 is
recorded four minutes late, so the next day at 07:30 only 23h56m have passed and
the job skips — running every other day, indefinitely, with nothing to show for it.

**How you learn about a run.** Three channels, in order of reliability:

1. `data/run.log` — everything, always, because the plist sends both stdout and
   stderr there.
2. The **fetch health strip** on the dashboard. It carries each source's status and
   last-run time, and the page header shows when it was last generated. A stale
   page is visible rather than plausible.
3. A **macOS notification**, sent only on failure and only when headless (running
   under `launchd`, not from a terminal, where the output is already in front of
   you). Best-effort: it needs you logged in, and macOS may ask permission the
   first time. Do not rely on it as the primary signal.

To check by hand: `python3 run.py status`.

**Publishing needs two things from you.** The plist passes `--publish`, which
commits and pushes `docs/`. That requires git credentials to work without a
terminal. Your SSH key has no passphrase, so a push over SSH works headlessly —
verify the remote uses `git@github.com:…` rather than `https://`, because an HTTPS
remote needs a stored token instead. It also needs an author identity:

```sh
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

Without it the publish step stops and says so rather than failing cryptically.

## Publishing

`docs/` is the GitHub Pages root. In the repo settings, set Pages to deploy from
the branch and the `/docs` folder. `run.py publish` commits and pushes it; a failed
push is reported as a failure, because a stale dashboard looks identical to a
working one.

On a free account Pages serves public repos only. The job listings are public data
in any case; nothing private is stored here.

## Cadence and cost

Measured on a full run:

| Source | Requests | Bytes | Wall time |
|---|---|---|---|
| ESL Cafe | 6 | 23 KB | 4 s |
| THE UniJobs | 10 | 194 KB | 8 s |
| eChinaCities | ~14 | 737 KB | 129 s |
| eChinaCareers | 101 | 2.5 MB | 174 s |

eChinaCareers is almost all waste: ~100 requests to ask 100 employers what they
have, and 96 of them have nothing. It is the first candidate for a longer cadence.
Set it in `CADENCE_DAYS` and the runner will skip it on the days it is not due.

eChinaCities rate-limits. A five-keyword run drew HTTP 403 after about fourteen
requests, and a later run was answered with **HTTP 200 and a plain-text message**
(`服务器负载过高，请稍后重试` — server load too high) rather than an error code. It
now uses two keywords and a two-second gap. If it keeps throttling, give it a
longer cadence rather than pushing harder.

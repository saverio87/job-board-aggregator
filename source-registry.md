# Job Board Source Registry

**Purpose:** characterise each job-board source well enough to build a fetcher against it.
One entry per source. This is the accumulating artifact for the exploratory phase.

**Project goal (context):** a system that fetches CS/ICT teaching job ads from several
sources on a schedule, normalises them into one structured store, and serves them in a
dashboard for reviewing new listings. Scope is tag-limited (computer science / ICT
teaching), extensible to other teaching subjects later.

**Status:** exploratory. 3 sources characterised. No system built yet.

**Last updated:** 2026-10-30

---

## How to characterise a new source

Cheap steps first — the yield check can kill a source before any adapter work.

1. **Headers** — `curl -D -`. Platform fingerprint lives here (and reveals proxy layers).
2. **`robots.txt` + `sitemap.xml`** — crawl permission, and sitemaps sometimes enumerate everything.
3. **Yield check** (do this *early*) — pull the whole board and count matches for the tag set.
   One request usually does it. A source with 300 listings and 0 CS/ICT jobs is not worth an adapter.
4. **Find endpoints** — in this order: server-render hydration blobs (`__NEXT_DATA__`, GTM
   dataLayer), inline page controllers (`$http`, `fetch(`, `url:`), then JS bundles.
5. **Probe with `curl`** — record status, `content-type`, and response shape. A 200 with
   `text/html` is not an API.
6. **Characterise** — auth, pagination, freshness field, tag field, and *traps*.
7. **Record adapter notes** — the fetch order that works, and the number of requests it costs.

---

## Emerging common schema

Normalised record. `src_` fields come from the source; `own_` fields we maintain ourselves.

| Field | Notes |
|---|---|
| `source_id` | e.g. `eslcafe`, `unijobs` |
| `src_job_id` | native id/slug — **the dedupe key**. Must survive edits. |
| `src_url` | canonical listing URL |
| `title` | as published |
| `employer_name` / `src_employer_id` | employer id where the source exposes one |
| `location_raw` | as published |
| `location_country` / `location_city` | normalised |
| `salary_raw` | rarely structured; keep the string |
| `posted_at` | source's posting date, if it has one |
| `own_first_seen_at` | when we first saw it |
| `own_last_seen_at` | when we last saw it — **stops advancing = delisted** |
| `own_is_active` | true until it disappears from the fetch range |
| `description_html` | full ad body |
| `tags_subject[]` / `tags_role[]` | our classification |
| `apply_url` | direct application link, where exposed |
| `raw_payload` | store the original response verbatim |

**Why the `own_` fields exist:** no source reviewed so far gives a reliable "changed since"
or "removed" signal. We derive both by re-fetching and diffing.

---

## Tag taxonomy

Filter is **subject AND role** — a job must match one of each. One flat keyword list is too
blunt: "Computer Science Teacher" ✓, "Software Engineer" ✗ (no role), "English Teacher" ✗ (no subject).

**Subject:** computer science, computing, computer, ICT, IT, information technology, coding,
programming, software, robotics, digital literacy, edtech, informatics, STEM/STEAM,
design and technology, data science, data, database

**Match pattern for "data":** use `\bdata` — leading word boundary, no trailing one. That
catches `data`, `database`, `datasets`, `data-driven` while excluding `metadata`, where "data"
sits mid-word. A plain substring match would drag in `metadata` and `data entry`; a strict
`\bdata\b` would miss `database`, which is a role you want.

**Precision risk now, deliberately accepted:** `design and technology` is the weakest term in
this list. In UK and international schools it frequently means woodwork, resistant materials
and product design rather than computing. Adding it will pull in non-computing roles. This is
the concrete case for the classifier discussed earlier — an LLM reading the description can
separate "D&T = woodwork" from "D&T = computing", where a keyword match cannot.

**Role:** teacher, teaching, instructor, lecturer, tutor, faculty, professor, educator,
head of, lecturer / assistant professor

**Notes learned:**
- Vocabularies differ per source. `ICT` returns 3 results on THE vs `computing` at 398 —
  THE's vocabulary is "Computer Science"/"computing". Keep synonyms broad; let the source's
  own taxonomy do the work where it exists.
- Watch false positives from keyword-stuffed titles (long titles listing every subject) and
  from company names containing "Technology".
- Compound titles are real jobs: "ESL **and IT** Teachers" is a genuine hit — a rule that
  excludes "ESL/English" would wrongly drop it.

---

## Source: eslcafe.com

**Platform:** ASP.NET MVC 5 + ASP.NET Web API 2, AngularJS 1.x front end, behind Cloudflare.
**Transport:** real JSON API for lists; server-rendered HTML for detail.
**Fetch cost:** 1 list call + 1 per job body.
**Yield (CS/ICT):** **~1 job.** 304 regular jobs across all three boards, 2 title matches,
one of which is a false positive.

### Endpoints

```
GET /api/list/PostAJobList          → paginated jobs
GET /api/list/JobBoardList          → the 3 boards
GET /api/list/PostAResumesList      → resumes (not needed)
GET /api/list/News
GET /api/list/AdvertisementPagesActiveList
GET /api/admin/myaccess             → 401, auth-gated
```

```
/api/list/PostAJobList?jobBoardSlug=china&jobType=1
  &sortColumn=SortOrder&sortType=asc&page=1&size=1000
```

| Param | Required | Values |
|---|---|---|
| `jobBoardSlug` | yes, for results | `china` / `korea` / `international` |
| `jobType` | yes, for results | `1` regular, `2` sponsored |
| `sortColumn` | **yes** | `SortOrder` |
| `sortType` | **yes** | `asc` / `desc` |
| `page` | no | default 1 |
| `size` | no | default 10; `1000` works |
| `name` | no | free-text search |

### Response

```json
{ "success": true, "paging": {"page":1,"lastPage":21,"size":3,"total":61},
  "data": [ {"jobTitle":"…","company":"…","slug":"…",
             "statusStartDate":"2026-10-27T08:28:35.187","isOpenNewTab":false} ] }
```

### Traps

- **Missing `jobType` → HTTP 200 with zero rows, silently.** Looks identical to "no new jobs".
- **Missing `sortColumn`/`sortType` → HTTP 500** leaking a full .NET stack trace (internal
  file paths, `Spinx.Services.*`, Web API 2). Unhandled exceptions are returned verbatim.
- **`name=` is a full-text search on the job body, not the title.** `name=ICT` returned
  "Teach English for Academic Purposes" — matches you can't see or verify from the list data.
  Don't use it for filtering; pull the board and filter locally.
- List response gives **only** title/company/slug/date — no description, no location, no salary.

### Detail

`https://www.eslcafe.com/postajob-detail/<slug>` — server-rendered HTML, full body present.
**This is the expensive part:** one request per job. Filter on list metadata first, then
fetch bodies only for matches and ambiguous cases.

### Other notes

- Job detail also exists as SSR; contact email is in the HTML (Cloudflare-obfuscated).
- Resume details are paywalled (Stripe/PayPal/Alipay). Out of scope and stay out.
- Verdict for this project: **cleanest API of the three, worst yield.** Worth keeping as an
  adapter because the same infrastructure pays off enormously if other teaching subjects
  (ESL/English) are ever added — that's what this board actually carries.

---

## Source: echinacareers.com

**Platform:** ASP.NET MVC 5 on IIS 10. jQuery + Bootstrap, no SPA framework.
**Transport:** server-rendered Razor shell + jQuery AJAX returning **HTML fragments**. No JSON API.
**Fetch cost:** ~100 requests / ~2.5 MB / ~4-5 min for the whole board (measured — see
"Cost profile"). Request count is the misleading figure; wall time is the real cost.
**Yield (CS/ICT):** **33 jobs** (measured 2026-10-30) — and every one of them is from the
same employer. See "Full corpus" below; it reframes the whole source.

### Endpoints

```
GET  /Jobs/JobSearch              → full page (SSR shell + SEO meta only)
GET  /Jobs/JobSearchAJAX          → HTML fragment, result cards
GET  /Jobs/ViewSingleJob2         → HTML fragment, job detail
GET  /Home/CompanyProfile?empID=  → HTML fragment, full employer profile
GET  /Employer/AccountImage?empID= → logo JPEG
```

`JobSearchAJAX` params: `keywords`, `pageNum`, `locations`, `employerID`, `job_ID`,
`specialisms_`, `jobType_`, `minSalary_`, `maxSalary_`, `jobFunctions`, `specifics`.

### Traps

- **Everything returns `text/html`.** No content negotiation — `Accept: application/json`
  still returns HTML. The client does `.html(partialViewResult)`; the payload is presentation.
- **The visible body has no job content.** Initial HTML contains the description only inside
  `<meta name="description">` / `og:description` (deliberate SEO). Result cards and detail
  are both empty divs (`#search-results-list`, `#job-viewer`) filled by AJAX.
- **Invalid `empID` → HTTP 500**, not 404. 200-vs-500 distinguishes valid from invalid ids.
- `CompanyProfile` is ~2 MB because the employer's entire job list is inlined.
- Descriptions come back **double-escaped** (`&amp;#039;`, `&amp;lt;br /&amp;gt;`) and
  contain markup — unescape twice, treat as untrusted text.

### Employer lookup

`empID` alone is sufficient — no other parameter needed.

| Field | Selector |
|---|---|
| name | `h2.company-profile-name` |
| Chinese legal name | `span#alternative-company-name` |
| industries | `span.company-profile-industries-label` |
| description | `.emp-decription-area-div` |
| logo | `img#profile-img` src |
| website | `a` with text "Visit Website" |
| job ids | `onclick="AJAXJobFetch(<jobID>, <empID>, …)"` on each `.job-row` |

Also: `/Employer/AccountImage?empID=` returns the logo image directly, no HTML.

### Full corpus — the search route doesn't work, the employer route does

**`employerID` appears to be ignored by `JobSearchAJAX`.** Every value returns employer
1521's jobs:

```
employerID=1521 / 1520 / 1522 → all return emps=['1521']
employerId, empID, employerid, employer_ID, EmployerID → all emps=['1521']
```

`/Jobs/JobSearch` also hardcodes `empID=1521` server-side, and every featured job link on
the homepage carries it. `keywords` **does** filter correctly (different keywords → genuinely
different id sets), but always within that one employer. So **don't build on the search
endpoint.**

**The working route** — enumerate employers, then read each profile:

1. `GET /Home/SiteMap` → lists **100 employer ids**, no pagination
2. `GET /Home/CompanyProfile?empID=<id>` per employer → the response **inlines that
   employer's entire job list**; job ids and titles sit in
   `onclick="AJAXJobFetch(<jobID>, <empID>, "<title>");"`
3. Filter titles locally

**Measured result (2026-10-30):** 100 employers, **1,027 distinct jobs**, 0 failures.

#### Cost profile (measured)

Request count badly misrepresents this source. Per-employer measurements:

```
employer     bytes     jobs   time
1521       2,038,464   1011   26.0 s     <- essentially the entire cost
1451           4,793      0    3.4 s
1469           4,210      0    2.1 s
1479           4,298      0    2.0 s
1508           4,613      0    2.0 s
1531           4,619      0    2.0 s
1536           4,858      0    1.9 s
1562           5,090      0    2.1 s
1567           3,210      0    3.7 s
1571           4,746      0    2.6 s

requests:      100     <- misleading; 99 are ~4.5 KB and return ZERO jobs
bytes:       ~2.5 MB   <- 99% of it from employer 1521 alone
wall time:   ~4-5 min  <- dominated by 99 empty employers at ~2-3 s each
```

- **It is one expensive request, not a hundred.** 1521 is 2 MB and 26 s; the rest is noise.
- **Wall time is the real cost, not bandwidth.** ~250 s goes on asking 99 employers who have
  nothing, at 2-3 s per request — slow for a 4.5 KB page. That is what would hurt on a daily
  schedule; 2.5 MB is nothing.
- **The actual waste:** 2 MB / 1,011 job cards downloaded to keep 33 — 97% discarded. Invisible
  if you count only requests.

**Tuning implied:** poll 1521 daily; poll the 99 near-empty employers weekly — their emptiness
today predicts their emptiness tomorrow.

#### Possible optimisation (UNVERIFIED)

`JobSearchAJAX` is scoped to 1521 and `keywords` filters correctly; an earlier call with
`keywords=computer` returned a **~32 KB** response carrying only matching cards. If that holds
across pagination, 1521's CS/ICT jobs could be had in ~32 KB instead of 2 MB — roughly 60x
smaller, on the one employer holding all 33. **Not confirmed** — the pagination coverage check
was interrupted by a tooling outage. Verify before building on it.

#### Dates: there are none in the list data

Critical for any "just fetch last month" strategy. Verified: that employer profile has 1,005
job cards, each carrying only logo, `job-title`, `job-employer-name`, `job-location`. **No date field.**

```
1005 class="job-title"
1005 class="job-employer-name"
1005 class="job-location"
1005 class="job-segment"
```

The only recency signal is on the **detail** page, and it is relative prose:

```
Posted 22 days ago
```

So filtering by date costs **~1,027 detail requests** vs **100 list requests** to take
everything — recency filtering is roughly 10x *more* expensive on this source. Take the whole
board; derive recency from `own_first_seen_at` instead.

Caveat: because the source's date is relative to fetch time, it cannot be backfilled or
re-derived later. Capture it on the run where a job is first seen, or lose it.

**Detail page also carries** (useful for tagging, but 1 request per job): a category field
(`Education, Teaching`), experience (`2 Years`), degree (`Bachelor Degree`), job type
(`Full Time`).

> **97.9% of the board is one employer.** empID 1521 (China Global Connections, a Chengdu
> recruitment agency) accounts for ~1,005 of the 1,027 jobs; the other 99 employers share
> ~22 between them. So echinacareers is effectively *one agency's board with a small tail*,
> not a broad multi-employer marketplace. That also explains the "search is scoped to 1521"
> oddity above — 1521 largely *is* the inventory.

**CS/ICT teaching yield: 33 jobs**, all from empID 1521 — `Computer Science Teacher` (×11),
`计算机老师 Computer science teacher` (×4), `STEAM Teacher` (×4), `ICT Teacher 信息技术老师`,
`ICT and Computer Science Teacher`, `Computing Teacher and Digital Lead (ICT)`,
`Head of ICT and Innovation`, `Design & Technology Teacher` (×3), `Technology ICT Teacher`,
`STEM and Science Teacher`, and similar.

*Measurement caveat:* the filter required a Latin role word with a word boundary, which
misses titles where it's immediately followed by CJK — e.g. `Computer Science Teacher计算机老师`
was not counted. True figure is a little higher, roughly 35.

### Other notes

- No `robots.txt`, no sitemap. Ids look sequential — **enumerate politely or not at all.**
- Company names containing "Technology" cause false positives if you match the whole card
  instead of the title.
- Verdict: **worst transport (HTML scraping), but genuinely carries the category — 33 CS/ICT
  jobs vs eslcafe's ~1.** Worth building, using the employer route.

---

## Source: timeshighereducation.com/unijobs  ★ best source so far

**Platform:** **Madgex** (`x-madgex-proxy` header, `analytics.madgex.com`). The parent domain
is Drupal; `/unijobs/` is the Madgex app. CloudFront + AWS ALB in front.
**Transport:** server-rendered HTML, **RSS feed**, and **embedded JSON blobs**.
**Fetch cost:** 4 list calls + 1 per job (for the China CS set).
**Yield (CS/ICT):** **67 jobs in China, 376 worldwide.**

> **Madgex is a platform, not a one-off.** It powers many boards. An adapter built here likely
> transfers — detect other Madgex sites by the `x-madgex-proxy` header or `/assets/dist/` paths.

### Yield measurements (2026-10-30)

```
computer science @ China        67      (1,307 jobs in China total)
computer science @ worldwide   376
computing @ worldwide          398
programming @ worldwide        586
ICT @ worldwide                  3
```

### Endpoint 1 — RSS feed

```
GET /unijobs/jobsrss/?LocationId=71&keywords=computer+science
    &radiallocation=20&countrycode=GB&sort=Date
```

```xml
<item>
  <title>WENZHOU - KEAN UNIVERSITY: 2027 Computer Science Lecturer</title>
  <description>$68,000 - $82,000: … Wenzhou, China</description>
  <link>…/unijobs/listing/416661/2027-computer-science-lecturer/</link>
  <pubDate>Fri, 16 Oct 2026 05:51:00 +0000</pubDate>
  <guid isPermaLink="true">…</guid>
</item>
```

- `text/xml`. Respects the search criteria (keywords + location).
- **Hard-capped at 20 items** — ignores `page`, `resultsperpage`, `pagesize`.
- **The feed publishes its own true total.** Verified 2026-10-31: the feed for
  `Keywords=computer+science&LocationId=71` returns **20 items** while declaring
  `<opensearch:totalResults>66</opensearch:totalResults>`, and the search page agrees — 66 jobs.
  So the feed delivers ~30% of what it admits exists, and **says so inside the payload**.
  A scraper reading this feed can detect its own truncation for free: compare item count
  against that element. Do that.
- **Default sort is Relevance, not date.** `&sort=Date` makes it near-chronological (one
  stray old `pubDate` observed mid-feed — likely a renewed re-post).
- Good as a cheap daily "anything new?" probe. **Not a source of record** — 20 of 66, imperfect
  order. For full coverage use the search page instead (`&page=N`, 20/page, 4 pages for the
  China CS set), which paginates correctly.

### Endpoint 2 — search listing

```
GET /unijobs/searchjobs/?Keywords=computer+science&LocationId=71
    &radiallocation=20&countrycode=GB&page=N&sort=Date
```

- 20 per page. 67 jobs = 4 pages (page 4 returns 7). Confirmed.
- Embeds its own GTM dataLayer with a **free array of the page's job ids** — no HTML parsing needed:

```json
{ "returned-results": "67", "total-job-count": "1307",
  "sort-order": "Date", "page-number": "1",
  "CurrentPageJobIds": [417110,417086,408228,…] }
```

- **Sort values are capitalised:** `sort=Date` / `sort=Relevance`. Lowercase `sort=dp` is
  silently ignored (stays Relevance) — easy to think it worked.
- No date-range filter param found (tried `postedwithin`, `days`, `DatePosted`, `posted`,
  `WithinDays`). May exist as a numeric facet id.

### Endpoint 3 — job detail

```
GET /unijobs/listing/<id>/<slug>/
```

Fully server-rendered (full description text present), and embeds the richest structured
record seen on any source:

```json
{
  "job": "2027 Computer Science Lecturer",
  "JobId": "416661",
  "SalaryDescription": "$68,000 - $82,000",
  "LocationDescription": "Wenzhou, China",
  "JobDatePosted": "16 Oct 2026",
  "recruiter": "WENZHOU - KEAN UNIVERSITY",
  "RecruiterId": "160831",
  "RecruiterType": "Direct Employer",
  "ApplicationMethod": "External",
  "ApplicationURL": "https://apply.interfolio.com/194667",
  "Academic Discipline": "Computer Science,Engineering & Technology",
  "Job Type": "Academic Posts,Lecturers / Assistant Professors",
  "Contract Type": "Fixed Term",
  "Hours": "Full Time",
  "Location": "Wenzhou",
  "AllTerms": "…,Zhejiang,China,Asia,Wenzhou"
}
```

**This solves two problems the other sources don't:**
- `JobDatePosted` — a real freshness field, so a "posted in the last month" filter works on data.
- `Academic Discipline` — a **structured taxonomy**, so tagging matches a real facet instead of
  regexing titles. Far more reliable than the eslcafe approach.

### Other notes

- `robots.txt` is the stock Drupal file; `/unijobs` was not listed as disallowed in what was read.
- Small JSON endpoints exist (not needed): `/unijobs/location-lookup/`, `/unijobs/recruiter-lookup/`.
- Verdict: **best source on every axis.** Build the first adapter against this one.

---

## Source: teast.co  ★ richest payload

**Platform:** Next.js (Pages Router) on Vercel, Material-UI, i18n under `/en/`.
**Transport:** server-rendered, with the **entire job payload embedded as `__NEXT_DATA__` JSON**.
**Fetch cost:** 1 request per category page; 6 jobs per page.
**Yield (CS/ICT):** `jobCount: 32` for `/jobs/china/computer-science-ict`.

### Endpoints

```
GET /jobs/<country>/<subject-tag>?p=1                → SSR page + embedded job data
GET /_next/data/<buildId>/en/jobs/<country>/<tag>.json?p=1
                                                     → same data as raw JSON (needs /en/)
```

Job detail: `https://teast.co/job/<slug>`

The URL path **is** the taxonomy. Observed subject tags: `art-design`, `biology`, `chemistry`,
`computer-science-ict`, `economics`, `esl-tefl-english`, `geography`, `mathematics`, `music`,
`pe-sports`, `physics`, `psychology`, `science`.

### Data per job (~50 fields)

Everything needed in one response — **no detail fetch required**:

```
jobTitle, originalTitle, companyName, city, country, region, countryCode
jobDescription       <- FULL description HTML (3,289 chars on the sample)
createdAt, updatedAt <- epoch millis
subjectTags          <- ["esl-tefl-english","science","computer-science-ict"]
pay, currency, email, applyLink, website, logo
employmentTypeLower, featured, highlighted, views, active, activeDays, endJobBy
foreignTeacherOnly, nativeSpeakerOnly, anglosphereTeacherOnly, ...
```

### The finding that matters most

```json
"scraped": true,
"scrapedFrom": "ESL Cafe"
```

**teast.co is itself an aggregator.** It scrapes other boards, and `ESL Cafe` is one of the
three sources already in this registry. It may already be doing part of this project — worth
checking its coverage against eslcafe before building that adapter.

### Traps

- **`?p=` does not paginate.** The param parses correctly into `query.p` (`p=1/2/3` each show
  the right value), but the returned jobs are **identical** — the same six IDs every time.
  `jobCount` says 32; only 6 are reachable this way. How the rest load is not yet identified.
- The `/_next/data/` route 404s without the `/en/` locale prefix.

---

## Source: jobs.echinacities.com

**Platform:** PHP on OpenResty, jQuery 3.2.1 + **Vue.js** + Bootstrap. `PHPSESSID` cookie.
**Transport:** server-rendered shell with the **whole result set embedded as a JS variable**.
**Fetch cost:** 1 request per page of 25.
**Yield:** **13** CS/ICT teaching jobs (title-level, subject ∧ role). The raw
`keyword=Computer+science` match is **182** — so only ~7% of keyword hits are actually
CS/ICT teaching roles. The other ~93% are noise the source's search happily returns.

All 8 pages fetched cleanly (25 each, last page 7) totalling exactly the 182 that `num`
reported — which confirms the `per_page` offset reading end-to-end.

*Caveat:* title-level only. Jobs whose subject appears solely in the description aren't counted,
so 13 is a floor, not a ceiling.

### The payload

```js
var _searchJobList = {"code":200,"msg":"ok","data":{
  "num":182, "list":[ …25 jobs… ], "jipin":[…], "tuijian":[…] }}
```

Same shape as teast.co: the JSON is sitting in the HTML, just not advertised.

### Data per job

```
id, title, company_name, employer_id, city, city_url, other_cities
job_type, salary, salaryRmb, salaryDollar, money_type
refresh_time   <- "Oct 30"  (a real date)
end_time, description, skills, tage, sktag, logo
hot, new, isNew, top, archive
```

Job detail: `/jobchapter/<id>`

### It has the recency filter the others lack

The search UI offers **"Job Ads (30 days) / Job Ads (90 days) / Job Ads (All)"**. If that maps
to a query param, this is the first source where "just fetch the last month" is a *server-side*
filter rather than local post-filtering. The param is not yet identified.

### Traps

- **Pagination works — but not via anything you'd guess.** `page`, `p`, `pageNum`, `page_no`
  are all silently ignored: every one returns the same 25 jobs with the same first id, while
  `num` reports 182. The real parameter is **`per_page`, and it is an *offset*, not a page size**:

  ```
  page 1 → (no param)          first id 1355125045
  page 2 → &per_page=25        first id 1355124229
  page 3 → &per_page=50        first id 1355123989
  page 6 → &per_page=125       first id 1355112695
  ```

  Page N is `per_page=(N-1)*25`. The name is actively misleading — the same page also has a
  25/50 results-size selector, so `per_page=50` *reads* as "50 per page" and actually means
  "skip the first 50". 182 jobs ÷ 25 = **8 pages**.

  **Lesson worth generalising:** four plausible page params returned identical data with no
  error. The correct one was only visible in the pagination links' `href` values. When a page
  param appears to do nothing, read the markup rather than guessing more names.
- `/jobs/search/` returns HTML even with `X-Requested-With: XMLHttpRequest` — no JSON variant
  of that route.
- An `/api/v1/` convention exists (`/api/v1/account/info`, `/api/v1/consumer_chat/*`) but none
  of it is job search — account and chat only.
- Gating notice: "Please login or register if you wish to find more jobs!"
- **It rate-limits, and it does so without an error code.** A five-keyword run drew
  **HTTP 403** after roughly fourteen requests. A later run was answered with
  **HTTP 200, `content-type: text/plain`, and a 63-byte body**:

  ```
  服务器负载过高，请稍后重试        ("server load too high, please try again later")
  ```

  A status-code check sails straight past that — it is a 200. The only reason it was
  caught is that the payload marker was missing and the body was implausibly small.
  **Any scraper here must sanity-check the body, not the status.** Current handling:
  two keywords instead of five, a 2-second gap, and a named check for that string so
  the run reports "throttled" rather than "markup changed".

---

## Comparison

| Source | Platform | Transport | CS/ICT yield | Freshness | Tag field | Full body in list? |
|---|---|---|---|---|---|---|
| eslcafe | ASP.NET + Web API 2 | JSON API | ~1 | ✓ `statusStartDate` | ✗ | ✗ |
| echinacareers | ASP.NET MVC 5 | HTML fragments | 33 | ✗ | ✗ | ✗ |
| THE unijobs | Madgex | HTML + RSS + JSON blob | 67 CN / 376 ww | ✓ `JobDatePosted` | ✓ `Academic Discipline` | ✗ |
| **teast.co** | **Next.js / Vercel** | **`__NEXT_DATA__` JSON** | **32 (China tag)** | ✓ epoch ms | ✓ `subjectTags` | **✓ yes** |
| **echinacities** | **PHP + Vue** | **embedded JS var** | **13** *(from 182 raw kw)* | ✓ `refresh_time` | partial `tage` | ✗ (snippet) |

**Cross-cutting finding — pagination is the unreliable part.** Three sources page correctly;
two silently ignore the page parameter while still reporting a full result count:

| | eslcafe | echinacareers | THE | teast.co | echinacities |
|---|---|---|---|---|---|
| page param works? | ✓ | ✓ `pageNum` | ✓ `page=` | ✗ **`?p=` parses but returns identical data** | ✓ but **`per_page` = offset, not page size** |

Cost, full board: eslcafe 3 req / ~105 KB · echinacareers **100 req / ~2.5 MB / ~4-5 min**
*(measured)* · THE 4 req to list CN + 1/job · teast.co 1 req per 6 jobs · echinacities 1 req per 25.

**Cost has three axes and they disagree.** On echinacareers the request count (100) is
misleading, the byte count (2.5 MB) is fine, and the wall time (4-5 min) is the actual
problem. Record all three per source, not just requests — and check *which* one dominates
before optimising the wrong one.

**Cost has three axes and they disagree.** On echinacareers the request count (100) is
misleading, the byte count (2.5 MB) is fine, and the wall time (4-5 min) is the actual
problem. Record all three per source, not just requests — and check *which* one dominates
before optimising the wrong one.

---

## Design notes carried forward

- **Fetch broad, filter narrow.** Fetch wider than you display so "disappeared from source"
  reliably means delisted, rather than being confounded with "aged past the cutoff".
- **Don't fetch detail for everything.** Filter on list metadata first; fetch bodies only for
  matches and ambiguous cases (generic titles where the subject is only in the description).
- **Re-scraping is self-healing.** A transient silent-zero response costs one day, not data —
  unlike an incremental cursor, which would silently miss the jobs permanently.
- **Store list metadata for everything, bodies for matches.** Then adding a new tag later
  (e.g. Mathematics) works retroactively via a backfill, instead of having no history.
- **Per-source adapters behind one schema.** Already proven necessary: three sources, three
  totally different transports.

## Open questions

- Where does this live? (currently `job-board-aggregator/` at repo root — not under `user/`,
  which is reserved for the personal user-model system)
- Storage engine — SQLite is the natural fit for a single-user dashboard.
- Does the Madgex adapter actually transfer to another Madgex board? Untested.
- echinacareers is ~98% one employer. Is that stable, or is 1521 a temporary bulk poster?
  Worth re-checking the employer count on later runs; if the tail grows, the source changes character.
- Scheduler cadence and per-source politeness limits — undecided.

## Sources to try next

Candidate boards likely to carry CS/ICT teaching roles: TES, Schrole, International Schools
Services (ISS), Search Associates, Teach Away, ISS-Schrole, Council of British International
Schools, plus national boards (UK DfE, Australian state boards) and university boards.
ATS-hosted boards (Greenhouse, Lever, Ashby, Workable) often publish documented public APIs —
check for official docs before reverse-engineering.

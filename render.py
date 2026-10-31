"""Render each dashboard to static HTML + JSON.

The page is self-contained: the job data is embedded in a script tag rather than
fetched, so it opens straight off the filesystem and needs no API, no CORS and no
server on Pages either. The same records are written alongside as jobs.json for
anything that wants to read them programmatically.

Two things the page does that matter more than they look:

* **It shows fetch health.** Most of these sources fail silently — a page
  parameter that returns page one forever, a feed that returns 20 of 66 items.
  If the dashboard only shows jobs, a truncated run looks exactly like a quiet
  week. The health strip makes a bad run visible.
* **"New since last visit"** is the primary view, because that is the actual use:
  what has appeared since I last looked. The timestamp lives in the browser.
"""

import html
import json
import os
import shutil

import config
from core.model import dedupe_key
from core.store import now_iso

PAGE = r"""<!doctype html>
<html lang="en" data-theme="">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<style>
:root{
  --bg:#f5f7f9; --panel:#fff; --panel2:#eceff3; --ink:#161a1f; --soft:#525c68;
  --faint:#828c99; --rule:#d9dee6; --accent:#0d6d78; --accent-soft:#e0eff1;
  --warn:#8f4708; --warn-soft:#fbeee0; --bad:#93221f; --bad-soft:#fbe6e4;
  --good:#256b46; --good-soft:#e2f1e9;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#111419; --panel:#181c23; --panel2:#1e232b; --ink:#e5e9ee; --soft:#a2acb9;
    --faint:#78828f; --rule:#2b323b; --accent:#57c4d0; --accent-soft:#0f2e35;
    --warn:#e2a864; --warn-soft:#2c2318; --bad:#e8847c; --bad-soft:#2e1a19;
    --good:#79c9a0; --good-soft:#14291f; color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#111419; --panel:#181c23; --panel2:#1e232b; --ink:#e5e9ee; --soft:#a2acb9;
  --faint:#78828f; --rule:#2b323b; --accent:#57c4d0; --accent-soft:#0f2e35;
  --warn:#e2a864; --warn-soft:#2c2318; --bad:#e8847c; --bad-soft:#2e1a19;
  --good:#79c9a0; --good-soft:#14291f; color-scheme:dark;
}
*{box-sizing:border-box}
body{margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  padding:0 max(16px,env(safe-area-inset-left,0px)) 4rem max(16px,env(safe-area-inset-right,0px));
  -webkit-font-smoothing:antialiased}
.wrap{max-width:74rem; margin:0 auto}
header{padding:2.5rem 0 1.25rem; border-bottom:1px solid var(--rule)}
h1{margin:0 0 .4rem; font-size:1.7rem; letter-spacing:-.02em}
.sub{margin:0; color:var(--soft); font-size:.94rem; max-width:62ch}
.meta{margin-top:.9rem; font-size:.82rem; color:var(--faint);
  font-variant-numeric:tabular-nums; display:flex; flex-wrap:wrap; gap:.35rem 1.1rem}
.meta b{color:var(--ink); font-weight:600}
h2{font-size:.74rem; text-transform:uppercase; letter-spacing:.13em; color:var(--faint);
  margin:2rem 0 .7rem; font-weight:600}
.health{display:flex; flex-wrap:wrap; gap:.5rem}
.hcard{border:1px solid var(--rule); background:var(--panel); border-radius:7px;
  padding:.55rem .75rem; font-size:.82rem; min-width:11rem; flex:1 1 11rem}
.hcard .n{font-weight:600; display:block; margin-bottom:.15rem}
.hcard .d{color:var(--soft); font-size:.78rem}
.hcard.warn{border-color:var(--warn); background:var(--warn-soft)}
.hcard.bad{border-color:var(--bad); background:var(--bad-soft)}
.hcard.ok .d{color:var(--soft)}
.controls{display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin:1.5rem 0 .9rem}
input[type=search]{flex:1 1 15rem; min-width:0; padding:.5rem .7rem; border-radius:6px;
  border:1px solid var(--rule); background:var(--panel); color:var(--ink); font:inherit; font-size:.9rem}
select{padding:.5rem .6rem; border-radius:6px; border:1px solid var(--rule);
  background:var(--panel); color:var(--ink); font:inherit; font-size:.9rem}
.seg{display:flex; border:1px solid var(--rule); border-radius:6px; overflow:hidden}
.seg button{background:var(--panel); color:var(--soft); border:0; padding:.5rem .8rem;
  font:inherit; font-size:.85rem; cursor:pointer}
.seg button[aria-pressed=true]{background:var(--accent); color:#fff}
.seg button+button{border-left:1px solid var(--rule)}
.list{display:flex; flex-direction:column; gap:.5rem}
.job{background:var(--panel); border:1px solid var(--rule); border-radius:7px; padding:.7rem .85rem}
.job.new{border-left:3px solid var(--accent)}
.job.dim{opacity:.55}
.job .t{font-weight:600; font-size:.95rem; text-decoration:none; color:var(--ink)}
.job .t:hover{color:var(--accent)}
.job .row2{margin-top:.28rem; color:var(--soft); font-size:.84rem;
  display:flex; flex-wrap:wrap; gap:.3rem .8rem}
.job .tags{margin-top:.4rem; display:flex; flex-wrap:wrap; gap:.3rem}
.pill{font-size:.68rem; letter-spacing:.05em; text-transform:uppercase; padding:.13rem .42rem;
  border-radius:4px; background:var(--panel2); color:var(--soft); border:1px solid var(--rule)}
.pill.src{background:var(--accent-soft); color:var(--accent); border-color:var(--accent-soft)}
.pill.dup{background:var(--warn-soft); color:var(--warn); border-color:var(--warn-soft)}
.empty{color:var(--faint); font-size:.9rem; padding:1.5rem 0}
footer{margin-top:3rem; padding-top:1.25rem; border-top:1px solid var(--rule);
  color:var(--faint); font-size:.8rem}
@media (max-width:600px){ h1{font-size:1.35rem} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>__TITLE__</h1>
    <p class="sub">__SUBTITLE__</p>
    <div class="meta">
      <span><b>__COUNT__</b> jobs</span>
      <span>updated <b>__GENERATED__</b></span>
      <span id="visit"></span>
    </div>
  </header>

  <h2>Fetch health</h2>
  <div class="health" id="health"></div>

  <div class="controls">
    <input type="search" id="q" placeholder="Filter by title, employer or location…" aria-label="Filter jobs">
    <select id="src" aria-label="Filter by source"></select>
    <div class="seg">
      <button id="all" aria-pressed="true">All</button>
      <button id="new" aria-pressed="false">New since last visit</button>
    </div>
  </div>

  <div class="list" id="list"></div>
  <div class="empty" id="empty" hidden>Nothing matches that filter.</div>

  <footer>
    Generated from <span id="fcount"></span> stored records across
    <span id="fsrc"></span> sources. Bodies are not stored; each title links to the
    original advertisement. Data is scraped daily from public job boards.
  </footer>
</div>

<script id="payload" type="application/json">__DATA__</script>
<script>
(function(){
  var data = JSON.parse(document.getElementById('payload').textContent);
  var jobs = data.jobs || [], health = data.health || [];

  var KEY = 'jba-last-visit';
  var lastVisit = null;
  try { lastVisit = localStorage.getItem(KEY); } catch(e){}
  var now = new Date().toISOString();
  try { localStorage.setItem(KEY, now); } catch(e){}

  var vEl = document.getElementById('visit');
  vEl.textContent = lastVisit
    ? 'last visit ' + new Date(lastVisit).toLocaleDateString()
    : 'first visit';

  // health strip — the point of the page
  document.getElementById('health').innerHTML = health.map(function(h){
    var cls = h.status === 'ok' ? 'ok' : (h.status === 'warn' ? 'warn' : 'bad');
    var when = h.ran_at ? new Date(h.ran_at).toLocaleString() : 'never';
    return '<div class="hcard ' + cls + '">'
      + '<span class="n">' + esc(h.name) + '</span>'
      + '<span class="d">' + esc(h.summary) + '</span><br>'
      + '<span class="d">' + esc(when) + '</span>'
      + (h.notes ? '<br><span class="d">' + esc(h.notes) + '</span>' : '')
      + '</div>';
  }).join('');

  // source filter
  var srcs = [];
  jobs.forEach(function(j){ if (srcs.indexOf(j.source_name) < 0) srcs.push(j.source_name); });
  var sel = document.getElementById('src');
  sel.innerHTML = '<option value="">All sources</option>'
    + srcs.sort().map(function(s){ return '<option>' + esc(s) + '</option>'; }).join('');

  var mode = 'all';
  function render(){
    var q = document.getElementById('q').value.trim().toLowerCase();
    var s = sel.value;
    var out = jobs.filter(function(j){
      if (s && j.source_name !== s) return false;
      if (mode === 'new' && lastVisit && j.first_seen <= lastVisit) return false;
      if (mode === 'new' && !lastVisit) return true;
      if (q){
        var hay = (j.title + ' ' + j.employer + ' ' + j.location_raw).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
    document.getElementById('list').innerHTML = out.map(function(j){
      var isNew = lastVisit && j.first_seen > lastVisit;
      return '<div class="job' + (isNew ? ' new' : '') + '">'
        + '<a class="t" href="' + esc(j.url) + '" target="_blank" rel="noopener">'
        + esc(j.title) + '</a>'
        + '<div class="row2">'
        + (j.employer ? '<span>' + esc(j.employer) + '</span>' : '')
        + (j.location_raw ? '<span>' + esc(j.location_raw) + '</span>' : '')
        + (j.salary_raw ? '<span>' + esc(j.salary_raw) + '</span>' : '')
        + '<span>' + (j.posted_at || 'seen ' + String(j.first_seen).slice(0,10)) + '</span>'
        + '</div>'
        + '<div class="tags">'
        + '<span class="pill src">' + esc(j.source_name) + '</span>'
        + (j.matched_subject || []).map(function(t){
            return '<span class="pill">' + esc(t) + '</span>'; }).join('')
        + (j.also_on ? '<span class="pill dup">also on ' + esc(j.also_on) + '</span>' : '')
        + '</div></div>';
    }).join('');
    document.getElementById('empty').hidden = out.length > 0;
  }

  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  document.getElementById('q').addEventListener('input', render);
  sel.addEventListener('change', render);
  document.getElementById('all').addEventListener('click', function(){
    mode='all'; this.setAttribute('aria-pressed','true');
    document.getElementById('new').setAttribute('aria-pressed','false'); render();
  });
  document.getElementById('new').addEventListener('click', function(){
    mode='new'; this.setAttribute('aria-pressed','true');
    document.getElementById('all').setAttribute('aria-pressed','false'); render();
  });

  document.getElementById('fcount').textContent = jobs.length;
  document.getElementById('fsrc').textContent = srcs.length;
  render();
})();
</script>
</body>
</html>
"""

LANDING = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Dashboards</title>
<style>
body{margin:0;padding:3rem max(16px,env(safe-area-inset-left,0px)) 4rem;
 font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 background:#f5f7f9;color:#161a1f}
@media (prefers-color-scheme:dark){body{background:#111419;color:#e5e9ee}
 a{color:#57c4d0}}
.wrap{max-width:44rem;margin:0 auto}
h1{font-size:1.6rem;margin:0 0 1.5rem}
ul{list-style:none;padding:0;display:flex;flex-direction:column;gap:.6rem}
li{border:1px solid #d9dee6;border-radius:8px;padding:.8rem 1rem;background:#fff}
@media (prefers-color-scheme:dark){li{background:#181c23;border-color:#2b323b}}
a{color:#0d6d78;text-decoration:none;font-weight:600}
a:hover{text-decoration:underline}
p{margin:.3rem 0 0;font-size:.88rem;opacity:.75}
</style></head><body><div class="wrap">
<h1>Job Dashboards</h1>
<ul>__ITEMS__</ul>
</div></body></html>
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


def build(store, docs_dir=None):
    docs_dir = docs_dir or config.DOCS_DIR
    os.makedirs(docs_dir, exist_ok=True)

    runs = {r["source"]: r for r in store.last_runs()}
    health = []
    for sid in config.ENABLED_SOURCES:
        r = runs.get(sid)
        if not r:
            health.append({"name": sid, "status": "bad", "summary": "never run",
                           "ran_at": "", "notes": ""})
            continue
        reported = r["reported"] or 0
        summary = f"{r['collected']}"
        if reported:
            summary += f"/{reported}"
        summary += f" jobs · {r['requests']} req"
        health.append({
            "name": sid, "status": r["status"], "summary": summary,
            "ran_at": r["ran_at"], "notes": r["notes"] or "",
        })

    items = []
    for slug, dash in config.DASHBOARDS.items():
        jobs = store.jobs_for(dash["subject_terms"], dash["role_terms"],
                              active_only=dash.get("active_only", True))
        jobs = _decorate(jobs, runs)

        outdir = os.path.join(docs_dir, slug)
        os.makedirs(outdir, exist_ok=True)

        payload = {
            "generated": now_iso(),
            "jobs": jobs,
            "health": health,
        }
        with open(os.path.join(outdir, "jobs.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

        page = (PAGE
                .replace("__TITLE__", esc(dash["title"]))
                .replace("__SUBTITLE__", esc(dash.get("subtitle", "")))
                .replace("__COUNT__", str(len(jobs)))
                .replace("__GENERATED__", esc(payload["generated"][:16].replace("T", " ")))
                .replace("__DATA__", json.dumps(payload, ensure_ascii=False)
                         .replace("</", "<\\/")))
        with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)

        items.append((slug, dash, len(jobs)))

    if len(items) == 1:
        # one dashboard: make the root serve it directly
        slug, dash, n = items[0]
        src = os.path.join(docs_dir, slug, "index.html")
        with open(src, encoding="utf-8") as f:
            body = f.read()
        with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(body)
        # and keep the JSON reachable at the root for anything reading it
        shutil.copy(os.path.join(docs_dir, slug, "jobs.json"),
                    os.path.join(docs_dir, "jobs.json"))
    else:
        links = "".join(
            f'<li><a href="{slug}/">{esc(d["title"])}</a>'
            f'<p>{n} jobs — {esc(d.get("subtitle",""))}</p></li>'
            for slug, d, n in items
        )
        with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(LANDING.replace("__ITEMS__", links))

    return items


def _decorate(jobs, runs):
    """Add display fields: source name, and which other sources carry the same job."""
    names = {}
    try:
        import sources
        for sid in config.ENABLED_SOURCES:
            names[sid] = sources.get(sid).name
    except Exception:
        pass

    # Set source_name on every job first. Reading it off another job in the same
    # pass would miss any job not yet visited.
    for j in jobs:
        j["source_name"] = names.get(j["source"], j["source"])
        j["matched_subject"] = list(j.get("matched_subject") or [])
        j.setdefault("also_on", "")
        # Recompute rather than trust the stored column, so the key is always
        # consistent with the current rule even before the next fetch rewrites it.
        j["dedupe_key"] = dedupe_key(j["title"], j.get("employer", ""),
                                     j.get("location_raw", ""))

    by_key = {}
    for j in jobs:
        by_key.setdefault(j["dedupe_key"], []).append(j)

    for j in jobs:
        dupes = {o["source_name"] for o in by_key.get(j["dedupe_key"], [])
                 if o["source"] != j["source"]}
        j["also_on"] = ", ".join(sorted(dupes))
    return jobs

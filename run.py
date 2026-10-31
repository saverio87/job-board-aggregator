#!/usr/bin/env python3
"""Job board aggregator.

  python3 run.py fetch           fetch any source whose cadence has come round
  python3 run.py fetch --force   fetch regardless of cadence
  python3 run.py fetch --sources eslcafe,the_unijobs
  python3 run.py build           render the dashboards from what is stored
  python3 run.py all             fetch then build
  python3 run.py status          show the last run per source
  python3 run.py tags --title "..."   check what a title matches

The one scheduled command is `all`. Everything else exists for working on it.
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

# Run from anywhere, including under launchd, which starts jobs with an arbitrary
# working directory and an empty environment.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import config
import render
import sources
from core.http import Fetcher
from core.model import SourceResult
from core.store import Store


def is_due(store, sid):
    """Has this source's cadence come round?

    Daily sources are compared by *calendar date*, not by elapsed time. Elapsed
    time has an off-by-a-few-minutes bug that quietly halves the schedule: a run
    that starts at 07:30 and takes four minutes is recorded at 07:34, so the next
    day at 07:30 only 23h56m have passed and the job skips — running every other
    day forever.

    Comparing dates also gives free catch-up. If the machine was off at 07:30 and
    boots at 09:00, no successful run exists for today's date, so the job runs.
    """
    last = store.last_success(sid)
    if not last:
        return True
    try:
        ran = datetime.fromisoformat(last["ran_at"]).astimezone()
    except ValueError:
        return True

    days = config.CADENCE_DAYS.get(sid, 1)
    if days <= 1:
        return ran.date() != datetime.now().astimezone().date()
    return (datetime.now(timezone.utc) - ran) >= timedelta(days=days)


def notify(title, message):
    """Post a macOS notification. Best-effort: never fail a run over it.

    Only used to report failure. A notification from a launchd agent needs the
    user logged in, and macOS may gate it behind a permission prompt the first
    time, so treat it as a convenience rather than a guarantee — the log file and
    the dashboard's health strip are the channels you can rely on.
    """
    def applescript(s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    try:
        subprocess.run(
            ["osascript", "-e",
             f"display notification {applescript(message)} with title {applescript(title)}"],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass


def cmd_fetch(store, args):
    wanted = [s.strip() for s in args.sources.split(",")] if args.sources else None
    failed = []

    for sid in config.ENABLED_SOURCES:
        if wanted and sid not in wanted:
            continue
        if not args.force and not is_due(store, sid):
            print(f"  {sid}: not due, skipping")
            continue

        http = Fetcher(delay=config.SOURCE_DELAY.get(sid, config.REQUEST_DELAY))
        res = SourceResult(source=sid)
        started = time.time()
        print(f"  {sid}: fetching…", flush=True)
        try:
            sources.get(sid).fetch(http, res)
        except Exception as e:                      # one bad source must not stop the rest
            res.fail(f"unhandled error: {e}")

        res.requests = http.requests
        res.bytes = http.bytes
        res.collected = len(res.jobs)

        new, updated = store.upsert(res.jobs)

        # Only retire on a clean run. A truncated fetch would otherwise mark
        # everything past page one as delisted — the exact silent failure the
        # guards exist to catch.
        retired = 0
        if res.status == "ok":
            retired = store.retire_missing(sid, [j.src_job_id for j in res.jobs])

        store.record_run(res)

        print(f"  {sid}: {res.status} · {res.summary()} · "
              f"{new} new, {updated} seen, {retired} retired · "
              f"{time.time() - started:.0f}s")
        for note in res.notes:
            print(f"      {note}")
        if res.status == "error":
            failed.append(sid)

    return failed


def cmd_build(store, args):
    items = render.build(store)
    for slug, dash, n in items:
        print(f"  {slug}: {n} jobs → {config.DOCS_DIR}/{slug}/")
    totals = store.counts()
    print(f"  corpus: {totals['active']} active of {totals['total']} stored")
    return []


def cmd_publish(store, args):
    """Commit and push the generated docs/ so GitHub Pages republishes.

    This is a failure point the scrape itself does not have: if the machine is
    offline, or the git credentials have expired, the fetch succeeds and the
    publish silently does not — leaving a dashboard that looks fine and is frozen.
    So a failed push is reported as a failure, and the page carries its own
    generation timestamp for the same reason.
    """
    def git(*a, check=True):
        return subprocess.run(["git", *a], capture_output=True, text=True, check=check)

    try:
        git("rev-parse", "--is-inside-work-tree")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  publish: not a git repository — skipping")
        return []

    # A commit with no author identity fails outright, and under launchd there is
    # no terminal to explain why. Catch it here with the fix in the message.
    name = git("config", "user.name", check=False).stdout.strip()
    email = git("config", "user.email", check=False).stdout.strip()
    if not name or not email:
        print("  publish: git identity not configured — commits would fail. Run:")
        print('           git config --global user.name "Your Name"')
        print('           git config --global user.email "you@example.com"')
        return ["publish"]

    git("add", "docs")
    status = git("status", "--porcelain", "docs").stdout.strip()
    if not status:
        print("  publish: docs unchanged, nothing to commit")
        return []

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    git("commit", "-m", f"Update job dashboards ({stamp} UTC)")
    try:
        git("push")
    except subprocess.CalledProcessError as e:
        print(f"  publish: PUSH FAILED — dashboard is now stale on Pages\n"
              f"           {e.stderr.strip()[:200]}")
        return ["publish"]

    print("  publish: pushed")
    return []


def cmd_status(store, args):
    rows = store.last_runs()
    if not rows:
        print("  no runs recorded yet")
        return []
    for r in rows:
        reported = f"/{r['reported']}" if r["reported"] else ""
        print(f"  {r['source']:<16} {r['status']:<6} "
              f"{r['collected']}{reported} jobs · {r['requests']} req · {r['ran_at']}")
        if r["notes"]:
            for n in r["notes"].split(" | "):
                print(f"      {n}")
    return []


def cmd_tags(store, args):
    from core.tags import classify

    for slug, dash in config.DASHBOARDS.items():
        ok, subs, roles = classify(args.title, dash["subject_terms"], dash["role_terms"])
        mark = "MATCH" if ok else "no match"
        print(f"  [{mark}] subject={subs or '—'} role={roles or '—'}")
    return []


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="fetch from sources")
    f.add_argument("--force", action="store_true", help="ignore cadence")
    f.add_argument("--sources", help="comma-separated subset")

    sub.add_parser("build", help="render dashboards")

    a = sub.add_parser("all", help="fetch then build")
    a.add_argument("--force", action="store_true")
    a.add_argument("--sources")
    a.add_argument("--publish", action="store_true",
                   help="commit and push docs/ to GitHub Pages")

    sub.add_parser("publish", help="commit and push docs/")
    sub.add_parser("status", help="show last run per source")

    t = sub.add_parser("tags", help="test the tag filter on a title")
    t.add_argument("--title", required=True)

    args = p.parse_args()
    store = Store()
    try:
        if args.cmd == "fetch":
            failed = cmd_fetch(store, args)
        elif args.cmd == "build":
            failed = cmd_build(store, args)
        elif args.cmd == "all":
            failed = cmd_fetch(store, args)
            cmd_build(store, args)
            if args.publish:
                failed += cmd_publish(store, args)
        elif args.cmd == "publish":
            failed = cmd_publish(store, args)
        elif args.cmd == "status":
            failed = cmd_status(store, args)
        elif args.cmd == "tags":
            failed = cmd_tags(store, args)
        else:
            failed = []
    finally:
        store.close()

    # A source that errored is worth a non-zero exit so a scheduled run surfaces
    # the failure instead of passing quietly.
    #
    # Notify only when headless. Under launchd stdout is a file and nobody is
    # watching; interactively it is a terminal and the output above is right there.
    if failed and not sys.stdout.isatty():
        notify("Job board run had problems", f"{', '.join(failed)} — see data/run.log")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

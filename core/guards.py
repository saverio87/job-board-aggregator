"""Integrity checks.

Each of these exists because a real source failed this way, silently, while
reporting success. They are cheap and they belong in the core rather than in
adapters, so that every future adapter inherits them.
"""


def check_pages_differ(prev_ids, curr_ids, page, result):
    """Catch a page parameter that is parsed and then ignored.

    Two sources do this. teast.co accepts `?p=3`, records it in its own query
    object, and returns page one. echinacities ignores four different page
    parameters and returns the same 25 jobs every time.

    Identical ids on consecutive pages is the tell. Treat it as a hard stop for
    that source's pagination rather than a blip.
    """
    if prev_ids and set(map(str, curr_ids)) == set(map(str, prev_ids)):
        result.warn(
            f"page {page} returned the same {len(curr_ids)} ids as page {page - 1} "
            f"— pagination is being ignored, stopping"
        )
        return False
    return True


def check_totals(collected, reported, result, label="jobs"):
    """Compare what we collected against what the source says exists.

    The cheapest guard there is, because the number is usually already in the
    payload. THE's RSS publishes `<opensearch:totalResults>66</opensearch:totalResults>`
    while returning 20 items; echinacities declares `num: 182`.
    """
    if not reported:
        return True
    if collected < reported:
        result.warn(f"collected {collected} of {reported} {label} the source reports")
        return False
    return True


def check_nonempty(collected, result):
    """A run that returns nothing is not the same as a day with no new jobs.

    omitting one parameter on eslcafe yields HTTP 200, a valid envelope and zero
    rows. An empty result must never be recorded as a clean run, or the retirement
    pass will mark every stored job as delisted.
    """
    if collected == 0:
        result.warn("returned zero rows — treating as unverified, not as 'nothing new'")
        return False
    return True

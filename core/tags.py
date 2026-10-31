"""Tag matching: subject AND role.

Kept deliberately simple and local. A source's own keyword search is a candidate
generator, never a filter — one of them returns 182 results for a query where only
13 are actually relevant, about 7% precision. So we do the real matching here,
against fields we control, and log what we reject.
"""

import re

_cache = {}


def _compiled(terms):
    key = id(terms)
    if key not in _cache:
        built = []
        for t in terms:
            flags = 0 if t.get("cs") else re.IGNORECASE
            built.append((re.compile(t["p"], flags), t["p"]))
        _cache[key] = built
    return _cache[key]


def match(text, terms):
    """Return the list of term patterns that hit, or []."""
    if not text:
        return []
    return [label for rx, label in _compiled(terms) if rx.search(text)]


def classify(title, subject_terms, role_terms, extra_text=""):
    """Classify a job by title (and optionally more text).

    Returns (is_match, subjects_hit, roles_hit). Both a subject and a role must
    hit. The role is matched against the title only — a role word in a description
    ("you will work alongside teachers") is noise.
    """
    haystack = title or ""
    if extra_text:
        haystack = f"{title} {extra_text}"
    subjects = match(haystack, subject_terms)
    roles = match(title, role_terms)
    return (bool(subjects) and bool(roles)), subjects, roles

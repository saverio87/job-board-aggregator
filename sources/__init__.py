"""Source registry.

Adding a board is: write a module here implementing `fetch`, add its id to
config.ENABLED_SOURCES, and add a line below. Nothing else in the pipeline knows
or cares how many sources there are or how each one serves its data.
"""

from sources import echinacareers, echinacities, eslcafe, the_unijobs

_CLASSES = {
    eslcafe.Source.id: eslcafe.Source,
    the_unijobs.Source.id: the_unijobs.Source,
    echinacareers.Source.id: echinacareers.Source,
    echinacities.Source.id: echinacities.Source,
}


def get(source_id):
    """Return a fresh adapter instance for a source id."""
    try:
        return _CLASSES[source_id]()
    except KeyError:
        raise KeyError(
            f"unknown source '{source_id}'. Known: {', '.join(sorted(_CLASSES))}"
        ) from None


def all_ids():
    return sorted(_CLASSES)

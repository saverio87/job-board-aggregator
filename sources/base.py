"""Adapter interface.

An adapter's whole job is: know the endpoints, know the parameters, and know the
traps. Everything reusable — retries, politeness, tag matching, storage,
retirement, the integrity checks — lives in core/ and is already handled by the
time `fetch` is called.
"""


class Source:
    id = ""
    name = ""
    homepage = ""

    def fetch(self, http, result):
        """Populate `result.jobs` and return it.

        Must set `result.reported` when the source publishes a total, so the
        collected-vs-reported guard has something to compare against.
        """
        raise NotImplementedError

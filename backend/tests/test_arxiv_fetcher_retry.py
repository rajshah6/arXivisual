"""arXiv metadata fetch: retry 429 AND 503 with capped, jittered backoff.

The export API answered 429/503 often enough that 206 of 656 ingests in one
week died in ``fetch_paper_meta``: 503 was never retried at all, and the status
was sniffed out of a message that contains the request URL — so any error for
paper 2404.01234 contained "404" and was reported as "Paper not found".

Sleeps are injected; nothing here waits or touches the network.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import arxiv
import pytest

from ingestion import arxiv_fetcher
from ingestion.arxiv_fetcher import (
    META_BACKOFF_CAP_SECONDS,
    META_MAX_ATTEMPTS,
    fetch_paper_meta,
)

INGEST_CEILING_SECONDS = 15 * 60  # temporal_app/workflows.py: ingest start_to_close


def _http_error(status: int, arxiv_id: str = "1706.03762") -> arxiv.HTTPError:
    return arxiv.HTTPError(f"https://export.arxiv.org/api/query?id_list={arxiv_id}", 3, status)


def _result(title="Attention Is All You Need"):
    now = datetime(2017, 6, 12, tzinfo=UTC)
    return SimpleNamespace(
        title=title, authors=[SimpleNamespace(name="A. Vaswani")], summary="abstract",
        published=now, updated=now, categories=["cs.CL"],
    )


@pytest.fixture()
def arxiv_api(monkeypatch):
    """Script the arXiv client: each entry is an exception to raise or a result list."""
    script: list = []
    calls = {"n": 0}

    class _Client:
        def results(self, _search):
            calls["n"] += 1
            outcome = script.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return iter(outcome)

    async def _no_html(_arxiv_id):
        return None

    monkeypatch.setattr(arxiv_fetcher.arxiv, "Client", _Client)
    monkeypatch.setattr(arxiv_fetcher, "find_latexml_html_url", _no_html)
    return script, calls


class _Sleeps:
    def __init__(self):
        self.waits: list[float] = []

    async def __call__(self, seconds: float):
        self.waits.append(seconds)


@pytest.mark.parametrize("status", [429, 503])
async def test_rate_limit_and_unavailable_are_both_retried(arxiv_api, status):
    script, calls = arxiv_api
    script += [_http_error(status), _http_error(status), [_result()]]
    sleeps = _Sleeps()

    meta = await fetch_paper_meta("1706.03762", sleep=sleeps)

    assert meta.title == "Attention Is All You Need"
    assert calls["n"] == 3 and len(sleeps.waits) == 2


async def test_backoff_is_exponential_jittered_and_capped(arxiv_api):
    script, _calls = arxiv_api
    script += [_http_error(503)] * (META_MAX_ATTEMPTS - 1) + [[_result()]]

    low, high = _Sleeps(), _Sleeps()
    await fetch_paper_meta("1706.03762", sleep=low, rand=lambda: 0.0)
    script += [_http_error(503)] * (META_MAX_ATTEMPTS - 1) + [[_result()]]
    await fetch_paper_meta("1706.03762", sleep=high, rand=lambda: 1.0)

    assert len(low.waits) == len(high.waits) == META_MAX_ATTEMPTS - 1
    # Exponential until the cap: each nominal wait doubles.
    assert low.waits[1] == pytest.approx(2 * low.waits[0])
    assert low.waits[2] == pytest.approx(2 * low.waits[1])
    # Jitter: the same attempt waits a different time at the two extremes.
    assert all(lo < hi for lo, hi in zip(low.waits, high.waits, strict=True))
    # Capped, jitter included.
    assert max(high.waits) <= META_BACKOFF_CAP_SECONDS * 1.25


async def test_worst_case_stays_well_inside_the_ingest_ceiling(arxiv_api):
    script, calls = arxiv_api
    script += [_http_error(429)] * META_MAX_ATTEMPTS
    sleeps = _Sleeps()

    with pytest.raises(ValueError, match="after 6 attempts") as excinfo:
        await fetch_paper_meta("1706.03762", sleep=sleeps, rand=lambda: 1.0)

    assert calls["n"] == META_MAX_ATTEMPTS
    assert "429" in str(excinfo.value)
    # The arxiv client also retries internally (3 x 3 s per call); even with
    # that on top, all the waiting fits in a third of the 15-minute ceiling.
    internal = META_MAX_ATTEMPTS * 3 * 3.0
    assert sum(sleeps.waits) + internal < INGEST_CEILING_SECONDS / 3


async def test_other_statuses_are_not_retried(arxiv_api):
    script, calls = arxiv_api
    script += [_http_error(500)]
    sleeps = _Sleeps()

    with pytest.raises(ValueError, match="HTTP 500"):
        await fetch_paper_meta("1706.03762", sleep=sleeps)
    assert calls["n"] == 1 and sleeps.waits == []


async def test_status_comes_from_the_error_not_from_digits_in_the_url(arxiv_api):
    # "2404.01234" contains 404 and "2429.00001" contains 429: the old
    # substring sniffing turned a 500 into "Paper not found" / a retry loop.
    script, calls = arxiv_api
    sleeps = _Sleeps()

    script += [_http_error(500, "2404.01234")]
    with pytest.raises(ValueError) as excinfo:
        await fetch_paper_meta("2404.01234", sleep=sleeps)
    assert "not found" not in str(excinfo.value).lower()

    script += [_http_error(500, "2429.00001")]
    with pytest.raises(ValueError):
        await fetch_paper_meta("2429.00001", sleep=sleeps)
    assert calls["n"] == 2 and sleeps.waits == []

    script += [_http_error(503, "2404.01234"), [_result()]]
    assert (await fetch_paper_meta("2404.01234", sleep=sleeps)).arxiv_id == "2404.01234"


async def test_404_and_400_keep_their_messages(arxiv_api):
    script, _calls = arxiv_api
    script += [_http_error(404), _http_error(400)]
    with pytest.raises(ValueError, match="Paper not found"):
        await fetch_paper_meta("1706.03762", sleep=_Sleeps())
    with pytest.raises(ValueError, match="Invalid arXiv ID"):
        await fetch_paper_meta("1706.03762", sleep=_Sleeps())


async def test_connection_trouble_is_still_a_connection_error(arxiv_api):
    script, _calls = arxiv_api
    script += [OSError("Connection reset by peer")]
    with pytest.raises(ConnectionError):
        await fetch_paper_meta("1706.03762", sleep=_Sleeps())


async def test_empty_result_is_not_found(arxiv_api):
    script, _calls = arxiv_api
    script += [[]]
    with pytest.raises(ValueError, match="Paper not found"):
        await fetch_paper_meta("1706.03762", sleep=_Sleeps())

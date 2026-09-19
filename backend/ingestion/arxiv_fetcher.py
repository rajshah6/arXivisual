"""
ArXiv paper fetcher for the ingestion pipeline.

Fetches paper metadata from the arXiv API and downloads PDFs.
Also locates a LaTeXML HTML rendering (arxiv.org/html, then ar5iv).
"""

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable

import arxiv
import httpx

logger = logging.getLogger(__name__)

from models.paper import ArxivPaperMeta

# Regex to normalize arXiv IDs
ARXIV_ID_PATTERN = re.compile(r'^(\d{4}\.\d{4,5})(v\d+)?$|^([a-z-]+/\d{7})(v\d+)?$')


def normalize_arxiv_id(arxiv_id: str) -> str:
    """
    Normalize arXiv ID by stripping version suffix if present.
    
    Examples:
        - "1706.03762v1" -> "1706.03762"
        - "1706.03762" -> "1706.03762"
        - "cs/0123456v2" -> "cs/0123456"
    """
    # Remove 'arXiv:' prefix if present
    arxiv_id = arxiv_id.replace('arXiv:', '').strip()
    
    # Strip version suffix
    match = ARXIV_ID_PATTERN.match(arxiv_id)
    if match:
        # Return the base ID without version
        return match.group(1) or match.group(3)
    
    # If no match, return as-is (might be invalid)
    return arxiv_id


def extract_version(arxiv_id: str) -> int | None:
    """Extract version number from arXiv ID if present."""
    match = re.search(r'v(\d+)$', arxiv_id)
    if match:
        return int(match.group(1))
    return None


def validate_arxiv_id(arxiv_id: str) -> bool:
    """
    Validate that an arXiv ID is in a valid format.
    
    Valid formats:
    - 1706.03762 (new format)
    - 1706.03762v1 (with version)
    - cs/0123456 (old format)
    """
    cleaned = arxiv_id.replace('arXiv:', '').strip()
    return bool(ARXIV_ID_PATTERN.match(cleaned))


# The export API answers 429 (rate limit) and 503 (overloaded) in bursts: 206 of
# 656 ingests in one week died here. The arxiv client's own retries (3, a fixed
# 3 s apart) are too quick for either to clear, and 503 was not retried by this
# loop at all. Exponential backoff with jitter (many ingests start together and
# must not re-collide), capped — worst case about 2.8 min of waiting plus the
# client's internal ~1 min, well inside the ingest activity's 15-minute ceiling
# with room left for the actual ingest.
RETRYABLE_STATUSES = frozenset({429, 503})
META_MAX_ATTEMPTS = 6
META_BACKOFF_BASE_SECONDS = 5.0
META_BACKOFF_CAP_SECONDS = 60.0
META_BACKOFF_JITTER = 0.25  # each wait is nominal x [0.75, 1.25]


def _backoff_seconds(attempt: int, rand: Callable[[], float]) -> float:
    """Wait before retry number ``attempt + 1``: 5, 10, 20, 40, 60 s nominal."""
    nominal = min(META_BACKOFF_CAP_SECONDS, META_BACKOFF_BASE_SECONDS * (2 ** attempt))
    return nominal * (1 + META_BACKOFF_JITTER * (2 * rand() - 1))


def _http_status(error: Exception) -> int | None:
    """HTTP status of an arxiv.HTTPError, from the error object itself.

    Never from the message: it embeds the request URL, so "2404.01234"
    contains 404 and "2429.00001" contains 429.
    """
    status = getattr(error, "status", None)
    return status if isinstance(status, int) else None


async def fetch_paper_meta(
    arxiv_id: str,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> ArxivPaperMeta:
    """
    Fetch paper metadata from arXiv API.

    Args:
        arxiv_id: arXiv paper ID (e.g., "1706.03762" or "1706.03762v1")
        sleep / rand: injectable for tests (backoff waits and jitter)

    Returns:
        ArxivPaperMeta with all paper metadata

    Raises:
        ValueError: If paper not found or invalid ID
    """
    # Normalize the ID (keep version for search if specified)
    search_id = arxiv_id.replace('arXiv:', '').strip()
    base_id = normalize_arxiv_id(arxiv_id)
    
    # Validate ID format first
    if not validate_arxiv_id(arxiv_id):
        raise ValueError(
            f"Invalid arXiv ID format: '{arxiv_id}'. "
            f"Expected formats: '1706.03762', '1706.03762v1', or 'cs/0123456'"
        )
    
    last_error = None

    for attempt in range(META_MAX_ATTEMPTS):
        try:
            # Create search client
            client = arxiv.Client()

            # Search for the paper
            search = arxiv.Search(
                id_list=[search_id],
                max_results=1
            )

            # The arxiv library is synchronous and time.sleep()s between its
            # own retries — keep that off the event loop (it froze status
            # polling on the in-process path, and more attempts means more of it).
            results = await asyncio.to_thread(lambda c=client, s=search: list(c.results(s)))
            break  # Success

        except Exception as e:
            error_msg = str(e)
            last_error = e
            status = _http_status(e)

            # Retry on rate limit (429) and overload (503)
            if status in RETRYABLE_STATUSES:
                if attempt + 1 < META_MAX_ATTEMPTS:
                    wait = _backoff_seconds(attempt, rand)
                    logger.warning(
                        "arXiv API answered HTTP %s, retrying in %.0fs (attempt %d/%d)",
                        status, wait, attempt + 1, META_MAX_ATTEMPTS,
                    )
                    await sleep(wait)
                continue

            # Non-retryable errors — raise immediately. With a real status the
            # message is never sniffed (it embeds the URL, hence the id).
            if status == 400 or (status is None and ("400" in error_msg or "Bad Request" in error_msg)):
                raise ValueError(f"Invalid arXiv ID: '{arxiv_id}' - arXiv API rejected the request") from e
            elif status == 404 or (status is None and ("404" in error_msg or "Not Found" in error_msg)):
                raise ValueError(f"Paper not found on arXiv: '{arxiv_id}'") from e
            elif status is None and ("timeout" in error_msg.lower() or "connection" in error_msg.lower()):
                raise ConnectionError(f"Could not connect to arXiv API: {e}") from e
            else:
                raise ValueError(f"Error fetching paper '{arxiv_id}': {e}") from e
    else:
        # All attempts exhausted
        raise ValueError(
            f"Error fetching paper '{arxiv_id}' after {META_MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    if not results:
        raise ValueError(f"Paper not found on arXiv: '{arxiv_id}'")
    
    paper = results[0]
    
    # Build PDF URL
    pdf_url = f"https://arxiv.org/pdf/{base_id}.pdf"
    
    # Check for ar5iv HTML availability
    html_url = await find_latexml_html_url(base_id)
    
    return ArxivPaperMeta(
        arxiv_id=base_id,
        title=paper.title,
        authors=[author.name for author in paper.authors],
        abstract=paper.summary,
        published=paper.published,
        updated=paper.updated,
        categories=[cat for cat in paper.categories],
        pdf_url=pdf_url,
        html_url=html_url
    )


_LATEXML_HOSTS = {"arxiv.org", "ar5iv.labs.arxiv.org"}


def _is_latexml_html_url(url: str) -> bool:
    parsed = httpx.URL(url)
    return parsed.host in _LATEXML_HOSTS and parsed.path.startswith("/html/")


async def find_latexml_html_url(arxiv_id: str) -> str | None:
    """
    Find a LaTeXML HTML rendering of the paper, or None.

    Probes the LaTeXML pages themselves — arxiv.org/html first, then
    ar5iv.labs.arxiv.org/html — with redirects NOT followed. The old check
    HEAD'd ar5iv.org/abs with redirects on; for ids ar5iv hasn't converted
    that chain ends at the arxiv.org ABSTRACT page with a 200, and ~31% of
    the library was ingested as a 300-word inflation of the abstract. A 3xx
    is honoured only when it resolves to another /html/ URL on a LaTeXML host
    AND that target itself answers 200 (unconverted ids redirect to /abs/).
    """
    candidates = [
        f"https://arxiv.org/html/{arxiv_id}",
        f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
    ]
    async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
        for url in candidates:
            try:
                response = await client.head(url)
                if response.status_code == 200:
                    return url
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location", "")
                    if not location:
                        continue
                    target = str(httpx.URL(url).join(location))
                    if _is_latexml_html_url(target):
                        resolved = await client.head(target)
                        if resolved.status_code == 200:
                            return target
            except httpx.RequestError:
                continue
    return None


# Backwards-compatible name (callers/tests written against the old check).
check_ar5iv_available = find_latexml_html_url


async def download_pdf(pdf_url: str) -> bytes:
    """
    Download PDF from arXiv.
    
    Args:
        pdf_url: Direct PDF download URL
        
    Returns:
        Raw PDF bytes
        
    Raises:
        httpx.HTTPError: If download fails
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        response = await client.get(pdf_url)
        response.raise_for_status()
        return response.content


async def fetch_html_content(html_url: str) -> str:
    """
    Fetch HTML content from ar5iv.
    
    Args:
        html_url: ar5iv HTML URL
        
    Returns:
        HTML content as string
        
    Raises:
        httpx.HTTPError: If fetch fails
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(html_url)
        response.raise_for_status()
        return response.text

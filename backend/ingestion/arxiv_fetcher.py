"""
ArXiv paper fetcher for the ingestion pipeline.

Fetches paper metadata from the arXiv API and downloads PDFs.
Also checks for ar5iv HTML availability.
"""

import asyncio
import logging
import re
import arxiv
import httpx
from datetime import datetime
from typing import Optional

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


def extract_version(arxiv_id: str) -> Optional[int]:
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


async def fetch_paper_meta(arxiv_id: str) -> ArxivPaperMeta:
    """
    Fetch paper metadata from arXiv API.
    
    Args:
        arxiv_id: arXiv paper ID (e.g., "1706.03762" or "1706.03762v1")
        
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
    
    max_retries = 4
    last_error = None

    for attempt in range(max_retries):
        try:
            # Create search client
            client = arxiv.Client()

            # Search for the paper
            search = arxiv.Search(
                id_list=[search_id],
                max_results=1
            )

            # Get results (arxiv library is synchronous)
            results = list(client.results(search))
            break  # Success

        except Exception as e:
            error_msg = str(e)
            last_error = e

            # Retry on rate limit (429)
            if "429" in error_msg:
                wait = 3 * (2 ** attempt)  # 3s, 6s, 12s, 24s
                logger.warning(f"arXiv rate limited (429), retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait)
                continue

            # Non-retryable errors — raise immediately
            if "400" in error_msg or "Bad Request" in error_msg:
                raise ValueError(f"Invalid arXiv ID: '{arxiv_id}' - arXiv API rejected the request")
            elif "404" in error_msg or "Not Found" in error_msg:
                raise ValueError(f"Paper not found on arXiv: '{arxiv_id}'")
            elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                raise ConnectionError(f"Could not connect to arXiv API: {e}")
            else:
                raise ValueError(f"Error fetching paper '{arxiv_id}': {e}")
    else:
        # All retries exhausted
        raise ValueError(f"Error fetching paper '{arxiv_id}' after {max_retries} retries: {last_error}")
    
    if not results:
        raise ValueError(f"Paper not found on arXiv: '{arxiv_id}'")
    
    paper = results[0]
    
    # Build PDF URL
    pdf_url = f"https://arxiv.org/pdf/{base_id}.pdf"
    
    # Check for ar5iv HTML availability
    html_url = await check_ar5iv_available(base_id)
    
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


async def check_ar5iv_available(arxiv_id: str) -> Optional[str]:
    """
    Check if ar5iv HTML version is available for this paper.
    
    Args:
        arxiv_id: Normalized arXiv ID (without version)
        
    Returns:
        ar5iv URL if available, None otherwise
    """
    url = f"https://ar5iv.org/abs/{arxiv_id}"
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            response = await client.head(url)
            
            if response.status_code == 200:
                return url
            
    except httpx.RequestError:
        # Network error, ar5iv might be down
        pass
    
    return None


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

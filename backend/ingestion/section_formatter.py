"""
LLM-based section formatter for ArXiviz.

Takes raw extracted section content and produces clean, well-formatted
summaries using OpenAI's API. Runs after section_extractor in the pipeline.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from models.paper import Section, ArxivPaperMeta

# Load .env so MARTIAN_API_KEY is available when called from any entry point
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

logger = logging.getLogger(__name__)

# Lazy-initialized client
_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    """Get or create the OpenAI client (pointed at Martian router)."""
    global _client
    if _client is None:
        api_key = os.getenv("MARTIAN_API_KEY")
        if not api_key:
            print("[FORMATTER] ERROR: MARTIAN_API_KEY not set in environment!")
            raise RuntimeError(
                "MARTIAN_API_KEY environment variable is required for section formatting. "
                "Set it in your .env file or environment."
            )
        print(f"[FORMATTER] Initializing Martian client (key: {api_key[:8]}...)")
        _client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.withmartian.com/v1",
        )
    return _client


SYSTEM_PROMPT = """\
You are a technical writing assistant that reformats academic paper sections into clean, readable summaries.

Given the raw extracted text of a section from an academic paper, produce a well-formatted summary that:

1. Preserves all key technical information, claims, and results
2. Uses clean markdown formatting (headers, bullet points, bold for emphasis where appropriate)
3. Removes parsing artifacts, broken formatting, random whitespace, and garbled text
4. Keeps mathematical notation intact (LaTeX expressions like $...$ or $$...$$)
5. Maintains the original meaning — do NOT add information that isn't in the source
6. Is concise but thorough — aim for roughly 40-60% of the original length
7. Uses clear paragraph breaks and logical flow

If the section content is already well-formatted and clean, return it mostly as-is with minor cleanup.
If the content is very short (a few sentences), just clean it up without trying to summarize.

Return ONLY the formatted summary text. No preamble, no "Here is the summary:", just the content."""


async def format_section(
    section: Section,
    paper_title: str,
    model: str = "openai/gpt-4.1",
) -> str:
    """
    Format a single section's content using an LLM via Martian.

    Args:
        section: The section to format
        paper_title: Title of the paper (for context)
        model: Martian model identifier (e.g. "openai/gpt-4.1")

    Returns:
        Formatted summary string
    """
    client = _get_client()

    # Skip very short sections — just clean them up
    if len(section.content.split()) < 20:
        return section.content.strip()

    user_prompt = f"""Paper: "{paper_title}"
Section: "{section.title}"

Raw content:
{section.content}"""

    try:
        print(f"[FORMATTER] Calling Martian API for section: {section.title[:50]}...")
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,  # Low temperature for consistent formatting
            max_tokens=2000,
        )
        result = response.choices[0].message.content.strip()
        print(f"[FORMATTER] Success for section: {section.title[:50]} ({len(result)} chars)")
        return result
    except Exception as e:
        print(f"[FORMATTER] ERROR for section '{section.title}': {type(e).__name__}: {e}")
        logger.error(f"LLM formatting failed for section '{section.title}': {e}")
        # Graceful fallback: return the original content
        return section.content


async def format_sections(
    sections: list[Section],
    meta: ArxivPaperMeta,
    model: str = "openai/gpt-4.1",
    max_concurrent: int = 5,
) -> list[Section]:
    """
    Format all sections using LLM, populating the `summary` field.

    Runs requests concurrently with a semaphore to respect rate limits.

    Args:
        sections: List of sections to format
        meta: Paper metadata for context
        model: Martian model identifier (e.g. "openai/gpt-4.1")
        max_concurrent: Max concurrent API calls

    Returns:
        The same list of sections with `summary` fields populated
    """
    if not sections:
        return sections

    print(f"\n[FORMATTER] === Starting LLM formatting for {len(sections)} sections (model={model}) ===")
    logger.info(f"Formatting {len(sections)} sections with LLM ({model})")

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _format_one(section: Section) -> None:
        async with semaphore:
            summary = await format_section(section, meta.title, model)
            section.summary = summary

    # Run all formatting tasks concurrently
    tasks = [_format_one(section) for section in sections]
    await asyncio.gather(*tasks)

    logger.info(f"Finished formatting {len(sections)} sections")
    return sections

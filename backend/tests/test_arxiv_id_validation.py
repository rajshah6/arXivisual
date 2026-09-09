"""arXiv id validation at the API boundary.

From the first hour of real (Turnstile-verified) traffic: '0805.3898v2' was
accepted with its version suffix and crashed generation with a None paper
lookup (the row is stored under the base id), and a medRxiv DOI path was
accepted, spent a job/workflow/daily-cap slot, then failed at ingestion.
"""

import pytest
from pydantic import ValidationError

from api.schemas import ProcessRequest


@pytest.mark.parametrize("raw, canonical", [
    ("1706.03762", "1706.03762"),
    ("1706.03762v7", "1706.03762"),
    ("0805.3898v2", "0805.3898"),
    ("  arXiv:2301.00002 ", "2301.00002"),
    ("cs/0123456v2", "cs/0123456"),
    ("hep-th/9711200", "hep-th/9711200"),
])
def test_valid_ids_are_normalized(raw, canonical):
    assert ProcessRequest(arxiv_id=raw).arxiv_id == canonical


@pytest.mark.parametrize("raw", [
    "10.64898/2026.06.29.26356713v1.full.pdf",
    "https://arxiv.org/abs/1706.03762",
    "attention is all you need",
    "",
    "1706",
])
def test_non_arxiv_ids_are_rejected(raw):
    with pytest.raises(ValidationError, match="Not an arXiv identifier"):
        ProcessRequest(arxiv_id=raw)

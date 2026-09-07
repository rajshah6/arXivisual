"""Ingestion correctness guards (no network).

Reviewer-confirmed defects pinned here: ar5iv redirected unconverted ids to
the arXiv ABSTRACT page and ~31% of the library was ingested as a 300-word
inflation of the abstract; the organizer echoed its own prompt header into
section 1; equations were hard-coded to []; the summarizer prompt was a
non-raw string whose \\t corrupted its own instructions; brace-unescaping ran
on substituted LaTeX.
"""

import asyncio

import pytest

from agents.base import BaseAgent
from ingestion import arxiv_fetcher, section_formatter
from ingestion.html_parser import looks_like_latexml_paper
from ingestion.section_formatter import (
    SUMMARIZE_SYSTEM_PROMPT,
    SourceTooShortError,
    _equations_from_summary,
    strip_prompt_scaffold,
)
from tests.conftest import make_fake_http_client

ABSTRACT_PAGE = "<html><body><main><h1>Title</h1><blockquote class='abstract'>..</blockquote></main></body></html>"
LATEXML_PAGE = "<html><body><article class='ltx_document'><section class='ltx_section'>..</section></article></body></html>"


class TestHtmlAvailability:
    """Redirect shapes pinned to what the real hosts emit: arxiv.org/html
    answers 200 or 404; ar5iv.labs.arxiv.org/html answers 200 when converted
    and 307 -> arxiv.org/abs/{id} when not."""

    def test_unconverted_id_yields_none_not_the_abstract_page(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", make_fake_http_client({
            "https://arxiv.org/html/2608.13717": (404, {}),
            "https://ar5iv.labs.arxiv.org/html/2608.13717": (307, {"location": "https://arxiv.org/abs/2608.13717"}),
        }))
        assert asyncio.run(arxiv_fetcher.find_latexml_html_url("2608.13717")) is None

    def test_arxiv_html_preferred_when_present(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", make_fake_http_client({
            "https://arxiv.org/html/2608.13717": (200, {}),
        }))
        assert asyncio.run(arxiv_fetcher.find_latexml_html_url("2608.13717")) == "https://arxiv.org/html/2608.13717"

    def test_ar5iv_labs_fallback_when_converted(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", make_fake_http_client({
            "https://arxiv.org/html/1706.03762": (404, {}),
            "https://ar5iv.labs.arxiv.org/html/1706.03762": (200, {}),
        }))
        assert asyncio.run(arxiv_fetcher.find_latexml_html_url("1706.03762")) == "https://ar5iv.labs.arxiv.org/html/1706.03762"

    def test_relative_redirect_to_versioned_html_is_resolved_and_verified(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", make_fake_http_client({
            "https://arxiv.org/html/1706.03762": (301, {"location": "/html/1706.03762v7"}),
            "https://arxiv.org/html/1706.03762v7": (200, {}),
        }))
        assert asyncio.run(arxiv_fetcher.find_latexml_html_url("1706.03762")) == "https://arxiv.org/html/1706.03762v7"

    def test_redirect_off_latexml_hosts_is_rejected(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", make_fake_http_client({
            "https://arxiv.org/html/1.2": (302, {"location": "https://evil.example/html/1.2"}),
            "https://ar5iv.labs.arxiv.org/html/1.2": (404, {}),
        }))
        assert asyncio.run(arxiv_fetcher.find_latexml_html_url("1.2")) is None

    def test_body_validation(self):
        assert looks_like_latexml_paper(LATEXML_PAGE)
        assert not looks_like_latexml_paper(ABSTRACT_PAGE)


class TestSummarizer:
    def test_prompt_is_raw_so_tex_commands_survive(self):
        assert "\\textsc" in SUMMARIZE_SYSTEM_PROMPT
        assert "\t" not in SUMMARIZE_SYSTEM_PROMPT
        # The raw-string change must not turn the old line-continuation into content.
        assert SUMMARIZE_SYSTEM_PROMPT.startswith("You are")

    def test_short_source_is_refused(self):
        with pytest.raises(SourceTooShortError, match="abstract"):
            asyncio.run(section_formatter._summarize_paper("word " * 120, "T", 120, "gpt-5-mini"))

    def test_target_does_not_inflate(self, monkeypatch):
        captured = {}

        async def fake_llm(prompt, model, system_prompt, max_tokens):
            captured["system"] = system_prompt
            return "summary text"

        monkeypatch.setattr(section_formatter, "call_llm", fake_llm)
        asyncio.run(section_formatter._summarize_paper("w " * 400, "T", 400, "m"))
        # 35% of 400 = 140: no floor of any kind (the old max(300, ...) inflated)
        assert "~140 words" in captured["system"]


class TestOrganizerScaffold:
    def test_header_and_delimiters_stripped(self):
        text = 'Paper: "Cognitive computational neuroscience"\n\nSummarized text to organize into sections:\n\nThe goal is X.'
        assert strip_prompt_scaffold(text) == "The goal is X."
        assert strip_prompt_scaffold("<summary>\nBody\n</summary>") == "Body"
        assert strip_prompt_scaffold("Plain body") == "Plain body"

    def test_new_header_sentence_stripped_but_inline_tag_kept(self):
        text = 'Paper: "X"\n\nThe text to organize is between the <summary> tags. The tags and this header are NOT content.\n\nBody here.'
        assert strip_prompt_scaffold(text) == "Body here."
        # A <summary> element mentioned in prose (HTML papers) is content.
        assert strip_prompt_scaffold("We use a <summary> token to mark boundaries.") == "We use a <summary> token to mark boundaries."


class TestEquationCarryThrough:
    def test_display_and_inline_math_extracted_currency_ignored(self):
        text = (
            "Attention is\n$$\n\\mathrm{softmax}(QK^T/\\sqrt{d})V\n$$\nwith $d_k = 64$ heads. "
            "Prices were $5 and $10 per unit."
        )
        eqs = _equations_from_summary(text)
        latex = [e.latex for e in eqs]
        assert "\\mathrm{softmax}(QK^T/\\sqrt{d})V" in latex
        assert "d_k = 64" in latex
        assert not any("5 and" in item for item in latex)
        assert [e.is_inline for e in eqs] == [False, True]

    def test_money_and_prose_spans_rejected_and_deduped(self):
        text = "It costs $5 < $10 today. Also $x = y$ and again $x = y$ and $the model then uses the same trick$."
        latex = [e.latex for e in _equations_from_summary(text)]
        assert latex == ["x = y"]


class TestPromptBraces:
    def test_template_escapes_unescaped_but_content_preserved(self, tmp_path, monkeypatch):
        agent = BaseAgent.__new__(BaseAgent)
        agent.prompt_template = "Example: {{x}} -> Section: {section}"
        out = agent._format_prompt(section="\\frac{{a}}{{b}}")
        assert out == "Example: {x} -> Section: \\frac{{a}}{{b}}"

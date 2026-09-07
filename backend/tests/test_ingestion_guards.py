"""Ingestion correctness guards (no network).

Reviewer-confirmed defects pinned here: ar5iv redirected unconverted ids to
the arXiv ABSTRACT page and ~31% of the library was ingested as a 300-word
inflation of the abstract; the organizer echoed its own prompt header into
section 1; equations were hard-coded to []; the summarizer prompt was a
non-raw string whose \\t corrupted its own instructions; brace-unescaping ran
on substituted LaTeX.
"""

import asyncio

import httpx
import pytest

from agents.base import BaseAgent
from ingestion import arxiv_fetcher, section_formatter
from ingestion.html_parser import looks_like_latexml_paper
from ingestion.section_formatter import (
    SUMMARIZE_SYSTEM_PROMPT,
    extract_equations,
    strip_prompt_scaffold,
)

ABSTRACT_PAGE = "<html><body><main><h1>Title</h1><blockquote class='abstract'>..</blockquote></main></body></html>"
LATEXML_PAGE = "<html><body><article class='ltx_document'><section class='ltx_section'>..</section></article></body></html>"


class TestHtmlAvailability:
    def _client(self, responses):
        """Fake httpx client: url -> (status, headers)."""
        class Resp:
            def __init__(self, status, headers):
                self.status_code, self.headers = status, headers

        class Client:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def head(self, url):
                if url not in responses:
                    raise httpx.RequestError("boom")
                return Resp(*responses[url])
        return Client

    def test_ar5iv_redirect_to_abstract_is_not_html(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", self._client({
            "https://arxiv.org/html/2608.13717": (404, {}),
            "https://ar5iv.org/abs/2608.13717": (302, {"location": "https://arxiv.org/abs/2608.13717"}),
        }))
        assert asyncio.run(arxiv_fetcher.check_ar5iv_available("2608.13717")) is None

    def test_arxiv_html_preferred_when_present(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", self._client({
            "https://arxiv.org/html/2608.13717": (200, {}),
        }))
        assert asyncio.run(arxiv_fetcher.check_ar5iv_available("2608.13717")) == "https://arxiv.org/html/2608.13717"

    def test_redirect_to_versioned_html_is_accepted(self, monkeypatch):
        monkeypatch.setattr(arxiv_fetcher.httpx, "AsyncClient", self._client({
            "https://arxiv.org/html/1706.03762": (301, {"location": "https://arxiv.org/html/1706.03762v7"}),
        }))
        assert asyncio.run(arxiv_fetcher.check_ar5iv_available("1706.03762")) == "https://arxiv.org/html/1706.03762v7"

    def test_body_validation(self):
        assert looks_like_latexml_paper(LATEXML_PAGE)
        assert not looks_like_latexml_paper(ABSTRACT_PAGE)


class TestSummarizer:
    def test_prompt_is_raw_so_tex_commands_survive(self):
        assert "\\textsc" in SUMMARIZE_SYSTEM_PROMPT
        assert "\t" not in SUMMARIZE_SYSTEM_PROMPT

    def test_short_source_is_refused(self):
        with pytest.raises(ValueError, match="abstract"):
            asyncio.run(section_formatter._summarize_paper("word " * 120, "T", 120, "gpt-5-mini"))

    def test_target_does_not_inflate(self, monkeypatch):
        captured = {}

        async def fake_llm(prompt, model, system_prompt, max_tokens):
            captured["system"] = system_prompt
            return "summary text"

        monkeypatch.setattr(section_formatter, "call_llm", fake_llm)
        asyncio.run(section_formatter._summarize_paper("w " * 500, "T", 500, "m"))
        # 35% of 500 = 175, well under the old hard floor of 300
        assert "~175 words" in captured["system"]


class TestOrganizerScaffold:
    def test_header_and_delimiters_stripped(self):
        text = 'Paper: "Cognitive computational neuroscience"\n\nSummarized text to organize into sections:\n\nThe goal is X.'
        assert strip_prompt_scaffold(text) == "The goal is X."
        assert strip_prompt_scaffold("<summary>\nBody\n</summary>") == "Body"
        assert strip_prompt_scaffold("Plain body") == "Plain body"


class TestEquationCarryThrough:
    def test_display_and_inline_math_extracted_currency_ignored(self):
        text = (
            "Attention is\n$$\n\\mathrm{softmax}(QK^T/\\sqrt{d})V\n$$\nwith $d_k = 64$ heads. "
            "Prices were $5 and $10 per unit."
        )
        eqs = extract_equations(text)
        latex = [e.latex for e in eqs]
        assert "\\mathrm{softmax}(QK^T/\\sqrt{d})V" in latex
        assert "d_k = 64" in latex
        assert not any("5 and" in item for item in latex)
        assert [e.is_inline for e in eqs] == [False, True]


class TestPromptBraces:
    def test_template_escapes_unescaped_but_content_preserved(self, tmp_path, monkeypatch):
        agent = BaseAgent.__new__(BaseAgent)
        agent.prompt_template = "Example: {{x}} -> Section: {section}"
        out = agent._format_prompt(section="\\frac{{a}}{{b}}")
        assert out == "Example: {x} -> Section: \\frac{{a}}{{b}}"

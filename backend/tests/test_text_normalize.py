"""Display-text normalization, pinned to samples quoted from live papers in
the Sept 2026 audit (the 'regex on the site') and to the reviewer-found
failure modes: currency vs. inline math starting with a digit, idempotency
across ingest + read, adjacent commands, nested braces, code spans."""

import pytest

from ingestion.section_formatter import _clean_display_text
from ingestion.text_normalize import (
    escape_currency,
    normalize_display_text,
    normalize_math_fences,
    tex_to_text,
    unescape_json_artifacts,
    wrap_bare_tex,
)

N = normalize_display_text


class TestBareTex:
    def test_prose_commands_get_wrapped_but_math_spans_untouched(self):
        # 2509.23444 section-2 (rendered as literal backslashes on the site)
        text = ("return a chosen fake parameter set \\overline{\\rho} instead of the true one \\rho, "
                "where $\\mathbf{H}[k]$ is given. Each path \\ell has gain \\alpha_\\ell.")
        out = wrap_bare_tex(text)
        assert "$\\overline{\\rho}$" in out
        assert "one $\\rho$," in out
        assert "$\\mathbf{H}[k]$" in out and "$$\\mathbf{H}[k]$$" not in out
        assert "$\\alpha_\\ell$" in out

    def test_adjacent_commands_are_one_span(self):
        # Wrapping one at a time produced $a$$b$: one span containing $$ (red KaTeX)
        assert wrap_bare_tex("maps \\mathbf{x}\\in\\mathbb{R}^n to") == "maps $\\mathbf{x}\\in\\mathbb{R}^n$ to"
        assert wrap_bare_tex("decay \\psi\\pi^+\\pi^- observed") == "decay $\\psi\\pi^+\\pi^-$ observed"

    def test_nested_braces_kept_whole(self):
        assert wrap_bare_tex("estimate \\overline{\\bm{\\theta}} here") == "estimate $\\overline{\\bm{\\theta}}$ here"

    def test_style_commands_become_markdown(self):
        assert wrap_bare_tex("a \\textbf{BadNet} with 95.73\\% accuracy \\cite{x}") == "a **BadNet** with 95.73% accuracy "

    def test_delimiters_converted(self):
        assert wrap_bare_tex("as \\(x^2\\) shows") == "as $x^2$ shows"
        assert wrap_bare_tex("so \\[E=mc^2\\] holds") == "so \n$$\nE=mc^2\n$$\n holds"

    def test_code_and_paths_untouched(self):
        assert wrap_bare_tex("run `\\alpha` in code") == "run `\\alpha` in code"
        assert wrap_bare_tex("```\n\\alpha\n```") == "```\n\\alpha\n```"
        assert wrap_bare_tex("open C:\\Users\\me and foo\\bar") == "open C:\\Users\\me and foo\\bar"


class TestFences:
    def test_inline_close_moves_to_own_line(self):
        # 1706.03762 section-2: equation, prose and the literal $$ were one KaTeX error
        text = "PE is\n$$\nPE_{(pos,2i+1)} = \\cos(x).$$ Intuition: each dimension is a sinusoid."
        assert normalize_math_fences(text) == "PE is\n$$\nPE_{(pos,2i+1)} = \\cos(x).\n$$\n\nIntuition: each dimension is a sinusoid."

    def test_closed_block_does_not_capture_a_later_inline_span(self):
        text = "$$\nx=1\n$$\nthen inline $$y$$ here"
        assert normalize_math_fences(text) == text

    def test_escaped_dollar_closer_and_tag(self):
        text = "$$\n\\mathbf{u}_t = f(x) \\tag{1}\n\\$"
        out = normalize_math_fences(text)
        assert out.count("$$") == 2 and "\\tag" not in out and "\\$" not in out

    def test_odd_fence_count_closed(self):
        assert normalize_math_fences("intro\n$$\nx=1").count("$$") == 2


class TestJsonArtifacts:
    def test_unicode_escapes_double_backslashes_literal_newlines(self):
        text = "S \\u2248 30 with W[\\\\mathbf{p}] = \\\\sum_i f\\n  next"
        out = unescape_json_artifacts(text)
        assert "S \u2248 30" in out
        assert "\\mathbf{p}" in out and "\\\\mathbf" not in out
        assert "\\sum_i" in out
        assert "f\n  next" in out

    def test_real_tex_commands_starting_with_n_or_u_survive(self):
        assert unescape_json_artifacts("\\nabla f and \\underline{x}") == "\\nabla f and \\underline{x}"

    def test_prose_with_real_newlines_is_not_double_encoded(self):
        text = "Use \\n to break lines.\nRow breaks in math use \\\\ too."
        assert unescape_json_artifacts(text) == text


class TestCurrency:
    def test_semicolon_separated_amounts(self):
        # 2603.03136 section-4 — prose between amounts rendered as a formula
        text = "V^E ~ $391.03M; Harris ~ $191.93M; Biden negligible ($0.017M)."
        assert escape_currency(text).count("\\$") == 3

    def test_pair_of_amounts_in_prose(self):
        assert escape_currency("Prices were $5 and $10 per unit.") == "Prices were \\$5 and \\$10 per unit."
        assert escape_currency("It costs $5 < $10 today.") == "It costs \\$5 < \\$10 today."

    def test_inline_math_starting_with_a_digit_is_left_alone(self):
        # Reviewer: every firing on the live corpus was one of these false positives.
        for text in ("with $2^n$ states", "at most $10\\%$", "cost $3 \\times 10^5$", "exactly $5$ items", "where $d_k = 64$ heads"):
            assert escape_currency(text) == text

    def test_closing_dollar_before_digit_is_not_currency(self):
        assert escape_currency("gain $\\alpha$5 units") == "gain $\\alpha$5 units"


class TestIdempotencyAndFalsePositives:
    SAMPLES = [
        "gain \\alpha_\\ell and $\\beta$",
        "estimate \\bar{\\theta}_R; cost was $391.03M; total $2M.",
        "PE is\n$$\nPE = \\cos(x).$$ Intuition: sinusoid \\alpha_5 then $x$5",
        "maps \\mathbf{x}\\in\\mathbb{R}^n to \\(y\\) via \\[z\\]",
        "\\$5 already escaped and $\\alpha$ later",
        "S \\u2248 30 with W[\\\\mathbf{p}] = \\\\sum_i f",
    ]

    @pytest.mark.parametrize("text", SAMPLES)
    def test_applying_twice_equals_once(self, text):
        once = N(text)
        assert N(once) == once

    NO_OPS = [
        "Prices were \\$5 and \\$10 per unit.",
        "run `\\alpha` in code and ```\n\\beta\n```",
        "open C:\\Users\\me and foo\\bar",
        "Use \\n to break lines.\nSecond line.",
        "$$\na \\\\ b\n$$",
        "with $2^n$ states and where $d_k = 64$ heads",
    ]

    @pytest.mark.parametrize("text", NO_OPS)
    def test_legitimate_text_is_untouched(self, text):
        assert N(text) == text


class TestSingleOwner:
    def test_ingest_and_read_time_agree(self):
        text = "\\textsc{BadNet} is a \\textbf{backdoor} with 95\\% and $391M cost"
        assert _clean_display_text(text) == N(text)
        assert N(text) == "BadNet is a **backdoor** with 95% and \\$391M cost"

    def test_split_small_caps_and_zero_width(self):
        assert N("\\textscBASE and\nL\nA\nR\nG\nE\ndone\u200b") == "BASE and\nLARGE\ndone"

    def test_abstract_path_skips_organizer_only_rules(self):
        text = 'Paper: "X"\n\nThe text to organize is between the <summary> tags. y\n\nbody'
        assert N(text) == "body"
        assert N(text, from_organizer=False).startswith('Paper: "X"')


class TestScaffoldAndPipeline:
    def test_full_pipeline_on_live_shape(self):
        text = ('Paper: "X"\n\nSummarized text to organize into sections:\n\n'
                "The estimate \\bar{\\theta}_R is updated online; cost was $391.03M; total $2M.")
        out = N(text)
        assert out.startswith("The estimate $\\bar{\\theta}_R$")
        assert "\\$391.03M" in out and "\\$2M" in out


class TestTitles:
    def test_tex_titles_become_plain_text(self):
        assert tex_to_text("H$_2$O: Heavy-Hitter Oracle") == "H\u2082O: Heavy-Hitter Oracle"
        assert tex_to_text("Marshall Quotients of the Rings $\\mathbb Z/n\\mathbb Z$") == "Marshall Quotients of the Rings Z/nZ"
        assert tex_to_text("Unitary Yang--Baxter Operators") == "Unitary Yang\u2013Baxter Operators"
        assert tex_to_text("Maximizers of the $L^2\\to L^4$ inequality") == "Maximizers of the L\u00b2\u2192L\u2074 inequality"
        assert tex_to_text("\\emph{BadNet} at 95\\%") == "BadNet at 95%"

    def test_symbols_and_unknown_commands_are_not_deleted(self):
        assert tex_to_text("$\\alpha$-decay of $\\ell_\\infty$ norms") == "α-decay of ℓ∞ norms"
        assert tex_to_text("the $\\softmax$ trick") == "the softmax trick"

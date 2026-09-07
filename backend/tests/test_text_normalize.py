"""Display-text normalization, pinned to samples quoted from live papers in
the Sept 2026 audit (the 'regex on the site')."""

from ingestion.text_normalize import (
    escape_currency,
    normalize_display_text,
    normalize_math_fences,
    tex_to_text,
    unescape_json_artifacts,
    wrap_bare_tex,
)


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

    def test_style_commands_become_markdown(self):
        assert wrap_bare_tex("a \\textbf{BadNet} with 95.73\\% accuracy \\cite{x}") == "a **BadNet** with 95.73% accuracy "

    def test_no_double_wrapping_is_idempotent(self):
        once = normalize_display_text("gain \\alpha_\\ell and $\\beta$")
        assert normalize_display_text(once) == once


class TestFences:
    def test_inline_close_moves_to_own_line(self):
        # 1706.03762 section-2: equation, prose and the literal $$ were one KaTeX error
        text = "PE is\n$$\nPE_{(pos,2i+1)} = \\cos(x).$$ Intuition: each dimension is a sinusoid."
        out = normalize_math_fences(text)
        assert "\\cos(x).\n$$\n\nIntuition" in out.replace("\\cos(x).\n$$\n\n Intuition", "\\cos(x).\n$$\n\nIntuition")

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


class TestCurrency:
    def test_semicolon_separated_amounts(self):
        # 2603.03136 section-4 — prose between amounts rendered as a formula
        text = "V^E ~ $391.03M; Harris ~ $191.93M; Biden negligible ($0.017M)."
        out = escape_currency(text)
        assert out.count("\\$") == 3

    def test_pair_of_amounts_in_prose(self):
        assert escape_currency("Prices were $5 and $10 per unit.") == "Prices were \\$5 and \\$10 per unit."

    def test_inline_math_not_escaped(self):
        assert escape_currency("where $d_k = 64$ heads") == "where $d_k = 64$ heads"


class TestScaffoldAndPipeline:
    def test_full_pipeline_on_live_shape(self):
        text = ('Paper: "X"\n\nSummarized text to organize into sections:\n\n'
                "The estimate \\bar{\\theta}_R is updated online; cost was $391.03M; total $2M.")
        out = normalize_display_text(text)
        assert out.startswith("The estimate $\\bar{\\theta}_R$")
        assert "\\$391.03M" in out and "\\$2M" in out


class TestTitles:
    def test_tex_titles_become_plain_text(self):
        assert tex_to_text("H$_2$O: Heavy-Hitter Oracle") == "H\u2082O: Heavy-Hitter Oracle"
        assert tex_to_text("Marshall Quotients of the Rings $\\mathbb Z/n\\mathbb Z$") == "Marshall Quotients of the Rings Z/nZ"
        assert tex_to_text("Unitary Yang--Baxter Operators") == "Unitary Yang\u2013Baxter Operators"
        assert tex_to_text("Maximizers of the $L^2\\to L^4$ inequality") == "Maximizers of the L\u00b2\u2192L\u2074 inequality"
        assert tex_to_text("\\emph{BadNet} at 95\\%") == "BadNet at 95%"

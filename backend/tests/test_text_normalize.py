"""Display-text normalization, pinned to samples quoted from live papers in
the Sept 2026 audit (the 'regex on the site') and to the reviewer-found
failure modes: currency vs. inline math starting with a digit, idempotency
across ingest + read, adjacent commands, nested braces, code spans."""

import pytest

from ingestion.section_formatter import _clean_display_text
from ingestion.text_normalize import (
    escape_currency,
    label_to_text,
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

    # A list item's block closed at column 0 ends the item, and every later $$
    # pairs with the wrong partner (1609.03851: 11 KaTeX errors). Each closer
    # the walk writes takes the opener's indentation; the first case is the
    # stored shape, repaired at read time.
    @pytest.mark.parametrize(("text", "expected"), [
        ("- a:\n  $$\n  x = 1\n$$\n  where $y$", "- a:\n  $$\n  x = 1\n  $$\n  where $y$"),
        ("- a:\n  $$\n  x = 1\n  \\$\n  where $y$", "- a:\n  $$\n  x = 1\n  $$\n  where $y$"),
        ("- a:\n  $$\n  x = 1.$$ where $y$", "- a:\n  $$\n  x = 1.\n  $$\n\n  where $y$"),
        ("- a:\n  $$\n  x = 1 $$\n  where $y$", "- a:\n  $$\n  x = 1\n  $$\n  where $y$"),
        ("- a:\n  $$\n  x = 1", "- a:\n  $$\n  x = 1\n  $$"),
    ])
    def test_closer_takes_the_opener_indentation(self, text, expected):
        assert normalize_math_fences(text) == expected

    def test_one_line_display_is_split_onto_fence_lines(self):
        # 1301.0081: remark-math renders a one-line $$...$$ as inline math.
        assert normalize_math_fences("so\n\n$$K \\le c$$\n\nfor all") == "so\n\n$$\nK \\le c\n$$\n\nfor all"
        assert normalize_math_fences("- prior:\n  $$p_n \\propto 2^{-K(n)}.$$") == (
            "- prior:\n  $$\n  p_n \\propto 2^{-K(n)}.\n  $$"
        )

    def test_glued_multiline_opener_gets_its_own_line(self):
        # 1903.06586: "$$x,\qquad" read as the fence's meta, closer never found.
        text = "1. Split:\n   $$U = F(X),\\qquad\n   V = G(X),$$\n   next"
        assert normalize_math_fences(text) == "1. Split:\n   $$\n   U = F(X),\\qquad\n   V = G(X),\n   $$\n   next"
        # The closing $$ the walk adds at the end closes it too.
        assert normalize_math_fences("$$x = 1\nprose") == "$$\nx = 1\nprose\n$$"

    def test_glued_opener_without_a_later_closer_is_not_split(self):
        assert normalize_math_fences("$$x = 1\nso $$y$$ here").split("\n")[0] == "$$x = 1"

    def test_one_line_pair_inside_a_code_fence_is_not_split(self):
        text = "```\n$$x$$\n```"
        assert normalize_math_fences(text) == text


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

    def test_literal_newline_residue_beside_real_newlines(self):
        # 2004.07558: rendered as a literal "\n\n" and an unbroken list.
        text = "Pack[$P$].\\n\\nKey types:\\n- Motions\\n- Pieces\n\nWith rotations, hard."
        assert unescape_json_artifacts(text) == "Pack[$P$].\n\nKey types:\n- Motions\n- Pieces\n\nWith rotations, hard."

    def test_residue_next_to_a_real_break_leaves_no_blank_run(self):
        assert unescape_json_artifacts("A.\n\\n\\nB\nC") == "A.\n\nB\nC"

    def test_literal_newlines_in_code_are_kept(self):
        text = "Split on `a\\n\\nB` here.\n```\nx = \"\\n\\nY\"\n```"
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

    def test_one_token_digit_led_span_is_math(self):
        for text in ("dimension $6n$ (positions and momenta)", "the $2n-1$ terms"):
            assert escape_currency(text) == text

    def test_stored_escape_before_a_formula_is_undone(self):
        # 1301.0081 was stored as \$6n$ by the older rule.
        assert escape_currency("dimension \\$6n$ here") == "dimension $6n$ here"
        assert escape_currency("the \\$2n-1$ terms") == "the $2n-1$ terms"
        # Every stored escape on a line is undone in the same pass.
        assert escape_currency("a \\$2n$-dimensional phase space with \\$6n$ coordinates") == (
            "a $2n$-dimensional phase space with $6n$ coordinates"
        )
        assert escape_currency("the \\$2n-1$ terms and \\$2n$ others") == "the $2n-1$ terms and $2n$ others"
        # Only the shape the older rule escaped is undone; an escape it never wrote stays.
        for text in ("paid \\$5 for $x$ units", "pay \\$5/unit and $x$ later", "a \\$5$ b"):
            assert escape_currency(text) == text
        # A closer glued to \ or a letter opens a span wrap_bare_tex wrote after the escape.
        for text in ("~\\$5M($\\pm$ 2M)", "the fee \\$5-$x$ per unit", "about \\$5M,$\\ldots$ more"):
            assert escape_currency(text) == text
        assert escape_currency("dimension \\$6n$ and $x$") == "dimension $6n$ and $x$"


class TestIdempotencyAndFalsePositives:
    SAMPLES = [
        "gain \\alpha_\\ell and $\\beta$",
        "estimate \\bar{\\theta}_R; cost was $391.03M; total $2M.",
        "PE is\n$$\nPE = \\cos(x).$$ Intuition: sinusoid \\alpha_5 then $x$5",
        "maps \\mathbf{x}\\in\\mathbb{R}^n to \\(y\\) via \\[z\\]",
        "\\$5 already escaped and $\\alpha$ later",
        "S \\u2248 30 with W[\\\\mathbf{p}] = \\\\sum_i f",
        "- a:\n  $$\n  x = 1\n$$\n  where $y$ and $6n$ \\$6n$",
        "  $$\n  x = 1\n  $$\nthen\n\n- b:\n  $$K \\le c$$",
        "1. Split:\n   $$U = F(X),\\qquad\n   V = G(X),$$ so\n   next",
        "Intro.\\n\\nKey:\\n- a\n\\n\\nB `c\\n\\nD`",
        "rate \\$10\\%$ x",
        "$$x = 1\nprose",
        "$$a = 1,\nb = 2\n\n$$y$$",
        "Revenue ~$5M(\\pm 2M) in 2020.",
        "the fee $5-\\(x\\) per unit",
        "about $5M,\\ldots more",
        "a \\$2n$-dimensional phase space with \\$6n$ coordinates",
        "the \\$2n-1$ terms and \\$2n$ others",
    ]

    @pytest.mark.parametrize("from_organizer", [True, False])
    @pytest.mark.parametrize("text", SAMPLES)
    def test_applying_twice_equals_once(self, text, from_organizer):
        once = N(text, from_organizer=from_organizer)
        assert N(once, from_organizer=from_organizer) == once

    NO_OPS = [
        "Prices were \\$5 and \\$10 per unit.",
        "run `\\alpha` in code and ```\n\\beta\n```",
        "open C:\\Users\\me and foo\\bar",
        "Use \\n to break lines.\nSecond line.",
        "$$\na \\\\ b\n$$",
        "with $2^n$ states and where $d_k = 64$ heads",
        "pay \\$5/unit and $x$ later",
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

    def test_symbol_followed_by_a_script(self):
        # Symbols map before scripts are flattened: $\\phi_i$ used to read "phii".
        assert tex_to_text("$\\phi_i$ and $\\pi^+\\pi^-$ pairs") == "φi and π⁺π⁻ pairs"
        assert tex_to_text("optimum $S^*$ of $x_+$") == "optimum S* of x₊"
        assert tex_to_text("$e^(x)$ growth") == "e^(x) growth"  # only dropped before a symbol

    # TeX's -- is an en dash in a title; labels keep it as written (TestLabels).
    @pytest.mark.parametrize(("title", "expected"), [
        ("Yang--Mills theory", "Yang\u2013Mills theory"),
        ("$\\alpha$--$\\beta$ duality", "α\u2013β duality"),
    ])
    def test_double_dash_is_an_en_dash(self, title, expected):
        assert tex_to_text(title) == expected


class TestLabels:
    """Video concepts are LLM-written plain text that often carries bare TeX."""

    @pytest.mark.parametrize(("label", "expected"), [
        ("Spread operators S_{(j)} and S_{(j)}^* (boundary\u2194grid)", "Spread operators S₍j₎ and S₍j₎* (boundary\u2194grid)"),
        ("Unified encoder: \\Phi(\\bx)=g_{\\theta}(x)", "Unified encoder: Φ(bx)=gθ(x)"),
        ("Levin\\'s prior over K(n)", "Levin's prior over K(n)"),
        ("Pipeline (M_0 \\u2192 cuts) with \\\\theta", "Pipeline (M₀ → cuts) with θ"),
        ("Acoustic scale r_{\\rm d} (drag epoch)", "Acoustic scale rd (drag epoch)"),
        ("Taste (the $\\alpha$-line)", "Taste (the α-line)"),
        ("Fees: $5 and $x$ units", "Fees: $5 and x units"),
        ("f_{} and g", "f and g"),
        ("x_1x_2 coupling", "x₁x₂ coupling"),
        ("T_1T_2 relaxation", "T₁T₂ relaxation"),
    ])
    def test_tex_becomes_plain_text(self, label, expected):
        assert label_to_text(label) == expected
        assert label_to_text(expected) == expected

    @pytest.mark.parametrize("label", [
        "DP realignment", "Teacher -> Student", "JRC_m and G_goal in file_name.py", "Fees of $5 per x_1 call",
        "$5 vs $10 pricing", "Cost reduction from $5M to $2M", "2^10 tokens", "model_2_layers and conv2d_3x3",
        "conv_block_1 and num_heads_8", "train_stage_1.py config", "G_goal_1 vs hidden_state_0",
    ])
    def test_plain_labels_are_unchanged(self, label):
        assert label_to_text(label) == label

    # Arrows and rules, not en dashes: kept as written, also next to TeX and
    # inside a TeX span (the title rule turned "-->" into an en dash and ">").
    @pytest.mark.parametrize(("label", "expected"), [
        ("Encoder --> Decoder pipeline", "Encoder --> Decoder pipeline"),
        ("Decoder <-- Encoder", "Decoder <-- Encoder"),
        ("Encoder <--> Decoder", "Encoder <--> Decoder"),
        ("Before --- after", "Before --- after"),
        ("Yang--Baxter maps", "Yang--Baxter maps"),
        ("x_1 --> \\Phi(x)", "x₁ --> Φ(x)"),
        ("$a--b$ split", "a--b split"),
    ])
    def test_double_dashes_are_kept(self, label, expected):
        assert label_to_text(label) == expected
        assert label_to_text(expected) == expected

    def test_missing_label(self):
        assert label_to_text(None) == "" and label_to_text("") == ""

"""Display-text normalization for section content, summaries and abstracts.

Single owner of every display rule. Applied at ingest (section_formatter)
AND at read time (api.routes), so the ~1,000 already-stored papers are
cleaned without a migration. Idempotent: N(N(x)) == N(x) is pinned by tests.

Every rule maps to an artifact class measured on the live corpus (Sept 2026):

- split small-caps / zero-width junk from PDF text            (legacy)
- prompt scaffold echoed into section 1                       21 papers
- JSON escape residue (\\uXXXX, \\\\command, literal \\n)         23 papers
  (undone at its origin in section_formatter too; the retry suffix in
  agents.base.call_llm_json is what invites the over-escaping)
- display math whose closing $$ is followed by prose           54 papers
- display math in a list item closed at column 0, one-line $$...$$ and
  $$ glued to a multi-line equation's first line (all rendered wrong)
- currency "$391M" parsed as inline-math delimiters
- bare TeX commands in prose rendered as literal backslashes   207 papers
- \\[ \\] / \\( \\) delimiters remark-math does not understand
- bare TeX in video concept labels (label_to_text)
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. Artifact cleanup (PDF small-caps splits, zero-width chars)
# ---------------------------------------------------------------------------
_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\uFEFF]")
_TEXTSC_BARE_RE = re.compile(r"\\textsc\s*(?=[A-Za-z])")  # \textscBASE -> BASE
_LETTER_LINES_RE = re.compile(r"(?m)^(?:[A-Z]\s*\n){2,}[A-Z]\s*$")
_DUP_LINE_RE = re.compile(r"(?m)^([A-Z]{2,})\n\1$")


def clean_artifacts(text: str) -> str:
    """Zero-width characters, letter-per-line small caps (L\\nA\\nR\\nG\\nE),
    brace-less \\textsc markers, runs of blank lines."""
    t = _ZERO_WIDTH_RE.sub("", text)
    t = _LETTER_LINES_RE.sub(lambda m: "".join(ch for ch in m.group(0) if ch.isalpha()), t)
    t = _DUP_LINE_RE.sub(r"\1", t)
    t = _TEXTSC_BARE_RE.sub("", t)
    return re.sub(r"\n{3,}", "\n\n", t)


# ---------------------------------------------------------------------------
# 2. Organizer scaffold + JSON residue (organizer output only)
# ---------------------------------------------------------------------------
_SCAFFOLD_LEAD_RE = re.compile(
    r'^\s*(?:Paper:\s*".*?"\s*\n+)?'
    r"(?:(?:Summarized text to organize into sections:|"
    r"The text to organize is between the <summary> tags\.[^\n]*)\s*\n+)?"
    r"(?:<summary>\s*)?",
    re.IGNORECASE,
)
_SCAFFOLD_TAIL_RE = re.compile(r"\s*</summary>\s*$", re.IGNORECASE)
_UNICODE_ESC_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
# Literal \n residue in text that also has real newlines: a run of two or more
# (a paragraph break) before a capital, digit, markdown marker, math or the
# end, or any run right before a markdown list item / heading / quote. TeX
# commands that start with n (\nabla, \neq, \nu) are followed by a lowercase
# letter, and a lone \n before a space ("Use \n to split") is prose about it.
_RESIDUE_NL_RE = re.compile(
    r"(?<!\\)(?:(?:\\n){2,}(?=[A-Z0-9*#>$\\(\[-]|\Z)|(?:\\n)+(?=[-*+>] |#{1,6} |\d+[.)] ))"
)
_CODE_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")


def strip_prompt_scaffold(text: str) -> str:
    """Remove the organizer prompt's own header/delimiters if the model echoed
    them — anchored to the section edges only, so a '<summary>' element
    mentioned in body prose survives."""
    t = _SCAFFOLD_LEAD_RE.sub("", text or "", count=1)
    return _SCAFFOLD_TAIL_RE.sub("", t).strip()


def unescape_json_artifacts(text: str) -> str:
    """Undo JSON-escape residue the organizer stored verbatim.

    ``\\uXXXX`` is always residue. The deeper undo (doubled backslashes before
    a command, literal two-character ``\\n``) runs only when the text is
    detectably double-encoded — no real newlines, or ``\\uXXXX`` present —
    so a prose sentence mentioning ``\\n`` and a ``\\\\`` row break inside
    display math survive. Text that does have real newlines can still carry
    literal ``\\n`` residue; only the narrow shapes in ``_RESIDUE_NL_RE``
    (a paragraph break, a break before a list item or heading) are undone,
    and never inside code.
    """
    t = _UNICODE_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    double_encoded = ("\n" not in text and "\\n" in text) or _UNICODE_ESC_RE.search(text) is not None
    if double_encoded:
        t = re.sub(r"\\\\(?=[A-Za-z])", r"\\", t)
        t = re.sub(r"\\n(?=[\s$])", "\n", t)
    return _undo_residue_newlines(t)


def _undo_residue_newlines(text: str) -> str:
    """Undo the ``_RESIDUE_NL_RE`` shapes outside code spans and fences."""
    code = [m.span() for m in _CODE_RE.finditer(text)]

    def sub(m: re.Match) -> str:
        if any(start <= m.start() < end for start, end in code):
            return m.group(0)
        return "\n" * m.group(0).count("\\n")

    t = _RESIDUE_NL_RE.sub(sub, text)
    # clean_artifacts collapsed blank-line runs before this ran; a residue
    # break next to a real one must not leave a run a second pass collapses.
    return re.sub(r"\n{3,}", "\n\n", t) if t != text else t


# ---------------------------------------------------------------------------
# 3. Display-math fences (line walk, never a regex across fences)
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"\\tag\{[^}]*\}")


def _one_line_display(s: str) -> str | None:
    """The TeX of a stripped line that is exactly one $$...$$ pair, else None."""
    if s.startswith("$$") and s.endswith("$$") and s.count("$$") == 2:
        return s[2:-2].strip() or None
    return None


def _glued_opener(s: str) -> bool:
    """A stripped line that is a ``$$`` with the equation's first line glued on."""
    return len(s) > 2 and s.startswith("$$") and s.count("$$") == 1


def _closed_later(done: list[str], rest: list[str]) -> bool:
    """The glued opener ``rest[0]`` is closed once the walk is done.

    It is when the next line holding a ``$$`` ends with its only one or is
    a one-line pair (the walk puts that on fence lines). A later glued
    opener is passed over, since the walk splits it only when this same
    test holds. With neither, the ``$$`` the walk adds to an odd count
    closes it (``done`` is the output so far).
    """
    for line in rest[1:]:
        s = line.strip()
        if "$$" in s and not _glued_opener(s):
            return _one_line_display(s) is not None or (s.endswith("$$") and s.count("$$") == 1)
    return "\n".join(done + rest).count("$$") % 2 == 1


def normalize_math_fences(text: str) -> str:
    """Make display math well-formed for remark-math.

    A ``$$`` opened on its own line must close on its own line, at the
    opener's indentation: a list item's block closed at column 0 ends the
    list item, and every later ``$$`` pairs with the wrong partner. A
    content line that closes with ``$$`` and continues with prose is split
    (the prose keeps the indentation too), a trailing ``$$`` moves to its
    own line, a ``\\$`` closer becomes ``$$``, ``\\tag{}`` (unsupported by
    KaTeX) is dropped, and an odd number of fences is closed at the end
    instead of swallowing the section.

    remark-math renders a one-line ``$$...$$`` as inline math, so a line
    that is exactly one such pair is split onto fence lines; a ``$$y$$`` in
    the middle of prose stays inline. An opener glued to the first line of
    a multi-line equation (``$$x = 1,`` ... ``y = 2.$$``) gets its own
    line too, or remark-math reads the first line as the fence's meta and
    never finds the closer. A ``$$`` inside a code fence opens no block
    and is not split.
    """
    out: list[str] = []
    open_block = False
    in_code = False
    indent = ""
    lines = text.split("\n")
    for k, line in enumerate(lines):
        s = line.strip()
        if not open_block:
            if s.startswith("```"):
                in_code = not in_code
            indent = line[: len(line) - len(line.lstrip())]
            tex = None if in_code else _one_line_display(s)
            if tex is not None:
                out.extend([f"{indent}$$", indent + tex, f"{indent}$$"])
                continue
            if not in_code and _glued_opener(s) and _closed_later(out, lines[k:]):
                out.extend([f"{indent}$$", indent + s[2:].strip()])
                open_block = True
                continue
            if s == "$$" and not in_code:
                open_block = True
            out.append(line)
            continue
        if s in ("$$", "\\$"):
            out.append(f"{indent}$$")
            open_block = False
            continue
        m = re.match(r"^(.*?)\$\$[ \t]*(\S.*)$", line)
        if m and "$$" not in m.group(1):
            # "... = f(x).$$ Intuition: ..." -> equation, closer, blank, prose
            if m.group(1).strip():
                out.append(m.group(1).rstrip())
            out.extend([f"{indent}$$", "", indent + m.group(2)])
            open_block = False
            continue
        if s.endswith("$$") and s.count("$$") == 1:
            out.extend([line[: line.rfind("$$")].rstrip(), f"{indent}$$"])
            open_block = False
            continue
        out.append(line)
    t = "\n".join(out)
    t = _TAG_RE.sub("", t)
    if t.count("$$") % 2 == 1:
        t = t.rstrip() + "\n" + (indent if open_block else "") + "$$"
    return t


# ---------------------------------------------------------------------------
# 4. Currency: decided per `$`, before any span detection
# ---------------------------------------------------------------------------
_MATHISH_RE = re.compile(r"[\\^_=<>+*/]")


def _closed_span(line: str, i: int) -> str | None:
    """The text between the ``$`` at ``line[i]`` and its closing ``$``.

    None when no unescaped ``$`` closes it on the line, or when the closer is
    itself followed by a digit: two amounts (``$5 and $10``, ``$5 < $10``)
    are not a formula.
    """
    j = i + 1
    while True:
        j = line.find("$", j)
        if j == -1:
            return None
        if line[j - 1] != "\\":
            break
        j += 1
    after = line[j + 1] if j + 1 < len(line) else ""
    return None if after.isdigit() else line[i + 1 : j]


def _opens_math(line: str, i: int) -> bool:
    """``line[i]`` is a ``$`` followed by a digit. Does an inline formula follow?

    Money when: no closing ``$`` on the line; the closing ``$`` is itself
    followed by a digit (``$5 and $10``, ``$5 < $10``); or the span between
    reads as prose (spaces / ``;``) rather than a formula. A span that is
    one token (``$5$``, ``$6n$``, ``$2n-1$``) and anything containing TeX or
    operators (``$2^n$``, ``$10\\%$``) is math.
    """
    cand = _closed_span(line, i)
    return cand is not None and (
        not re.search(r"[\s;]", cand) or _MATHISH_RE.search(cand) is not None
    )


def _misread_as_money(line: str, i: int) -> bool:
    """The older rule escaped the ``$`` at ``line[i]`` though a formula follows.

    A stored ``\\$`` is undone only for the shape that rule escaped and the
    current one reads as math: a closed one-token span with no TeX or
    operator that is not a bare number (``\\$6n$``, ``\\$2n-1$``). Any other
    ``\\$`` was written that way (``\\$5/unit and $x$``, ``\\$5$``) and stays.
    A span holding ``%`` or ``&`` stays too, since ``wrap_bare_tex`` unescapes
    ``\\%`` and ``\\&`` and undoing it would break idempotency. So does one
    whose closer is glued to a ``\\`` or a letter: that ``$`` opens a span
    ``wrap_bare_tex`` wrote after the escape (``\\$5M($\\pm$``, ``\\$5-$x$``).
    """
    cand = _closed_span(line, i)
    if cand is None:
        return False
    after = line[i + len(cand) + 2 : i + len(cand) + 3]
    return (
        not re.search(r"[\s;%&]", cand)
        and _MATHISH_RE.search(cand) is None
        and not re.fullmatch(r"[\d.,]+", cand)
        and after != "\\"
        and not after.isalpha()
    )


def _at_token_start(line: str, i: int) -> bool:
    """``line[i]`` starts a token (a ``$`` closing a span or glued to a word does not)."""
    return i == 0 or line[i - 1] in " \t([~-"


def escape_currency(text: str) -> str:
    """``$391M; Harris $191M`` is money, not a formula — escape the ``$``.

    Decided per ``$`` followed by a digit at the start of a token. Only a
    ``\\$`` that an older rule stored in front of a one-token formula
    (``\\$6n$``) is undone, so stored papers are repaired at read time.
    """
    out: list[str] = []
    in_block = False
    in_code = False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
        if s == "$$":
            in_block = not in_block
        if in_block or in_code or "$" not in line:
            out.append(line)
            continue
        chars = list(line)
        i = 0
        while i < len(chars):
            if chars[i] == "$" and i + 1 < len(chars) and chars[i + 1].isdigit():
                cur = "".join(chars)
                if i > 0 and chars[i - 1] == "\\":
                    if _at_token_start(cur, i - 1) and _misread_as_money(cur, i):
                        del chars[i - 1]
                        i -= 1
                elif _at_token_start(cur, i) and not _opens_math(cur, i):
                    chars.insert(i, "\\")
                    i += 1
            i += 1
        out.append("".join(chars))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 5. Prose rewriting outside protected spans
# ---------------------------------------------------------------------------
_BRACE = r"\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}"  # three nesting levels
_TOKEN = rf"\\[A-Za-z]{{2,}}(?:{_BRACE}|[_^](?:{_BRACE}|\\[A-Za-z]+|[A-Za-z0-9+\-*]))*"
# A run of adjacent commands (\mathbf{x}\in\mathbb{R}^n, \psi\pi^+\pi^-) is
# ONE span; wrapping them one at a time produced $a$$b$ — read by remark-math
# as a single span containing $$. Not in path/word context (C:\Users, foo\bar)
# and never right after another backslash.
_BARE_TEX_RE = re.compile(rf"(?<![\w.\\:])(?:{_TOKEN})(?:[^\s$`\\]{{0,4}}?(?:{_TOKEN}))*")
_PROTECTED_RE = re.compile(
    r"```[\s\S]*?```"
    r"|`[^`\n]+`"
    r"|\$\$[\s\S]*?\$\$"
    r"|\\\[[\s\S]*?\\\]"
    r"|\\\([\s\S]*?\\\)"
    r"|(?<!\\)\$(?:[^$\n\\]|\\.)+?(?<!\\)\$"
)
_STYLE_RE = re.compile(rf"\\(textbf|textit|emph|textsc|texttt|text)({_BRACE})")
_STYLE_MD = {"textbf": "**{}**", "textit": "*{}*", "emph": "*{}*"}
_REF_RE = re.compile(rf"\\(?:cite|ref|label|citep|citet)(?:\[[^\]]*\])?{_BRACE}")
_URL_RE = re.compile(r"\\url\{([^}]*)\}")


def _strip_styles(text: str, markdown: bool) -> str:
    """\\textbf{x} -> **x** (markdown) or x (plain); \\% \\& unescaped."""

    def sub(m: re.Match) -> str:
        inner = m.group(2)[1:-1]
        return (_STYLE_MD.get(m.group(1), "{}") if markdown else "{}").format(inner)

    return _STYLE_RE.sub(sub, text).replace(r"\%", "%").replace(r"\&", "&")


def _rewrite_prose(segment: str) -> str:
    seg = _strip_styles(segment, markdown=True)
    seg = _REF_RE.sub("", seg)
    seg = _URL_RE.sub(r"\1", seg)
    return _BARE_TEX_RE.sub(lambda m: f"${m.group(0)}$", seg)


def _rewrite_span(span: str) -> str:
    if span.startswith("\\["):
        return "\n$$\n" + span[2:-2].strip() + "\n$$\n"
    if span.startswith("\\("):
        return "$" + span[2:-2].strip() + "$"
    return span


def wrap_bare_tex(text: str) -> str:
    """Wrap TeX tokens that sit outside any protected span in ``$...$`` and
    convert ``\\[ \\]`` / ``\\( \\)`` delimiters. Code spans and fences are
    emitted verbatim."""
    out: list[str] = []
    pos = 0
    for m in _PROTECTED_RE.finditer(text):
        out.append(_rewrite_prose(text[pos : m.start()]))
        out.append(_rewrite_span(m.group(0)))
        pos = m.end()
    out.append(_rewrite_prose(text[pos:]))
    return "".join(out)


def normalize_display_text(text: str | None, *, from_organizer: bool = True) -> str:
    """The full pipeline, idempotent — safe to apply at ingest and at read.

    ``from_organizer=False`` (arXiv abstracts) skips the scaffold strip and the
    JSON-residue undo, which only make sense for organizer output. The text
    is stripped before the fence pass so a first-line opener's indentation
    is the same on every pass.
    """
    if not text:
        return ""
    t = clean_artifacts(text)
    if from_organizer:
        t = strip_prompt_scaffold(t)
        t = unescape_json_artifacts(t)
    t = normalize_math_fences(t.strip())
    t = escape_currency(t)
    t = wrap_bare_tex(t)
    return t.strip()


# ---------------------------------------------------------------------------
# 6. Plain-text titles
# ---------------------------------------------------------------------------
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_SUP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "times": "×", "cdot": "·", "infty": "∞",
    "sim": "∼", "approx": "≈", "neq": "≠", "leq": "≤", "geq": "≥", "le": "≤", "ge": "≥",
    "pm": "±", "ell": "ℓ", "partial": "∂", "nabla": "∇", "sum": "Σ", "prod": "Π",
    "int": "∫", "in": "∈", "subset": "⊂", "cup": "∪", "cap": "∩", "circ": "∘", "star": "★",
    "log": "log", "ln": "ln", "exp": "exp", "min": "min", "max": "max", "sin": "sin", "cos": "cos",
}
_TITLE_MATH_RE = re.compile(r"\$([^$]+)\$")


def tex_to_text(title: str | None) -> str:
    """Plain-text rendering of a TeX-flavoured title for cards, hero, <title>.

    ``H$_2$O`` -> ``H\u2082O``; ``Rings $\\mathbb Z/n\\mathbb Z$`` -> ``Rings Z/nZ``;
    ``$\\alpha$-decay`` -> ``α-decay``; unknown commands keep their name.
    """
    return _plain_text(title, _TITLE_MATH_RE)


def _plain_text(text: str | None, math_re: re.Pattern[str], *, en_dash: bool = True) -> str:
    """``tex_to_text`` with ``math_re`` deciding which ``$...$`` spans are math.

    ``en_dash=False`` keeps ``--`` as written instead of the title rule's en dash.
    """
    if not text:
        return ""
    t = _strip_styles(text, markdown=False)
    if en_dash:
        t = t.replace("--", "\u2013")

    def plain_math(m: re.Match) -> str:
        inner = m.group(1)
        # Known symbols first: once braces and sub/superscript markers go, a
        # command runs into the letters after it (\phi_i -> \phii -> "phii").
        inner = re.sub(r"\\([A-Za-z]+)", lambda s: _SYMBOLS.get(s.group(1), s.group(0)), inner)
        inner = re.sub(r"\\(?:mathbb|mathcal|mathrm|mathbf|mathit|text|operatorname)\s*\{?([A-Za-z0-9]+)\}?", r"\1", inner)
        inner = re.sub(r"\\sqrt\{([^{}]*)\}", "\u221a\\1", inner)
        inner = re.sub(r"_\{([^{}]*)\}|_([\w+\-])", lambda s: (s.group(1) if s.group(1) is not None else s.group(2)).translate(_SUB), inner)
        inner = re.sub(r"\^\{([^{}]*)\}|\^([\w*+\-])", lambda s: (s.group(1) if s.group(1) is not None else s.group(2)).translate(_SUP), inner)
        # \ell_\infty -> ℓ∞: before a symbol or command the marker is dropped
        # (the symbol carries the meaning).
        inner = re.sub(r"[_^](?=\\|[^\w\s\x00-\x7f])", "", inner)
        inner = re.sub(r"\\([A-Za-z]+)", lambda s: _SYMBOLS.get(s.group(1), s.group(1)), inner)
        inner = inner.replace("{", "").replace("}", "")
        # Collapse spaces only around operators/relations, keep word spacing.
        inner = re.sub(r"\s*([→←×·∼≈≠≤≥±∈⊂∪∩∘/=+\-])\s*", r"\1", inner)
        return inner

    t = math_re.sub(plain_math, t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# 7. Plain-text video labels
# ---------------------------------------------------------------------------
# A word carries TeX when it has a command, a braced or command sub/superscript,
# or a bare one-character one that Unicode can render (x_1, n^2, S^*, \pi^+).
# Bare letter subscripts (JRC_m, G_goal, file_name.py) and longer bare scripts
# (2^10, model_2_layers, conv2d_3x3) are left as written, and so is a word
# that also holds a longer letter-led subscript: an identifier (conv_block_1).
_LABEL_TEX_RE = re.compile(r"\\[A-Za-z]|[_^][{\\]")
_LABEL_SCRIPT_RE = re.compile(r"[A-Za-z0-9)}\]][_^][\d*+\-](?!\w)")
_LABEL_IDENT_RE = re.compile(r"_[A-Za-z]\w")
_FONT_SWITCH_RE = re.compile(
    r"\\(?:rm|bf|it|sf|tt|cal|mathrm|mathbf|mathit|mathsf|mathcal|mathbb)\b(?!\{)\s*"
)
# A money ``\$`` (escape_currency) neither opens nor closes a label's span.
_LABEL_MATH_RE = re.compile(r"(?<!\\)\$([^$]+)(?<!\\)\$")


def _wrap_tex_words(text: str) -> str:
    """Wrap each TeX-bearing word in ``$...$``. Words split on whitespace
    outside braces, so ``{\\rm Bad Net}`` is one word."""
    out: list[str] = []
    word: list[str] = []
    depth = 0

    def flush() -> None:
        w = "".join(word)
        word.clear()
        if _LABEL_TEX_RE.search(w) or (_LABEL_SCRIPT_RE.search(w) and not _LABEL_IDENT_RE.search(w)):
            w = _FONT_SWITCH_RE.sub("", w)
            w = f"${w}$" if w else ""
        out.append(w)

    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch.isspace() and depth == 0:
            flush()
            out.append(ch)
        else:
            word.append(ch)
    flush()
    return "".join(out)


def label_to_text(label: str | None) -> str:
    """Plain-text video label (``Visualization.concept``), like a title.

    Concepts are LLM-written and often carry bare TeX with no ``$``
    delimiters (``S_{(j)}^*``, ``\\Phi(\\bx)=g_{\\theta}(...)``), which
    ``tex_to_text`` alone leaves untouched, plus JSON-escape residue
    (``\\u2194``, ``\\\\mathcal``, ``Levin\\'s``). The residue is undone,
    each ``$`` is decided money or math as in section text
    (``escape_currency``; money stays as written), TeX-bearing words are
    wrapped in ``$...$`` (``$...$`` spans already there are kept; text
    holding an unpaired ``$`` is not wrapped, since a new pair would close
    against it) and the result is rendered like a title, except that
    ``--`` stays as written: ``-->``, ``<--`` and ``---`` are arrows and
    rules, not en dashes (in a TeX span ``--`` is two minus signs anyway).
    """
    if not label:
        return ""
    t = _UNICODE_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)), label)
    t = re.sub(r"\\\\(?=[A-Za-z])", r"\\", t)
    t = re.sub(r"\\(['{}])", r"\1", t)
    parts = _LABEL_MATH_RE.split(escape_currency(t))
    wrapped = (f"${p}$" if i % 2 else p if "$" in p else _wrap_tex_words(p) for i, p in enumerate(parts))
    return _plain_text("".join(wrapped), _LABEL_MATH_RE, en_dash=False).replace("\\$", "$")

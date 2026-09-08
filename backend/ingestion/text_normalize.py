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
- currency "$391M" parsed as inline-math delimiters
- bare TeX commands in prose rendered as literal backslashes   207 papers
- \\[ \\] / \\( \\) delimiters remark-math does not understand
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
    display math survive.
    """
    t = _UNICODE_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    double_encoded = ("\n" not in text and "\\n" in text) or _UNICODE_ESC_RE.search(text) is not None
    if double_encoded:
        t = re.sub(r"\\\\(?=[A-Za-z])", r"\\", t)
        t = re.sub(r"\\n(?=[\s$])", "\n", t)
    return t


# ---------------------------------------------------------------------------
# 3. Display-math fences (line walk, never a regex across fences)
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"\\tag\{[^}]*\}")


def normalize_math_fences(text: str) -> str:
    """Make display math well-formed for remark-math.

    A ``$$`` opened on its own line must close on its own line: a content
    line that closes with ``$$`` and continues with prose is split, a
    trailing ``$$`` moves to its own line, a ``\\$`` closer becomes ``$$``,
    ``\\tag{}`` (unsupported by KaTeX) is dropped, and an odd number of
    fences is closed at the end instead of swallowing the section.
    """
    out: list[str] = []
    open_block = False
    for line in text.split("\n"):
        s = line.strip()
        if not open_block:
            if s == "$$":
                open_block = True
            out.append(line)
            continue
        if s in ("$$", "\\$"):
            out.append("$$")
            open_block = False
            continue
        m = re.match(r"^(.*?)\$\$[ \t]*(\S.*)$", line)
        if m and "$$" not in m.group(1):
            # "... = f(x).$$ Intuition: ..." -> equation, closer, blank, prose
            out.extend([m.group(1).rstrip(), "$$", "", m.group(2)])
            open_block = False
            continue
        if s.endswith("$$") and s.count("$$") == 1:
            out.extend([line[: line.rfind("$$")].rstrip(), "$$"])
            open_block = False
            continue
        out.append(line)
    t = "\n".join(out)
    t = _TAG_RE.sub("", t)
    if t.count("$$") % 2 == 1:
        t = t.rstrip() + "\n$$"
    return t


# ---------------------------------------------------------------------------
# 4. Currency: decided per `$`, before any span detection
# ---------------------------------------------------------------------------
_MATHISH_RE = re.compile(r"[\\^_=<>+*/]")


def _is_currency(line: str, i: int) -> bool:
    """``line[i]`` is a ``$`` followed by a digit. Money, or an inline-math opener?

    Money when: no closing ``$`` on the line; the closing ``$`` is itself
    followed by a digit (``$5 and $10``, ``$5 < $10``); or the span between
    reads as prose (spaces / ``;``) rather than a formula. A short numeric
    span with a real closer (``$5$``) and anything containing TeX or
    operators (``$2^n$``, ``$10\\%$``) is math.
    """
    if i > 0 and line[i - 1] not in " \t([~-":
        return False  # closing a span, or glued to a word
    j = i + 1
    while True:
        j = line.find("$", j)
        if j == -1:
            return True
        if line[j - 1] != "\\":
            break
        j += 1
    after = line[j + 1] if j + 1 < len(line) else ""
    if after.isdigit():
        return True
    cand = line[i + 1 : j]
    if re.fullmatch(r"[\d.,]+", cand):
        return False
    return not _MATHISH_RE.search(cand)


def escape_currency(text: str) -> str:
    """``$391M; Harris $191M`` is money, not a formula — escape the ``$``."""
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
            if chars[i] == "$" and i + 1 < len(chars) and chars[i + 1].isdigit() and (i == 0 or chars[i - 1] != "\\"):
                if _is_currency("".join(chars), i):
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
    JSON-residue undo, which only make sense for organizer output.
    """
    if not text:
        return ""
    t = clean_artifacts(text)
    if from_organizer:
        t = strip_prompt_scaffold(t)
        t = unescape_json_artifacts(t)
    t = normalize_math_fences(t)
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


def tex_to_text(title: str | None) -> str:
    """Plain-text rendering of a TeX-flavoured title for cards, hero, <title>.

    ``H$_2$O`` -> ``H\u2082O``; ``Rings $\\mathbb Z/n\\mathbb Z$`` -> ``Rings Z/nZ``;
    ``$\\alpha$-decay`` -> ``α-decay``; unknown commands keep their name.
    """
    if not title:
        return ""
    t = _strip_styles(title, markdown=False)
    t = t.replace("--", "\u2013")

    def plain_math(m: re.Match) -> str:
        inner = m.group(1)
        inner = re.sub(r"\\(?:mathbb|mathcal|mathrm|mathbf|mathit|text|operatorname)\s*\{?([A-Za-z0-9]+)\}?", r"\1", inner)
        inner = re.sub(r"\\sqrt\{([^{}]*)\}", "\u221a\\1", inner)
        inner = re.sub(r"_\{([^{}]*)\}|_(\w)", lambda s: (s.group(1) or s.group(2)).translate(_SUB), inner)
        inner = re.sub(r"\^\{([^{}]*)\}|\^(\w)", lambda s: (s.group(1) or s.group(2)).translate(_SUP), inner)
        inner = re.sub(r"[_^](?=\\)", "", inner)  # \ell_\infty -> ℓ∞ (symbol carries the meaning)
        inner = re.sub(r"\\([A-Za-z]+)", lambda s: _SYMBOLS.get(s.group(1), s.group(1)), inner)
        inner = inner.replace("{", "").replace("}", "")
        # Collapse spaces only around operators/relations, keep word spacing.
        inner = re.sub(r"\s*([→←×·∼≈≠≤≥±∈⊂∪∩∘/=+\-])\s*", r"\1", inner)
        return inner

    t = re.sub(r"\$([^$]+)\$", plain_math, t)
    return re.sub(r"\s+", " ", t).strip()

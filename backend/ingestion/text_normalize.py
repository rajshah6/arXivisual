"""Display-text normalization for section content, summaries and abstracts.

Applied at ingest (section_formatter) AND at read time (api.routes), so the
~940 already-stored papers are cleaned without a migration. Every rule maps
to an artifact class measured on the live corpus (Sept 2026 audit):

- prompt scaffold echoed into section 1                      21 papers
- display math whose closing $$ is followed by prose          54 papers (red KaTeX)
- JSON escape artifacts (\\uXXXX, \\\\command, literal \\n)       23 papers
- currency "$391M" parsed as inline-math delimiters
- bare TeX commands in prose rendered as literal backslashes  207 papers (22%)
"""

from __future__ import annotations

import re

_SCAFFOLD_LEAD_RE = re.compile(
    r'^\s*(?:Paper:\s*".*?"\s*\n+)?'
    r"(?:(?:Summarized text to organize into sections:|"
    r"The text to organize is between the <summary> tags\.[^\n]*)\s*\n+)?"
    r"(?:<summary>\s*)?",
    re.IGNORECASE,
)
_SCAFFOLD_TAIL_RE = re.compile(r"\s*</summary>\s*$", re.IGNORECASE)
_MATH_SPAN_RE = re.compile(r"\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]")
_BARE_TEX_RE = re.compile(
    r"\\[A-Za-z]+(?:\{[^{}]*\}|[_^](?:\{[^{}]*\}|\\[A-Za-z]+|[A-Za-z0-9]))*"
)
_STYLE_RE = re.compile(r"\\(?:textbf|textit|emph|textsc|texttt|text)\{([^{}]*)\}")
_DISPLAY_OPEN_INLINE_CLOSE_RE = re.compile(r"(?m)^([ \t]*)\$\$[ \t]*\n([\s\S]*?)\$\$[ \t]*(?=\S)")
_ESCAPED_DOLLAR_CLOSER_RE = re.compile(r"(?m)^([ \t]*\$\$\n[\s\S]*?)\\\$[ \t]*$")
_CURRENCY_RE = re.compile(r"(?<![\\$])\$(?=\d)(?=[^$\n]*(?:;|\s\S+\s\S+\s|\$\d|$))", re.M)


def strip_prompt_scaffold(text: str) -> str:
    """Remove the organizer prompt's own header/delimiters if the model echoed
    them — anchored to the section edges only, so a '<summary>' element
    mentioned in body prose survives."""
    t = _SCAFFOLD_LEAD_RE.sub("", text or "", count=1)
    return _SCAFFOLD_TAIL_RE.sub("", t).strip()


def unescape_json_artifacts(text: str) -> str:
    """Undo JSON-escape residue the organizer stored verbatim."""
    t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    # A double backslash before a letter is never a TeX line break.
    t = re.sub(r"\\\\(?=[A-Za-z])", r"\\", t)
    # Literal two-character \n before whitespace/$ (never \nabla, \neq, \nu).
    return re.sub(r"\\n(?=[\s$])", "\n", t)


def normalize_math_fences(text: str) -> str:
    """Make display math well-formed for remark-math.

    A ``$$`` opened on its own line must close on its own line; ``\\$`` as a
    closer becomes ``$$``; ``\\tag{}`` is unsupported by KaTeX; an odd count of
    ``$$`` swallows the rest of the section.
    """
    t = _DISPLAY_OPEN_INLINE_CLOSE_RE.sub(
        lambda m: f"{m.group(1)}$$\n{m.group(2).rstrip()}\n$$\n\n", text
    )
    t = _ESCAPED_DOLLAR_CLOSER_RE.sub(lambda m: m.group(1) + "$$", t)
    t = re.sub(r"\\tag\{[^}]*\}", "", t)
    if t.count("$$") % 2 == 1:
        t = t.rstrip() + "\n$$"
    return t


def escape_currency(text: str) -> str:
    """``$391M; Harris $191M`` is money, not a formula."""
    return _CURRENCY_RE.sub(r"\\$", text)


def _wrap_prose_segment(segment: str) -> str:
    seg = _STYLE_RE.sub(
        lambda m: {"textbf": f"**{m.group(1)}**", "textit": f"*{m.group(1)}*", "emph": f"*{m.group(1)}*"}
        .get(m.group(0)[1:m.group(0).index("{")], m.group(1)),
        segment,
    )
    seg = seg.replace(r"\%", "%").replace(r"\&", "&")
    seg = re.sub(r"\\(?:cite|ref|label)\{[^}]*\}", "", seg)
    seg = re.sub(r"\\url\{([^}]*)\}", r"\1", seg)

    def wrap(m: re.Match) -> str:
        tok = m.group(0)
        if tok in (r"\$", "\\\\"):
            return tok
        return f"${tok}$"

    return _BARE_TEX_RE.sub(wrap, seg)


def wrap_bare_tex(text: str) -> str:
    """Wrap TeX tokens that sit outside any math span in ``$...$``.

    ``return a chosen fake parameter set \\overline{\\rho} instead of the true
    one \\rho`` rendered those commands as literal backslash text.
    """
    out: list[str] = []
    pos = 0
    for m in _MATH_SPAN_RE.finditer(text):
        out.append(_wrap_prose_segment(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_wrap_prose_segment(text[pos:]))
    return "".join(out)


def normalize_display_text(text: str | None) -> str:
    """The full pipeline, idempotent — safe to apply at ingest and at read."""
    if not text:
        return ""
    t = strip_prompt_scaffold(text)
    t = unescape_json_artifacts(t)
    t = normalize_math_fences(t)
    t = escape_currency(t)
    t = wrap_bare_tex(t)
    return t.strip()


_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_SUP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")


def tex_to_text(title: str | None) -> str:
    """Plain-text rendering of a TeX-flavoured title for cards, hero, <title>.

    ``H$_2$O`` -> ``H\u2082O``; ``Rings $\\mathbb Z/n\\mathbb Z$`` -> ``Rings Z/nZ``;
    ``--`` -> en dash; ``\\emph{x}`` -> ``x``; ``\\%`` -> ``%``.
    """
    if not title:
        return ""
    t = _STYLE_RE.sub(lambda m: m.group(1), title)
    t = t.replace("--", "\u2013").replace(r"\%", "%").replace(r"\&", "&")

    def plain_math(m: re.Match) -> str:
        inner = m.group(1)
        inner = re.sub(r"_\{([^{}]*)\}|_(\w)", lambda s: (s.group(1) or s.group(2)).translate(_SUB), inner)
        inner = re.sub(r"\^\{([^{}]*)\}|\^(\w)", lambda s: (s.group(1) or s.group(2)).translate(_SUP), inner)
        inner = inner.replace(r"\to", "\u2192").replace(r"\times", "\u00d7").replace(r"\infty", "\u221e")
        inner = re.sub(r"\\(?:mathbb|mathcal|mathrm|mathbf|text)\s*\{?([A-Za-z0-9]+)\}?", r"\1", inner)
        inner = re.sub(r"\\[A-Za-z]+", "", inner)
        return inner.replace("{", "").replace("}", "").replace(" ", "")

    t = re.sub(r"\$([^$]+)\$", plain_math, t)
    return re.sub(r"\s+", " ", t).strip()

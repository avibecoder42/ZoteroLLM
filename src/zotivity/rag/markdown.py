"""Minimaler Markdown→HTML-Wandler für Zotero-Notizen (Überschriften, Absätze, Listen, Hervorhebung, Links)."""

from __future__ import annotations

import html
import re

# -- Formeln in LaTeX-Schreibweise --------------------------------------------------------------------------------------
# Sprachmodelle schreiben Kennwerte gern als $\beta = .35$. Im Fliesstext (Word, Notiz, Anzeige) wird daraus β = .35.
# Wie in Pandoc steht das öffnende $ vor, das schliessende nach einem Nicht-Leerzeichen, und danach folgt keine Ziffer –
# so bleiben Geldbeträge („$15,000 und $20,000“) stehen. Zusätzlich muss der Inhalt nach einer Formel aussehen.
MATH = re.compile(r"(?<![\\$\w])\$(?=[^\s$])((?:\\.|[^$\n\\]){1,120}?)(?<=\S)\$(?![\d$])")
_MATHY = re.compile(r"[\\^_=<>]|^[−+-]?[\d.,]+%?$|^[A-Za-z]$")
_TEX_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
    "Theta": "Θ", "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "ge": "≥", "geq": "≥", "le": "≤", "leq": "≤", "ne": "≠", "neq": "≠", "approx": "≈", "sim": "~", "pm": "±",
    "mp": "∓", "times": "×", "cdot": "·", "div": "÷", "to": "→", "rightarrow": "→", "leftarrow": "←", "infty": "∞",
    "ll": "≪", "gg": "≫", "lt": "<", "gt": ">", "ldots": "…", "dots": "…", "cdots": "…", "circ": "°", "degree": "°",
    "prime": "′", "quad": " ", "qquad": " ", "left": "", "right": "",
}
_SUP = dict(zip("0123456789+-−=()ni°", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿⁱ°"))
_SUB = dict(zip("0123456789+-−=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"))


def is_math(inner: str) -> bool:
    return bool(_MATHY.search(inner.strip()))


def _script(content: str, table: dict[str, str], mark: str) -> str:
    if content and all(ch in table for ch in content):
        return "".join(table[ch] for ch in content)
    return mark + content if len(content) == 1 else f"{mark}({content})"


def tex_math_to_text(tex: str) -> str:
    """Inhalt einer Formel als Text: „\\beta = .35“ → „β = .35“, „I^2 > 98\\%“ → „I² > 98%“, „r = -.14“ → „r = −.14“."""
    s = tex
    for _ in range(3):
        s = re.sub(r"\\(?:text|textrm|textit|textbf|mathrm|mathit|mathbf|mathsf|operatorname|mbox)\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\([A-Za-z]+)", lambda m: _TEX_SYMBOLS.get(m.group(1), m.group(1)), s)
    s = re.sub(r"(?<!\\)\^\{([^{}]*)\}|(?<!\\)\^(\S)", lambda m: _script(m.group(1) or m.group(2), _SUP, "^"), s)
    s = re.sub(r"(?<!\\)_\{([^{}]*)\}|(?<!\\)_(\S)", lambda m: _script(m.group(1) or m.group(2), _SUB, "_"), s)
    s = re.sub(r"\\[,;:! ]|~", " ", s)
    s = re.sub(r"\\([%&#$_{}])", r"\1", s)
    s = s.replace("{", "").replace("}", "").replace("---", "—").replace("--", "–")
    s = re.sub(r"(?<![\w.])-(?=[\d.])", "−", s)  # Minuszeichen vor Zahlen
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def latex_to_text(text: str) -> str:
    """Formeln in LaTeX-Schreibweise im Fliesstext ($\\beta = .35$) als Text mit Unicode-Zeichen (β = .35)."""
    return MATH.sub(lambda m: tex_math_to_text(m.group(1)) if is_math(m.group(1)) else m.group(0), text)


_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
_SAFE_SCHEMES = ("http://", "https://", "zotero://")


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)

    def link(m: re.Match) -> str:
        url = html.unescape(m.group(2))
        if not url.startswith(_SAFE_SCHEMES):
            return m.group(1)
        return f'<a href="{html.escape(url)}">{m.group(1)}</a>'

    text = _LINK.sub(link, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITAL.sub(r"<em>\1</em>", text)
    return text


def md_to_html(md: str) -> str:
    out: list[str] = []
    para: list[str] = []
    list_type: str | None = None

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para = []

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            close_list()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_para()
            close_list()
            level = min(len(m.group(1)), 6)
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush_para()
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if list_type != kind:
                close_list()
                out.append(f"<{kind}>")
                list_type = kind
            out.append(f"<li>{_inline(m.group(2))}</li>")
            continue
        if line.startswith(">"):
            flush_para()
            close_list()
            out.append(f"<blockquote><p>{_inline(line.lstrip('> '))}</p></blockquote>")
            continue
        close_list()
        para.append(line.strip())
    flush_para()
    close_list()
    return "\n".join(out)

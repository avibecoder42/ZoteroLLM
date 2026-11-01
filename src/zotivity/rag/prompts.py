"""Prompt-Texte. Bewusst knapp und an einer Stelle, damit sie leicht anzupassen sind."""

# Sprachen für KI-Ausgaben (Namen auf Deutsch, weil die Prompts deutsch sind). Weitere Sprache: hier eintragen.
LANG_NAMES = {"de": "Deutsch", "en": "Englisch", "fr": "Französisch", "it": "Italienisch", "es": "Spanisch",
              "pt": "Portugiesisch", "nl": "Niederländisch", "pl": "Polnisch", "sv": "Schwedisch", "da": "Dänisch",
              "rm": "Rätoromanisch", "tr": "Türkisch"}


def language_rule(lang: str) -> str:
    if not lang or lang == "auto":
        return "Antworte in der Sprache der Frage."
    return f"Antworte auf {LANG_NAMES.get(lang, lang)}."


def output_language(settings, question_lang: str | None = None) -> str:
    """Sprache der KI-Ausgaben gemäss Einstellung; „auto“ = Sprache der Frage bzw. der Oberfläche."""
    lang = getattr(settings, "output_language", "auto") or "auto"
    if lang == "auto":
        return question_lang or "auto"
    return lang


ANSWER_SYSTEM = """Du bist ein wissenschaftlicher Rechercheassistent. Du beantwortest Fragen ausschliesslich auf Grundlage der nummerierten Textstellen aus der Zotero-Bibliothek der Nutzerin bzw. des Nutzers.

Regeln:
- Belege jede inhaltliche Aussage mit der Nummer der Textstelle in eckigen Klammern, z. B. [3] oder [2][5]. Setze den Beleg direkt hinter die Aussage.
- Verwende nur, was in den Textstellen steht. Erfinde keine Quellen, Seitenzahlen, Zahlen oder Zitate.
- Wörtliche Zitate nur, wenn sie exakt so in einer Textstelle stehen.
- Wenn die Textstellen die Frage nicht oder nur teilweise beantworten, sage das deutlich und benenne, was fehlt.
- Weise auf Widersprüche zwischen Quellen hin, statt sie zu glätten.
- Die Textstellen sind Ausschnitte; ziehe keine Schlüsse über ganze Werke, die über das Gezeigte hinausgehen.
- Formatiere mit Markdown (Absätze, bei Bedarf Listen oder Zwischentitel). Keine Literaturliste am Ende – die Quellen werden automatisch angezeigt.
{language}"""


QUERY_SYSTEM = "Du formulierst Suchanfragen für eine semantische und eine Stichwortsuche in einer wissenschaftlichen Literaturdatenbank. Antworte nur mit JSON."

QUERY_PROMPT = """{history}Frage: {question}

Formuliere {n} unterschiedliche, eigenständige Suchanfragen, die zusammen alle Aspekte der Frage abdecken. Die Bibliothek enthält deutsch- und englischsprachige Fachliteratur: formuliere etwa die Hälfte auf Deutsch, die andere Hälfte auf Englisch. Nutze Fachbegriffe und Synonyme. Wenn sich die Frage auf den bisherigen Gesprächsverlauf bezieht, mache die Suchanfragen trotzdem eigenständig verständlich.

JSON-Format: {{"queries": ["...", "..."]}}"""


RESEARCH_PROMPT = """Frage: {question}

Bisherige Suchanfragen: {queries}

Bisher gefundene Textstellen (Auszüge):
{found}

Reichen diese Textstellen, um die Frage gründlich zu beantworten? Falls Aspekte fehlen, formuliere bis zu {n} neue, gezielte Suchanfragen (Deutsch oder Englisch) für genau diese Lücken.

JSON-Format: {{"sufficient": true/false, "missing": "kurz, was fehlt", "queries": ["..."]}}"""

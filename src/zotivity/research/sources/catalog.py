"""Katalog der Literaturdatenbanken: Disziplin, Zugang und was maschinell erlaubt ist (Stand 29.10.2026,
siehe ``litsearch/Datenbanken_API.md``).

``access``:
- ``live``    offen, die App sucht direkt (ggf. mit kostenlosem Schlüssel)
- ``license`` nur mit Lizenz der Hochschule oder auf Antrag – in der App noch nicht angebunden
- ``export``  keine offene API: Suche in der Datenbank, Export als RIS, Import in der App
- ``never``   keine API, und die Bedingungen verbieten automatische Abfragen
"""

from __future__ import annotations

DISCIPLINES = {
    "multi": "Fächerübergreifend",
    "health": "Medizin, Gesundheit, Pflege",
    "psych": "Psychologie",
    "social": "Sozialwissenschaften, Soziale Arbeit",
    "edu": "Erziehungswissenschaft",
    "econ": "Wirtschaft",
    "tech": "Informatik, Technik, Naturwissenschaften",
    "hum": "Philosophie, Geisteswissenschaften",
    "art": "Kunst, Design, künstlerische Forschung",
    "books": "Bücher (Bibliothekskataloge)",
}
ACCESS = {
    "live": "direkt in der App",
    "license": "Lizenz oder Antrag",
    "export": "RIS-Import",
    "never": "nicht erlaubt",
}


def _s(id, label, disciplines, access, note, terms="", boolean="ja", key=None, live=None, recommended=False):
    return {"id": id, "label": label, "disciplines": disciplines, "access": access, "note": note, "terms": terms,
            "boolean": boolean, "key": key, "in_app": access == "live" if live is None else live,
            "recommended": recommended}


CATALOG = [
    _s("openalex", "OpenAlex", ["multi", "social", "edu", "psych", "econ", "hum", "tech", "health", "art"], "live",
       "Sehr breit, viel graue Literatur. Seit Februar 2026 mit (kostenlosem) API-Schlüssel, 1 $ Nutzung pro Tag.",
       "https://help.openalex.org/access/pricing/", key="openalex", recommended=True),
    _s("pubmed", "PubMed / MEDLINE", ["health", "psych"], "live",
       "Mit MeSH; 3 Anfragen/s, mit NCBI-Schlüssel 10/s.", "https://www.ncbi.nlm.nih.gov/books/NBK25497/",
       key="ncbi", recommended=True),
    _s("europepmc", "Europe PMC", ["health", "psych"], "live",
       "PubMed plus Preprints und Volltexte aus PMC; ohne Schlüssel.",
       "https://europepmc.org/RestfulWebService"),
    _s("semanticscholar", "Semantic Scholar", ["multi", "tech", "health"], "live",
       "Bulk-Suche in Titel und Abstract. Ohne Schlüssel oft überlastet; Lizenz von AI2, nicht kommerziell.",
       "https://api.semanticscholar.org/license", key="semanticscholar"),
    _s("eric", "ERIC", ["edu"], "live", "Bildungsforschung (US), mit Thesaurus; ohne Schlüssel.",
       "https://eric.ed.gov/?api"),
    _s("econbiz", "EconBiz", ["econ"], "live",
       "Wirtschaft (ZBW). Liefert keine Abstracts – nach der Suche nachladen. Keine Massenkopien.",
       "https://api.econbiz.de/"),
    _s("arxiv", "arXiv", ["tech"], "live", "Preprints; 1 Anfrage alle 3 Sekunden; keine Platzhalter.",
       "https://info.arxiv.org/help/api/tou.html"),
    _s("osf", "OSF-Preprints (PsyArXiv, SocArXiv, EdArXiv)", ["psych", "social", "edu"], "live",
       "Einfache Suche: alle Stichwörter müssen vorkommen, kein ODER.", "https://help.osf.io/", boolean="einfach"),
    _s("swisscovery", "swisscovery (Schweizer Hochschulbibliotheken)", ["books", "art"], "live",
       "Bücher und Sammelbände; SRU, höchstens 10'000 Treffer je Suche, keine Massenexporte.",
       "https://slsp.ch/en", boolean="ja (CQL)"),
    _s("core", "CORE", ["multi"], "live",
       "Open-Access-Volltexte. Phrasen werden nicht zuverlässig erkannt – noch nicht als Suchquelle eingebaut.",
       "https://core.ac.uk/services/api", boolean="eingeschränkt", live=False),
    _s("base", "BASE (Bielefeld)", ["multi"], "license", "Nur nicht kommerziell, Zugang auf Antrag (IP-gebunden).",
       "https://www.base-search.net/about/en/contact.php"),
    _s("openaire", "OpenAIRE Graph", ["multi"], "live", "Offen (60 Anfragen/h, mit Token 7200/h); noch nicht eingebaut.",
       "https://graph.openaire.eu/docs/apis/terms", boolean="einfach", live=False),
    _s("wos", "Web of Science (Starter API)", ["multi"], "license",
       "Gratis nur persönlich (50/Tag); mit Lizenz der Hochschule 5000/Tag. RIS-Import geht immer (in der Datenbank exportieren).",
       "https://developer.clarivate.com/apis/wos-starter"),
    _s("scopus", "Scopus", ["multi"], "license",
       "Nur mit Lizenz der Hochschule; TDM-Rechte für Abonnent*innen im Schengen-Raum. Sonst RIS-Import.",
       "https://dev.elsevier.com/academic_research_scopus.html"),
    _s("lens", "Lens.org", ["multi"], "license", "Token auf Antrag.", "https://docs.api.lens.org/getting-started.html"),
    _s("ieee", "IEEE Xplore", ["tech"], "license", "Schlüssel nach Prüfung durch IEEE.",
       "https://developer.ieee.org/API_Terms_of_Use2"),
    _s("springer", "Springer Nature (Meta API)", ["multi", "tech"], "live",
       "Kostenloser Schlüssel, 500 Anfragen/Tag; noch nicht eingebaut.",
       "https://dev.springernature.com/docs/rate-limit-details/rate-limits", live=False),
    _s("psycinfo", "APA PsycInfo", ["psych", "social", "edu"], "export",
       "Über Ovid oder EBSCO mit Lizenz; RIS-Import (Suchstring für Ovid übersetzt die App).", recommended=True),
    _s("cinahl", "CINAHL", ["health"], "export", "Pflege; EBSCO, nur mit Lizenz; RIS-Import."),
    _s("socindex", "SocINDEX", ["social"], "export", "EBSCO, nur mit Lizenz; RIS-Import."),
    _s("assia", "ASSIA", ["social"], "export", "ProQuest, nur mit Lizenz; RIS-Import."),
    _s("socabs", "Sociological Abstracts / Social Services Abstracts", ["social"], "export",
       "ProQuest, nur mit Lizenz; RIS-Import."),
    _s("fis", "FIS Bildung (Fachportal Pädagogik)", ["edu"], "export",
       "Deutschsprachige Bildungsforschung; keine API gefunden, RIS-Import."),
    _s("philpapers", "PhilPapers", ["hum"], "license", "Schlüssel auf Antrag; strenge Bedingungen zur Weitergabe.",
       "https://philpapers.org/help/api/"),
    _s("philindex", "Philosopher's Index, MLA", ["hum"], "export", "EBSCO, nur mit Lizenz; RIS-Import."),
    # Kunst, Design, künstlerische Forschung (Stand 30.10.2026; Schnittstellen geprüft, wo „keine API“ steht: keine gefunden)
    _s("iba", "International Bibliography of Art (IBA)", ["art"], "export",
       "ProQuest, nur mit Lizenz; Nachfolgerin der BHA, westliche Kunst von der Spätantike bis heute; RIS-Import.",
       "https://proquest.libguides.com/iba/content", recommended=True),
    _s("artfulltext", "Art Full Text / Art & Architecture Source", ["art"], "export",
       "EBSCO, nur mit Lizenz; Kunst, Design, Architektur; RIS-Import (EDS-API nur, wenn die Hochschule sie freischaltet)."),
    _s("avery", "Avery Index to Architectural Periodicals", ["art"], "export", "ProQuest, nur mit Lizenz; Architektur; RIS-Import."),
    _s("daai", "DAAI (Design and Applied Arts Index)", ["art"], "export",
       "ProQuest, nur mit Lizenz; Design und angewandte Kunst; RIS-Import."),
    _s("openbibart", "OpenBibArt (BHA und RAA 1910–2007)", ["art"], "export",
       "Frei online (INHA, Getty, CNRS), rund 1,2 Mio. Einträge bis 2007; keine API gefunden – Suche und Export von Hand.",
       "https://www.openbibart.fr/"),
    _s("kubikat", "kubikat (Kunsthistorische Institute Florenz, München, Rom, Paris)", ["art", "books"], "export",
       "Grösster Katalog der Kunstgeschichte, auch Aufsätze; keine Schnittstelle gefunden – Suche und Export von Hand.",
       "https://www.kubikat.org/"),
    _s("artdiscovery", "ART-Discovery (arthistoricum.net)", ["art"], "export",
       "Durchsucht kubikat, weitere Kunstbibliotheken und BASE; keine API erwähnt – Suche und Export von Hand.",
       "https://www.arthistoricum.net/en/search/data-sources"),
    _s("researchcatalogue", "Research Catalogue (Society for Artistic Research)", ["art"], "export",
       "Zentrale Plattform der künstlerischen Forschung (über 5'700 Expositionen, u. a. JAR); keine öffentliche API "
       "dokumentiert – Suche von Hand, Export bei der SAR erfragen.", "https://societyforartisticresearch.org/research-catalogue",
       recommended=True),
    _s("doaj", "DOAJ (Directory of Open Access Journals)", ["multi", "art", "hum"], "live",
       "Open-Access-Zeitschriften aller Fächer, auch Kunst und künstlerische Forschung; Metadaten CC0, offene API; noch "
       "nicht eingebaut.", "https://doaj.org/terms", boolean="ja", live=False),
    _s("artdok", "ART-Dok (UB Heidelberg)", ["art"], "live",
       "Rund 9'600 Open-Access-Volltexte der Kunstgeschichte; nur Gesamtabzug über OAI-PMH, keine Such-API; noch nicht "
       "eingebaut.", "https://archiv.ub.uni-heidelberg.de/artdok/", boolean="nur Gesamtabzug", live=False),
    _s("europeana", "Europeana", ["art", "hum"], "live",
       "Kulturgut-Objekte (Werke, Archivalien), keine Fachliteratur; Gratis-Schlüssel je Software-Projekt, Metadaten CC0; "
       "noch nicht eingebaut.", "https://www.europeana.eu/rights/terms-of-use", key="europeana", live=False),
    _s("jstor", "JSTOR", ["hum", "social", "art"], "never", "Keine Such-API (Constellate seit 1.7.2025 eingestellt)."),
    _s("cochrane", "Cochrane Library", ["health"], "never", "Keine öffentliche Such-API; Reviews sind auch in PubMed."),
    _s("scholar", "Google Scholar", ["multi"], "never", "Keine API; die Nutzungsbedingungen verbieten automatische Abfragen."),
]
BY_ID = {s["id"]: s for s in CATALOG}


def suggest(disciplines: list[str]) -> list[str]:
    """Vorschlag für die gewählten Disziplinen: alle offenen, eingebauten Quellen dieser Disziplinen, dazu OpenAlex
    und die Fachdatenbanken, die nur per Export gehen (damit sie im Protokoll nicht fehlen)."""
    chosen = set(disciplines or [])
    out = []
    for s in CATALOG:
        if s["access"] == "never":
            continue
        fits = bool(chosen & set(s["disciplines"]))
        if s["id"] == "openalex" or (fits and (s["in_app"] or s["access"] == "export")):
            out.append(s["id"])
    return out

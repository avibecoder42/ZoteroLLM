"""Export von Antworten, Textstellen und Forschungsstand: Text, Markdown, LaTeX und Word mit Zotero-Feldern."""

import io
import json
import re
import zipfile
from xml.dom import minidom

from test_server import H, client  # noqa: F401 - Fixture

SOURCES = [
    {"n": 1, "lib": "users/0", "item_key": "ITEMA001", "page_label": "2", "citation": "Müller 2024",
     "title": "Chatbots als Gesprächspartner", "text": "Jugendliche nutzen Chatbots bei persönlichen Problemen."},
    {"n": 2, "lib": "users/0", "item_key": "ITEMB001", "page_label": "", "citation": "Devlieghere 2018",
     "title": "Information systems in social work", "text": "Information systems shape social work."},
]


def _message(engine) -> int:
    chat = engine.store.create_chat("Wie nutzen Jugendliche Chatbots?")
    engine.store.add_chat_message(chat, "user", "Wie nutzen Jugendliche Chatbots?")
    return engine.store.add_chat_message(
        chat, "assistant", "## Befund\n\nJugendliche suchen Rat bei **Chatbots** [1]. Auch die Soziale Arbeit "
        "ist betroffen [1][2], vgl. [1, 2].", sources=SOURCES)


def _get(client, kind, mid, fmt):
    r = client.get(f"/api/export?kind={kind}&id={mid}&format={fmt}")
    assert r.status_code == 200, r.text
    return r


def test_answer_as_text_and_markdown(client):
    mid = _message(client.app.state.engine)
    r = _get(client, "answer", mid, "text").json()
    assert "(Müller, 2024, S. 2)" in r["text"] and "(Müller, 2024, S. 2; Devlieghere, 2018)" in r["text"]
    assert "Literatur" in r["text"] and "Devlieghere, A. (2018)" in r["text"]  # Verzeichnis aus Zotero
    assert r["from_zotero"] and "<b>Chatbots</b>" in r["html"] and "<h2>Befund</h2>" in r["html"]
    md = _get(client, "answer", mid, "md").text
    assert md.startswith("# Wie nutzen Jugendliche Chatbots?") and "## Literatur" in md
    assert 'attachment; filename*=' in _get(client, "answer", mid, "md").headers["content-disposition"]


def test_answer_as_word_with_zotero_fields(client):
    mid = _message(client.app.state.engine)
    data = _get(client, "answer", mid, "docx").content
    z = zipfile.ZipFile(io.BytesIO(data))
    doc = z.read("word/document.xml").decode()
    minidom.parseString(doc)  # gültiges XML
    assert doc.count('w:fldCharType="begin"') == 4  # drei Belege + Literaturverzeichnis
    code = "".join(re.findall(r"<w:instrText[^>]*>(.*?)</w:instrText>", doc))
    code = code.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    first = re.search(r"ADDIN ZOTERO_ITEM CSL_CITATION (\{.*?\})\s+ADDIN", code).group(1)
    cit = json.loads(first)
    item = cit["citationItems"][0]
    assert item["uris"] == ["http://zotero.org/users/local/abcd1234/items/ITEMA001"]  # vom Zotivity-Plugin
    assert item["locator"] == "2" and item["label"] == "page"
    assert item["itemData"]["title"] == "Chatbots als Gesprächspartner"
    assert "ADDIN ZOTERO_BIBL" in code and "CSL_BIBLIOGRAPHY" in code
    prefs = z.read("docProps/custom.xml").decode()
    assert "ZOTERO_PREF_1" in prefs and "http://www.zotero.org/styles/apa" in prefs.replace("&quot;", '"')
    for name in z.namelist():
        if name.endswith(".xml") or name.endswith(".rels"):
            minidom.parseString(z.read(name))


def test_answer_as_latex(client):
    mid = _message(client.app.state.engine)
    tex = _get(client, "answer", mid, "tex").text
    assert r"\parencite[S.~2]{müller_chatbots_2024}" in tex
    assert r"\parencites[S.~2]{müller_chatbots_2024}{devlieghere_information_2018}" in tex
    assert r"\textbf{Chatbots}" in tex and r"\section*{Befund}" in tex
    assert "@article{müller_chatbots_2024" in tex and r"\printbibliography" in tex


def test_export_without_zotero_uses_stored_metadata(client, monkeypatch):
    engine = client.app.state.engine
    mid = _message(engine)
    monkeypatch.setattr(engine.zotero(), "is_available", lambda: False)
    r = _get(client, "answer", mid, "text").json()
    assert not r["from_zotero"] and "(Müller, 2024, S. 2)" in r["text"]
    tex = _get(client, "answer", mid, "tex").text
    assert "@article{mueller_chatbots_2024," in tex and r"\parencite[S.~2]{mueller_chatbots_2024}" in tex
    assert "author = {Müller, A.}" in tex and "journal" not in tex  # ohne Zeitschrift kein leeres Feld
    doc = zipfile.ZipFile(io.BytesIO(_get(client, "answer", mid, "docx").content)).read("word/document.xml").decode()
    assert "http://zotero.org/users/local/" in doc


def test_sources_and_review_export(client):
    engine = client.app.state.engine
    mid = _message(engine)
    txt = _get(client, "sources", mid, "text").json()["text"]
    assert "Jugendliche nutzen Chatbots" in txt and "(Müller, 2024, S. 2)" in txt
    state = {"step": "written", "language": "en", "queries": ["chatbots youth"],
             "query_stats": [{"query": "chatbots youth", "docs": 2, "unique": 1}],
             "outline": {"title": "Chatbots and youth"},
             "sections": [{"text": "## Use\n\nYoung people use chatbots [@ITEMA001, S. 2; @ITEMB001]."}]}
    rid = engine.store.create_review("Chatbots", "How do young people use chatbots?", state)
    engine.store.put_review_docs(rid, [{"lib": "users/0", "item_key": "ITEMA001", "included": True},
                                      {"lib": "users/0", "item_key": "ITEMB001", "included": True}])
    md = _get(client, "review", rid, "md").text
    assert md.startswith("# Chatbots and youth") and "## References" in md  # Sprache des Forschungsstands
    assert "(Müller, 2024, p. 2; Devlieghere, 2018)" in md
    assert "Appendix: Literature search method" in md and "| chatbots youth | 2 | 1 |" in md
    tex = _get(client, "review", rid, "tex").text
    assert r"\parencites[p.~2]{müller_chatbots_2024}{devlieghere_information_2018}" in tex
    assert "english" in tex


def test_export_errors(client):
    assert client.get("/api/export?kind=answer&id=9999&format=docx").status_code == 404
    mid = _message(client.app.state.engine)
    assert client.get(f"/api/export?kind=answer&id={mid}&format=pdf").status_code == 400
    assert client.get(f"/api/export?kind=x&id={mid}&format=md").status_code == 400


def test_formulas_become_text():
    from zotivity.rag.markdown import latex_to_text

    assert latex_to_text(r"($\beta = .35$ and $.39$; $\alpha \approx .89\text{--}.91$; $I^2 > 98\%$; $r = -.14$)") == \
        "(β = .35 and .39; α ≈ .89–.91; I² > 98%; r = −.14)"
    assert latex_to_text(r"cut-offs of $\ge 21$ ($\text{aOR} = 1.40$ for $>2\text{ h/day}$)") == \
        "cut-offs of ≥ 21 (aOR = 1.40 for >2 h/day)"
    # Geldbeträge bleiben
    for money in ("income below $15,000; 8.8% $20,000 or more", "between $100,000–$150,000", "costs ($10 USD) and $5"):
        assert latex_to_text(money) == money


def test_author_named_before_citation():
    from zotivity.rag.review import named_before

    shin = {"creators": [{"creatorType": "author", "lastName": "Shin"}, {"creatorType": "author", "lastName": "Kim"},
                         {"creatorType": "author", "lastName": "Lee"}]}
    assert named_before("whereas Shin et al. ", shin) and named_before("as Shin and Kim ", shin)
    assert named_before("Shin, Kim und Lee", shin) and named_before("(see Shin)", shin) is False
    assert not named_before("whereas the findings ", shin) and not named_before("Shinto ", shin)
    assert named_before("Die WHO ", {"creators": [{"creatorType": "author", "name": "WHO"}]})


def test_review_export_formulas_and_named_authors(client):
    """Formeln des Modells werden Text (in LaTeX bleiben sie Formeln); steht der Name vor dem Beleg, nennt der Beleg nur
    Jahr und Seite – in Word mit suppress-author, sonst stünde „Müller (Müller, 2024)“ da."""
    engine = client.app.state.engine
    state = {"step": "written", "language": "en", "outline": {"title": "Chatbots"},
             "sections": [{"text": "## Use\n\nMüller [@ITEMA001, S. 2] found an effect ($\\beta = .35$, $I^2 > 98\\%$), "
                                   "costs of $15,000 and $20,000 aside. Others agree [@ITEMB001]."}]}
    rid = engine.store.create_review("Chatbots", "How do young people use chatbots?", state)
    engine.store.put_review_docs(rid, [{"lib": "users/0", "item_key": "ITEMA001", "included": True},
                                      {"lib": "users/0", "item_key": "ITEMB001", "included": True}])
    md = _get(client, "review", rid, "md").text
    assert "Müller (2024, p. 2) found an effect (β = .35, I² > 98%)" in md and "$15,000 and $20,000" in md
    assert "Others agree (Devlieghere, 2018)" in md
    tex = _get(client, "review", rid, "tex").text
    assert r"Müller \parencite*[p.~2]{müller_chatbots_2024}" in tex and r"($\beta = .35$, $I^2 > 98\%$)" in tex
    assert r"\$15,000" in tex and r"\usepackage{amsmath}" in tex
    doc = zipfile.ZipFile(io.BytesIO(_get(client, "review", rid, "docx").content)).read("word/document.xml").decode()
    code = "".join(re.findall(r"<w:instrText[^>]*>(.*?)</w:instrText>", doc))
    code = code.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    cits = [json.loads(c) for c in re.findall(r"ADDIN ZOTERO_ITEM CSL_CITATION (\{.*?\})\s+(?=ADDIN)", code)]
    assert cits[0]["citationItems"][0]["suppress-author"] is True and cits[0]["properties"]["formattedCitation"] == "(2024, p. 2)"
    assert "suppress-author" not in cits[1]["citationItems"][0]
    assert "β = .35" in doc and "\\beta" not in doc
    # Anzeige im Programm (und Notiz in Zotero) aus derselben Aufbereitung
    shown = client.get(f"/api/reviews/{rid}/text").json()["markdown"]
    assert "Müller ([2024, p. 2](#cite-0)) found an effect (β = .35, I² > 98%)" in shown

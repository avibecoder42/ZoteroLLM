"""Zitierstile aus Zotero: Datenordner, Liste der installierten Stile, Seitenangabe je Stil und „o. S.“ im Export."""

import json

from test_indexing_search import build_library
from test_server import H, client  # noqa: F401 - Fixture

from zotivity.exporting import CiteItem, Citations
from zotivity.rag.review import NO_PAGE
from zotivity.zotero import styles as zstyles

HEAD = '<style xmlns="http://purl.org/net/xbiblio/csl" class="{cls}" version="1.0"><info><title>{title}</title>' \
       '<id>http://www.zotero.org/styles/{id}</id>{extra}<category citation-format="{fmt}"/></info>'
# Wie „Hochschule für Soziale Arbeit FHNW“: (Müller 2019: 114), Bezeichnung nur bei anderen Stellenangaben
COLON = HEAD.format(cls="in-text", title="Doppelpunkt-Stil", id="test-colon", extra="", fmt="author-date") + """
  <macro name="point-locators"><group><choose><if locator="page" match="none">
    <label variable="locator" form="short" suffix=" "/></if></choose><text variable="locator"/></group></macro>
  <citation><layout prefix="(" suffix=")" delimiter="; "><choose><if position="ibid-with-locator">
    <group delimiter=": "><text term="ibid"/><text macro="point-locators"/></group></if><else>
    <group delimiter=": "><group delimiter=" "><names variable="author"><name form="short"/></names>
    <date variable="issued"><date-part name="year"/></date></group><text macro="point-locators"/></group>
  </else></choose></layout></citation></style>"""
# Wie APA: (Müller, 2019, S. 114)
COMMA = HEAD.format(cls="in-text", title="Komma-Stil", id="test-comma", extra="", fmt="author-date") + """
  <citation><layout prefix="(" suffix=")" delimiter="; "><group delimiter=", ">
    <names variable="author"><name form="short"/></names><date variable="issued"><date-part name="year"/></date>
    <group><label variable="locator" form="short" suffix=" "/><text variable="locator"/></group>
  </group></layout></citation></style>"""
NOTE = HEAD.format(cls="note", title="Fussnoten-Stil", id="test-note", extra="<title-short>FN kurz</title-short>",
                   fmt="note") + \
    "<citation><layout><text variable=\"title\"/></layout></citation></style>"
DEPENDENT = HEAD.format(cls="in-text", title="Abhängig vom Doppelpunkt-Stil", id="test-dependent",
                        extra='<link href="http://www.zotero.org/styles/test-colon" rel="independent-parent"/>',
                        fmt="author-date") + "</style>"


def make_styles(folder):
    styles = folder / "styles"
    styles.mkdir(parents=True)
    for name, xml in (("colon", COLON), ("comma", COMMA), ("note", NOTE), ("dependent", DEPENDENT)):
        (styles / f"{name}.csl").write_text(xml, encoding="utf-8")
    return folder


def test_data_dir_from_zotero_prefs():
    prefs = ('user_pref("extensions.zotero.useDataDir", true);\n'
             'user_pref("extensions.zotero.dataDir", "C:\\\\Users\\\\x\\\\OneDrive - Beispiel\\\\Zotero");')
    assert str(zstyles.data_dir_from_prefs(prefs)).replace("/", "\\") == "C:\\Users\\x\\OneDrive - Beispiel\\Zotero"
    assert zstyles.data_dir_from_prefs(prefs.replace("true", "false")) is None


def test_installed_styles_and_locator_analysis(tmp_path):
    data = make_styles(tmp_path)
    styles = zstyles.installed_styles(data)
    assert [s.title for s in styles] == ["Abhängig vom Doppelpunkt-Stil", "Doppelpunkt-Stil", "Fussnoten-Stil",
                                         "Komma-Stil"]
    note = next(s for s in styles if s.format == "note")
    assert not note.supported and note.as_dict()["short"] == "FN kurz"  # Kurztitel für den Filter im CSL-Editor
    colon = zstyles.analyze_locator(zstyles.style_xml("test-colon", data))
    assert colon.found and colon.no_page_mode == "locator" and colon.delimiter == ": " and not colon.label
    assert zstyles.preview(colon, "de", NO_PAGE) == {"page": "(Gillingham 2019: 114)", "no_page": "(Gillingham 2019: o. S.)"}
    comma = zstyles.analyze_locator(zstyles.style_xml("test-comma", data))
    assert comma.no_page_mode == "suffix" and comma.suffix_for(NO_PAGE) == ", o. S."
    assert zstyles.preview(comma, "de", NO_PAGE)["no_page"] == "(Gillingham, 2019, o. S.)"
    # Abhängige Stile nutzen den Kurzbeleg ihres eigenständigen Stils
    assert zstyles.analyze_locator(zstyles.style_xml("test-dependent", data)).delimiter == ": "
    # Unbekannter Stil: Vorgabe wie APA
    assert zstyles.analyze_locator(None).no_page_mode == "suffix"


def _citation_items(zengine, style):
    cit = Citations(zengine, [("users/0", "ITEMA001")], style, "de")
    group = [CiteItem("users/0", "ITEMA001", NO_PAGE)]
    return cit, json.loads(cit.citation_json(group))["citationItems"][0], cit.short(group)


def test_no_page_in_word_citation_depends_on_style(zengine, fake_zotero, tmp_path, monkeypatch):
    build_library(fake_zotero)
    data = make_styles(tmp_path)
    monkeypatch.setattr(zstyles, "zotero_data_dir", lambda store=None: data)
    # Doppelpunkt-Stil: „o. S.“ als Seitenangabe – Zotero setzt das Trennzeichen des Stils
    _, item, short = _citation_items(zengine, "http://www.zotero.org/styles/test-colon")
    assert item["locator"] == NO_PAGE and item["label"] == "page" and "suffix" not in item
    assert short.endswith(": o. S.)")
    # Komma-Stil mit „S.“ vor der Zahl: als Suffix samt Trennzeichen (sonst „S. o. S.“)
    _, item, short = _citation_items(zengine, "test-comma")
    assert "locator" not in item and item["suffix"] == ", o. S." and short.endswith(", o. S.)")
    # Leere Kennzeichnung: nichts
    zengine.settings_store.update({"citation_no_page": ""})
    _, item, _ = _citation_items(zengine, "test-comma")
    assert "locator" not in item and "suffix" not in item
    # Seitenzahl wie bisher als Seitenangabe
    cit = Citations(zengine, [("users/0", "ITEMA001")], "test-colon", "de")
    page = json.loads(cit.citation_json([CiteItem("users/0", "ITEMA001", "114")]))["citationItems"][0]
    assert page["locator"] == "114" and cit.short([CiteItem("users/0", "ITEMA001", "114")]).endswith(": 114)")


# Wie FHNW: Namen mit „/“, ohne „und“, ab drei Namen „et al.“ (Begriff aus dem Stil)
SLASH = HEAD.format(cls="in-text", title="Schrägstrich-Stil", id="test-slash", extra="", fmt="author-date") + """
  <locale xml:lang="de"><terms><term name="et-al">et al.</term></terms></locale>
  <macro name="contributor-short"><names variable="author">
    <name form="short" delimiter="/" et-al-min="3" et-al-use-first="1"/></names></macro>
  <macro name="point-locators"><group><choose><if locator="page" match="none">
    <label variable="locator" form="short" suffix=" "/></if></choose><text variable="locator"/></group></macro>
  <citation><layout prefix="(" suffix=")" delimiter="; "><group delimiter=": "><group delimiter=" ">
    <text macro="contributor-short"/><date variable="issued"><date-part name="year"/></date></group>
    <text macro="point-locators"/></group></layout></citation></style>"""
# Wie APA: „&“, Optionen für „et al.“ am cs:citation (werden geerbt)
APA_LIKE = HEAD.format(cls="in-text", title="Und-Stil", id="test-and", extra="", fmt="author-date") + """
  <citation et-al-min="3" et-al-use-first="1"><layout prefix="(" suffix=")" delimiter="; "><group delimiter=", ">
    <names variable="author"><name form="short" and="symbol" delimiter=", "/></names>
    <date variable="issued"><date-part name="year"/></date>
    <group><label variable="locator" form="short" suffix=" "/><text variable="locator"/></group>
  </group></layout></citation></style>"""


def test_names_follow_the_style(zengine, tmp_path, monkeypatch):
    slash = zstyles.analyze_names(SLASH.encode(), "de")
    assert slash.found and slash.format(["Gong", "Li"]) == "Gong/Li" and slash.format(["A", "B", "C"]) == "A et al."
    apa = zstyles.analyze_names(APA_LIKE.encode(), "de")
    assert apa.format(["Gong", "Li"]) == "Gong & Li" and apa.format(["A", "B", "C"]) == "A et al."
    assert zstyles.NameStyle(and_="text").format(["A", "B"], "de") == "A und B"
    assert not zstyles.analyze_names(None).found

    folder = tmp_path / "zotero"
    (folder / "styles").mkdir(parents=True)
    (folder / "styles" / "slash.csl").write_text(SLASH, encoding="utf-8")
    monkeypatch.setattr(zstyles, "zotero_data_dir", lambda store=None: folder)
    zengine.store.upsert_items("users/0", [{"key": "GONG0001", "version": 1,
                                            "meta": {"creatorSummary": "Gong und Li", "parsedDate": "2026"},
                                            "data": {"itemType": "journalArticle", "title": "The adaptive ecological trap",
                                                     "date": "2026", "creators": [
                                                         {"creatorType": "author", "lastName": "Gong", "firstName": "G."},
                                                         {"creatorType": "author", "lastName": "Li", "firstName": "G."}]}}])
    cit = Citations(zengine, [("users/0", "GONG0001")], "test-slash", "de")
    assert cit.short([CiteItem("users/0", "GONG0001", "2")]) == "(Gong/Li 2026: 2)"
    assert cit.short([CiteItem("users/0", "GONG0001", NO_PAGE)]) == "(Gong/Li 2026: o. S.)"
    zengine.settings_store.update({"citation_style": "http://www.zotero.org/styles/test-slash"})
    from zotivity.exporting import source_reference

    ref = source_reference(zengine, "users/0", "GONG0001", "<FEFF0032>", "text")  # alte, rohe Beschriftung
    assert ref["short"] == "(Gong/Li 2026: 2)" and "adaptive ecological trap" in ref["reference"]


def test_styles_endpoint(client, tmp_path, monkeypatch):
    data = make_styles(tmp_path)
    monkeypatch.setattr(zstyles, "zotero_data_dir", lambda store=None: data)
    client.put("/api/settings", json={"citation_style": "http://www.zotero.org/styles/test-colon"}, headers=H)
    r = client.get("/api/styles").json()
    assert r["data_dir"] == str(data) and len(r["styles"]) == 4
    assert r["current"].endswith("test-colon") and r["analysis"]["mode"] == "locator"
    assert r["analysis"]["preview"]["no_page"] == "(Gillingham 2019: o. S.)"
    a = client.get("/api/styles/analyze", params={"id": "test-comma"}).json()
    assert a["mode"] == "suffix" and a["preview"]["no_page"] == "(Gillingham, 2019, o. S.)"

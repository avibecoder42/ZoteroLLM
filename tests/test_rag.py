import json
import re

import pytest
from fakes import ScriptedModel
from test_indexing_search import build_library, run_index

from zotivity.jobs import Job
from zotivity.rag import AskOptions, ChatService, ReviewService
from zotivity.rag import chat as chat_mod
from zotivity.rag import review as review_mod


@pytest.fixture
def indexed(zengine, fake_zotero):
    build_library(fake_zotero)
    run_index(zengine)
    return zengine


def install_models(monkeypatch, helper, main):
    from zotivity.keystore import get_store

    get_store().set("anthropic", "sk-test-0000")  # eingestellter Anbieter braucht einen Schlüssel
    monkeypatch.setattr(chat_mod, "helper_model", lambda cfg, meter=None: helper)
    monkeypatch.setattr(chat_mod, "main_model", lambda cfg, meter=None: main)
    monkeypatch.setattr(review_mod, "helper_model", lambda cfg, meter=None: helper)
    monkeypatch.setattr(review_mod, "main_model", lambda cfg, meter=None: main)


def test_chat_answer_with_sources(indexed, monkeypatch):
    helper = ScriptedModel([("Suchanfragen", json.dumps({"queries": ["chatbots adolescents", "Chatbots Jugendliche"]}))])
    main = ScriptedModel([("Textstellen aus der Bibliothek", "Jugendliche nutzen Chatbots für persönliche Probleme [1].")])
    install_models(monkeypatch, helper, main)
    events = list(ChatService(indexed).ask("Wie nutzen Jugendliche Chatbots?", None, AskOptions()))
    types = [e["type"] for e in events]
    assert types[0] == "chat" and "queries" in types and "sources" in types and types[-1] == "done"
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    assert sources[0]["item_key"] == "ITEMA001"
    assert sources[0]["zotero_select"].startswith("zotero://select/library/items/")
    answer = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "[1]" in answer
    # Die Textstellen gingen nummeriert an das Hauptmodell
    assert "[1] Müller 2024" in main.calls[0]
    chat_id = events[0]["chat_id"]
    msgs = indexed.store.chat_messages(chat_id)
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["sources"]

    # Folgefrage im selben Chat: Verlauf geht an das Modell
    list(ChatService(indexed).ask("Und welche Motive?", chat_id, AskOptions()))
    assert "Wie nutzen Jugendliche Chatbots?" in main.calls[-1]


def test_missing_key_gives_actionable_message(indexed, monkeypatch):
    from zotivity.keystore import get_store

    get_store().set("gemini", "AIza-test-0000")
    monkeypatch.setattr(chat_mod, "main_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Aufruf")))
    events = list(ChatService(indexed).ask("Chatbots Jugendliche", None, AskOptions()))
    assert any(e["type"] == "sources" and e["sources"] for e in events)
    err = next(e for e in events if e["type"] == "error")
    assert err["kind"] == "setup" and "Anthropic Claude" in err["message"] and "Google Gemini" in err["message"]
    assert not any(e["type"] == "warning" for e in events)


def test_search_only_needs_no_llm(indexed, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM darf nicht aufgerufen werden")

    monkeypatch.setattr(chat_mod, "helper_model", boom)
    monkeypatch.setattr(chat_mod, "main_model", boom)
    events = list(ChatService(indexed).ask("information systems", None, AskOptions(search_only=True)))
    assert any(e["type"] == "sources" and e["sources"] for e in events)


def test_review_full_flow(indexed, monkeypatch, fake_zotero):
    def screen(prompt):
        keys = re.findall(r"\[([A-Z0-9]{8})\]", prompt)
        return json.dumps({"decisions": [{"key": k, "decision": "include" if k == "ITEMA001" else "exclude",
                                          "reason": "passt" if k == "ITEMA001" else "anderes Thema"} for k in keys]})

    sheet = {"kurzbeschreibung": "Studie zu Chatbots.", "methode": "Befragung", "stichprobe": "1200 Jugendliche",
             "zentrale_befunde": ["Emotionale Unterstützung ist das wichtigste Motiv"],
             "kernzitate": [{"zitat": "emotionale Unterstützung das wichtigste Motiv ist", "seite": "1"}]}
    outline = {"title": "Forschungsstand Chatbots", "sections": [
        {"heading": "Einleitung", "focus": "Gegenstand", "keys": ["ITEMA001"], "words": 100},
        {"heading": "Befunde", "focus": "Motive", "keys": ["ITEMA001"], "words": 150}]}
    helper = ScriptedModel([
        ("möglichst ALLE relevanten Texte", json.dumps({"queries": ["Chatbots Jugendliche", "adolescents chatbots"]})),
        ("Entscheide für jeden Text", screen),
    ])
    main = ScriptedModel([
        ("Auswertungsblatt in diesem JSON-Format", lambda prompt: json.dumps(sheet)),
        ("Entwirf eine Gliederung", json.dumps(outline)),
        ("Schreibe jetzt den Abschnitt „Einleitung“", "## Einleitung\n\nChatbots werden genutzt [@ITEMA001]."),
        ("Schreibe jetzt den Abschnitt „Befunde“",
         "## Befunde\n\nLaut Studie ist „emotionale Unterstützung das wichtigste Motiv“ [@ITEMA001, S. 1]. "
         "Ein erfundenes Zitat: „dieser Satz steht nirgends im Originaltext der Studie“ [@ITEMA001]. "
         "Unbekannt [@ZZZZ9999]."),
    ])
    install_models(monkeypatch, helper, main)
    indexed.settings_store.update({"review": {"parallel_requests": 1}})
    zot = indexed.zotero()
    zot.authorize()

    svc = ReviewService(indexed)
    rid = svc.create("Test", "Wie nutzen Jugendliche Chatbots bei persönlichen Problemen?")
    res = svc.find_candidates(Job("review", "t"), rid)
    assert res["candidates"] == 2 and res["included"] == 1
    r = svc.get(rid)
    assert [d["item_key"] for d in r["docs"] if d["included"]] == ["ITEMA001"]

    exp = svc.export_collection(rid)
    assert exp["added"] == 1 and exp["collection_key"] in fake_zotero.items["ITEMA001"]["data"]["collections"]

    svc.confirm(rid)
    est = svc.estimate_extraction(rid)
    assert est["missing_sheets"] == 1 and est["input_tokens"] > 0
    out = svc.extract(Job("review", "t"), rid)
    assert out["created"] == 1 and out["notes"] == 1
    note_key = indexed.store.get_sheet("users/0", "ITEMA001")["note_key"]
    assert fake_zotero.items[note_key]["data"]["parentItem"] == "ITEMA001"
    assert "Kernzitate" in fake_zotero.items[note_key]["data"]["note"]
    # Seitenmarkierungen im Text an das Modell
    assert "[S. 1]" in next(c for c in main.calls if "Auswertungsblatt in diesem" in c)
    # Anzeige des Blatts: Felder ohne interne Angaben, Kernzitat mit Link auf die PDF-Seite, Notiz in Zotero
    view = svc.sheet_view("users/0", "ITEMA001")
    assert view["sheet"]["methode"] == "Befragung" and not any(k.startswith("_") for k in view["sheet"])
    assert view["quotes"] == [{"zitat": "emotionale Unterstützung das wichtigste Motiv ist", "seite": "1",
                               "url": "zotero://open-pdf/library/items/ATTA0001?page=1"}]
    assert view["note_select"] == f"zotero://select/library/items/{note_key}" and view["basis"] == "Volltext"
    # Ein einzelnes Blatt neu erstellen: ersetzt Blatt und Notiz, der Schritt des Forschungsstands bleibt
    sheet["kurzbeschreibung"] = "Neu gelesen."
    svc.rebuild_sheet(Job("review", "t"), rid, "users/0", "ITEMA001")
    assert svc.sheet_view("users/0", "ITEMA001")["sheet"]["kurzbeschreibung"] == "Neu gelesen."
    assert indexed.store.get_sheet("users/0", "ITEMA001")["note_key"] == note_key
    assert "Neu gelesen." in fake_zotero.items[note_key]["data"]["note"]
    assert svc.get(rid)["state"]["step"] == "extracted"
    with pytest.raises(ValueError):  # ohne vorhandenes Blatt: dafür gibt es „Fehlende Blätter erstellen“
        svc.rebuild_sheet(Job("review", "t"), rid, "users/0", "ITEMB001")

    svc.outline(Job("review", "t"), rid)
    svc.write(Job("review", "t"), rid)
    check = svc.get(rid)["state"]["check"]
    assert check["verified_quotes"] == 1
    assert len(check["unverified_quotes"]) == 1 and "erfundenes" not in check["unverified_quotes"][0]["quote"]
    assert check["unknown_keys"] == ["ZZZZ9999"]

    md = svc.render(rid)
    assert md.startswith("# Forschungsstand Chatbots")
    assert "[Müller 2024, S. 1](zotero://open-pdf/library/items/ATTA0001?page=1)" in md
    assert "## Literatur" in md and "Müller, A. (2024)" in md.split("## Literatur")[1]  # Verzeichnis aus Zotero

    note = svc.save_to_zotero(rid)
    assert "<h1>Forschungsstand Chatbots</h1>" in fake_zotero.items[note]["data"]["note"]


def test_citation_page_index(indexed, monkeypatch):
    svc = ReviewService(indexed)
    # Massgebend ist die erste genannte Seite („1, 9“ öffnete früher die PDF am Anfang)
    assert svc._page_index("users/0", "ITEMA001", "1, 9") == 0
    assert svc._page_index("users/0", "ITEMA001", "2–3") == 1
    assert svc._page_index("users/0", "ITEMA001", "2f.") == 1
    assert svc._page_index("users/0", "ITEMA001", "") is None
    # Gedruckte Seitenzahlen (Zeitschrift ab S. 245) werden auf die PDF-Seite umgerechnet
    chunks = [{"page_label": "245", "page_start": 0, "page_end": 0},
              {"page_label": "246–247", "page_start": 1, "page_end": 2}]
    monkeypatch.setattr(svc.store, "document_chunks", lambda lib, key: chunks)
    assert svc._page_index("users/0", "X", "247") == 2
    assert svc._page_index("users/0", "X", "250, 252") == 5
    assert svc._page_index("users/0", "X", "xii") is None


GARDEN = "Im Garten blühen Rosen und Tulpen, die Gärtnerin pflegt die Beete sorgfältig jeden Morgen. "
HARBOUR = "Im Hafen liegen grosse Containerschiffe vor Anker, Kräne entladen die Fracht bis tief in die Nacht. "


def test_citation_without_page_links_to_matching_page(zengine, fake_zotero, monkeypatch):
    fake_zotero.add_item("ITEMC001", "Zwei Themen", "Meier", "2020")
    fake_zotero.add_pdf("ATTC0001", "ITEMC001", [GARDEN * 40, HARBOUR * 40])
    run_index(zengine)
    store = zengine.store
    text = ("## Befunde\n\nGärten blühen [@ITEMC001, S. 1]. "
            "Im Hafen entladen Kräne die Containerschiffe [@ITEMC001].")
    rid = store.create_review("T", "Frage", {"sections": [{"heading": "Befunde", "text": text}]})
    store.put_review_docs(rid, [{"lib": "users/0", "item_key": "ITEMC001", "included": True}])
    svc = ReviewService(zengine)
    md = svc.render(rid, link_target="pdf")
    assert "[Meier 2020, S. 1](zotero://open-pdf/library/items/ATTC0001?page=1)" in md
    # Ohne Seitenangabe: Link auf die Seite, auf der die belegte Aussage steht; der Text bleibt „Meier 2020“
    assert "[Meier 2020](zotero://open-pdf/library/items/ATTC0001?page=2)" in md
    assert list(store.review_pages(rid).values()) == [1]  # gemerkt
    # Ohne Embeddings (z. B. Ollama aus) genügt der Wortvergleich
    monkeypatch.setattr(zengine, "vector_index", lambda: (_ for _ in ()).throw(RuntimeError("aus")))
    store.update_review_state(rid, {"sections": [{"heading": "B", "text": "Die Gärtnerin pflegt die Beete [@ITEMC001]."}]})
    assert "[Meier 2020](zotero://open-pdf/library/items/ATTC0001?page=1)" in svc.render(rid, link_target="pdf")
    # Link auf den Eintrag: keine Seitensuche
    assert "zotero://select/library/items/ITEMC001" in svc.render(rid, link_target="item")
    # Programmoberfläche: Beleg als #cite-N, je Beleg beide Ziele (Auswahl beim Klick)
    store.update_review_state(rid, {"sections": [{"heading": "A", "text": text}]})
    cites: list[dict] = []
    md = svc.render(rid, body_only=True, link_target="dialog", cites=cites)
    assert "[Meier 2020, S. 1](#cite-0)" in md and "[Meier 2020](#cite-1)" in md
    assert cites[0]["select"] == "zotero://select/library/items/ITEMC001" and cites[0]["page"] == "1"
    assert cites[0]["pdf"].endswith("?page=1") and not cites[0]["located"]
    assert cites[1]["pdf"].endswith("?page=2") and cites[1]["located"] and cites[1]["pdf_page"] == 2
    assert cites[1]["title"] == "Zwei Themen"
    # Englischer Forschungsstand: „p.“ statt „S.“
    store.update_review_state(rid, {"language": "en", "sections": [{"heading": "A", "text": text}]})
    assert "Meier 2020, p. 1" in svc.render(rid, body_only=True, with_links=False)


def test_check_english_quotation_marks(zengine, fake_zotero):
    """“…” endet beim schliessenden ” – nicht erst beim nächsten öffnenden Zeichen."""
    fake_zotero.add_item("ITEMQ001", "Zitate", "Meier", "2020")
    fake_zotero.add_pdf("ATTQ0001", "ITEMQ001", [GARDEN * 20])
    run_index(zengine)
    q = "die Gärtnerin pflegt die Beete sorgfältig"
    text = f"## A\n\nShe writes that “{q}” [@ITEMQ001, p. 1]. Later again: “{q} jeden Morgen” [@ITEMQ001, p. 1]."
    rid = zengine.store.create_review("T", "Frage", {"language": "en", "sections": [{"heading": "A", "text": text}]})
    zengine.store.put_review_docs(rid, [{"lib": "users/0", "item_key": "ITEMQ001", "included": True}])
    check = ReviewService(zengine).check(rid)
    assert check["verified_quotes"] == 2 and check["unverified_quotes"] == []

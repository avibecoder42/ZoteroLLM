"""Belege auf Einträge, die in Zotero gelöscht wurden: auf eine verbleibende Kopie desselben Werks umstellen,
sonst mit den gespeicherten Kurzangaben lesbar halten und in der Prüfung melden."""

from test_duplicates import add_copy
from test_indexing_search import build_library, run_index

from zotivity import references
from zotivity.rag.review import ReviewService


def make_review(engine, text, keys):
    state = {"step": "write", "sections": [{"heading": "Befunde", "text": text}],
             "outline": {"title": "Test", "sections": [{"heading": "Befunde", "keys": list(keys)}]}}
    rid = engine.store.create_review("Test", "Frage?", state)
    engine.store.put_review_docs(rid, [{"lib": "users/0", "item_key": k, "included": True} for k in keys])
    return rid


def setup(zengine, fake_zotero):
    build_library(fake_zotero)
    add_copy(fake_zotero)  # ITEMD001 = zweite Kopie von ITEMA001 (gleiches Werk)
    run_index(zengine)
    rid = make_review(zengine, "Chatbots helfen [@ITEMA001; @ITEMD001, S. 2]. Auch hier [@ITEMD001]. "
                               "Andere Befunde [@ITEMB001].", ["ITEMA001", "ITEMD001", "ITEMB001"])
    chat = zengine.store.create_chat("Frage")
    zengine.store.add_chat_message(chat, "assistant", "Antwort [1].", sources=[
        {"n": 1, "lib": "users/0", "item_key": "ITEMD001", "att_key": "ATTD0001", "citation": "Müller 2024"}])
    return rid


def test_deleted_copy_points_to_remaining_copy(zengine, fake_zotero):
    rid = setup(zengine, fake_zotero)
    # In Zotero gelöscht (Papierkorb): der Abgleich entfernt den Eintrag und stellt die Belege um
    del fake_zotero.items["ITEMD001"], fake_zotero.items["ATTD0001"]
    run_index(zengine)
    assert zengine.store.item("users/0", "ITEMD001") is None
    assert zengine.store.removed_items([("users/0", "ITEMD001")])[("users/0", "ITEMD001")]["title"] == \
        "Chatbots als Gesprächspartner"
    text = zengine.store.get_review(rid)["state"]["sections"][0]["text"]
    assert "ITEMD001" not in text
    assert "[@ITEMA001, S. 2]" in text and "Auch hier [@ITEMA001]" in text  # zusammengefasst, Seite bleibt
    assert {d["item_key"] for d in zengine.store.review_docs(rid)} == {"ITEMA001", "ITEMB001"}
    assert zengine.store.get_review(rid)["state"]["outline"]["sections"][0]["keys"] == ["ITEMA001", "ITEMB001"]
    msg = zengine.store.chat_messages(zengine.store.chats()[0]["id"])[0]
    assert msg["sources"][0]["item_key"] == "ITEMA001" and msg["sources"][0]["att_key"] == "ATTA0001"
    assert "o. A." not in ReviewService(zengine).render(rid, with_links=False)


def test_deleted_unique_text_stays_readable(zengine, fake_zotero):
    rid = setup(zengine, fake_zotero)
    del fake_zotero.items["ITEMB001"], fake_zotero.items["ATTB0001"]
    run_index(zengine)
    svc = ReviewService(zengine)
    doc = next(d for d in svc.get(rid)["docs"] if d["item_key"] == "ITEMB001")
    assert doc["removed"] and doc["citation"] == "Devlieghere 2018"
    body = svc.render(rid, with_links=False, body_only=True)
    assert "(Devlieghere 2018)" in body and "o. A." not in body
    check = svc.check(rid)
    assert [d["key"] for d in check["removed_docs"]] == ["ITEMB001"]
    assert check["removed_docs"][0]["title"] == "Information systems in social work"


def test_deleted_before_this_version_is_fetched_from_zotero(zengine, fake_zotero):
    """Vor 0.7.3 entfernte Einträge: Kurzangaben aus dem Papierkorb von Zotero holen, dann umstellen."""
    rid = setup(zengine, fake_zotero)
    with zengine.store.write() as con:  # wie früher: ohne Kurzangaben entfernt, in Zotero noch abrufbar
        con.execute("DELETE FROM items WHERE key='ITEMD001'")
    zengine.store.duplicates_gen += 1
    assert references.missing(zengine.store) == {("users/0", "ITEMD001")}
    result = references.repair(zengine)
    assert result["replaced"] == 1 and result["reviews"] == 1 and result["messages"] == 1 and not result["unresolved"]
    assert "ITEMD001" not in zengine.store.get_review(rid)["state"]["sections"][0]["text"]
    assert references.repair(zengine) == {"replaced": 0, "unresolved": []}  # nichts mehr zu tun

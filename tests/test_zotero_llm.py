import pytest

from zotivity.keystore import get_store
from zotivity.llm.anthropic_provider import supports_effort, supports_sampling
from zotivity.llm.base import parse_json
from zotivity.rag.markdown import md_to_html
from zotivity.zotero import ZoteroAuthRequired, ZoteroClient, zotero_open_pdf_url, zotero_select_url


def client(fz):
    return ZoteroClient("http://127.0.0.1:23119", keystore=get_store(), transport=fz.transport())


def test_status_and_write_flow(fake_zotero):
    fake_zotero.add_item("ITEM0001", "Titel")
    zc = client(fake_zotero)
    st = zc.status()
    assert st["running"] and st["local_api"] and st["server_id"] == fake_zotero.SERVER_ID
    assert not zc.has_write_access()
    with pytest.raises(ZoteroAuthRequired):
        zc.create_note("users/0", "ITEM0001", "<p>x</p>")
    assert zc.authorize() is True
    assert zc.has_write_access()  # "Immer erlauben" → Schlüssel liegt im Schlüsselspeicher
    note = zc.create_note("users/0", "ITEM0001", "<p>Blatt</p>", tags=["Zotivity-Auswertung"])
    write = fake_zotero.writes[-1]
    assert write["body"][0]["parentItem"] == "ITEM0001"
    assert fake_zotero.items[note]["data"]["note"] == "<p>Blatt</p>"
    col = zc.create_collection("users/0", "Zotivity – Test")
    assert zc.add_to_collection("users/0", col, ["ITEM0001"]) == 1
    assert col in fake_zotero.items["ITEM0001"]["data"]["collections"]
    # Zweites Hinzufügen ändert nichts
    assert zc.add_to_collection("users/0", col, ["ITEM0001"]) == 0


def test_rejected_key_is_forgotten(fake_zotero):
    zc = client(fake_zotero)
    zc.authorize()
    fake_zotero.local_key = "ROTATED"
    with pytest.raises(ZoteroAuthRequired):
        zc.create_collection("users/0", "x")
    assert not zc.has_write_access()


def test_denied_authorization(fake_zotero):
    fake_zotero.authorized = False
    assert client(fake_zotero).authorize() is False


def test_zotero_urls():
    assert zotero_open_pdf_url("users/0", "ABCD1234", 11) == "zotero://open-pdf/library/items/ABCD1234?page=12"
    assert zotero_open_pdf_url("groups/77", "ABCD1234") == "zotero://open-pdf/groups/77/items/ABCD1234"
    assert zotero_select_url("users/0", "K") == "zotero://select/library/items/K"


def test_bidi_isolates_removed(engine):
    from zotivity.rag.sources import author_year

    engine.store.upsert_items("users/0", [{"key": "BIDI0001", "version": 1,
                                           "data": {"itemType": "journalArticle", "title": "T", "creators": []},
                                           "meta": {"creatorSummary": "⁨Matthews⁩ und ⁨Peral⁩",
                                                    "parsedDate": "2024"}}])
    item = engine.store.item("users/0", "BIDI0001")
    assert author_year(item) == "Matthews und Peral 2024"
    assert author_year({"creator_summary": "⁨Alt⁩", "year": 2020}) == "Alt 2020"


def test_parse_json_variants():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Hier: {"queries": ["x"]} fertig') == {"queries": ["x"]}
    assert parse_json("[1, 2]") == [1, 2]
    with pytest.raises(ValueError):
        parse_json("kein json")


def test_claude_parameter_support():
    assert not supports_sampling("claude-opus-5-5")
    assert not supports_sampling("claude-sonnet-5-5")
    assert supports_sampling("claude-sonnet-4-6") and supports_sampling("claude-haiku-4-5")
    assert supports_effort("claude-opus-5-5") and supports_effort("claude-fable-5-1")
    assert not supports_effort("claude-haiku-4-5")


def test_markdown_to_html_is_safe():
    h = md_to_html("## Titel\n\nText mit **fett** und [Link](zotero://select/library/items/K).\n\n- a\n- b\n\n<script>x</script>"
                   "\n\n[böse](javascript:alert(1))")
    assert "<h2>Titel</h2>" in h and "<strong>fett</strong>" in h and "<ul><li>a</li>" in h.replace("\n", "")
    assert 'href="zotero://select/library/items/K"' in h
    assert "<script>" not in h and "javascript:" not in h

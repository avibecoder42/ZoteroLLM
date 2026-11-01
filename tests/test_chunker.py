from zotivity.extract.chunker import (
    chunk_pages,
    estimate_tokens,
    make_abstract_chunk,
    mark_references,
    reference_density,
    split_sentences,
)
from zotivity.extract.pdf import PageText, html_to_text, text_as_document


def pages(n=6, sentences=40):
    out = []
    for p in range(n):
        body = " ".join(f"Satz {p}.{i} über Jugendliche und digitale Medien im Alltag." for i in range(sentences))
        out.append(PageText(index=p, label=str(101 + p), text=body + "\n\nNeuer Absatz mit weiterem Text."))
    return out


def test_chunks_respect_size_and_overlap():
    chunks = chunk_pages(pages(), chunk_tokens=200, overlap_tokens=40, min_chunk_tokens=20)
    assert len(chunks) > 5
    for c in chunks[:-1]:
        assert estimate_tokens(c.text) <= 230
    # Überlappung: Ende eines Abschnitts taucht am Anfang des nächsten wieder auf
    tail = chunks[0].text.split(". ")[-1][:30]
    assert tail in chunks[1].text
    assert [c.ord for c in chunks] == list(range(len(chunks)))


def test_page_labels_and_ranges():
    chunks = chunk_pages(pages(), chunk_tokens=300, overlap_tokens=0)
    assert chunks[0].page_start == 0 and chunks[0].page_label.startswith("101")
    assert any("–" in c.page_label for c in chunks)
    assert chunks[-1].page_end == 5


def test_sentence_split_keeps_abbreviations():
    s = split_sentences("Das gilt z. B. für Jugendliche. Vgl. dazu Müller et al. 2020. Neuer Satz hier.")
    assert s[0].startswith("Das gilt z. B. für Jugendliche.")
    assert any("et al. 2020" in x for x in s)


def test_reference_detection():
    refs = " ".join(
        f"Author{i}, A., & Other, B. ({2000 + i}). Title of paper {i}. Journal, {i}(2), 1–{i + 10}. doi:10.1000/{i}"
        for i in range(12)
    )
    body = "Diese Studie untersucht, wie Jugendliche Chatbots nutzen, um persönliche Probleme zu besprechen. " * 6
    assert reference_density(refs) > 13
    assert reference_density(body) < 3
    chunks = chunk_pages([PageText(0, "1", body), PageText(1, "2", "Literatur\n\n" + refs)], chunk_tokens=250)
    mark_references(chunks)
    assert chunks[0].kind == "text"
    assert chunks[-1].kind == "references"


def test_abstract_chunk_and_text_docs():
    assert make_abstract_chunk("kurz") is None
    c = make_abstract_chunk("A" * 100)
    assert c.kind == "abstract" and c.page_start is None
    doc = text_as_document("Absatz eins.\n\n" * 400, "zotero-fulltext")
    assert doc.n_pages > 1 and all(p.label == "" for p in doc.pages)


def test_html_to_text_skips_scripts():
    t = html_to_text("<html><head><script>x=1</script></head><body><h1>Titel</h1><p>Text &amp; mehr</p></body></html>")
    assert "x=1" not in t and "Titel" in t and "Text & mehr" in t


def test_html_snapshot_with_unclosed_head():
    # Wiley-Schnappschuss: <head> wird nie geschlossen, </head> steht erst spät (z. B. in einem Stil-Block)
    body = "".join(f"<p>Absatz {i} über Entscheidungsunterstützung in der Sozialen Arbeit.</p>" for i in range(30))
    html = (f"<!DOCTYPE html><html><head><title>Seitentitel</title><style>p {{ color: red }}</style>"
            f"<body><nav>Menü</nav><article><h1>Can Predictive Algorithms Assist?</h1>{body}</article>"
            f"<footer>Impressum</footer><style>/* </head> */</style></body></html>")
    t = html_to_text(html)
    assert "Can Predictive Algorithms Assist?" in t and "Absatz 29" in t
    assert "Seitentitel" not in t and "Menü" not in t and "Impressum" not in t and "color" not in t


def test_html_unclosed_nav_falls_back_to_lenient_reading():
    body = "".join(f"<p>Satz {i} mit Inhalt, der gelesen werden soll.</p>" for i in range(40))
    t = html_to_text(f"<html><body><nav>Menü<svg/><div>{body}</div></body></html>")
    assert "Satz 39" in t

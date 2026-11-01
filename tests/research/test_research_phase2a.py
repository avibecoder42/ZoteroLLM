"""Phase 2a (Konzept 3.7): Grenzfälle sichtbar machen statt still ausfiltern.

Testfall für „fertig“: Mit der Ausschlussregel „cyberbully*“ samt Ausnahmen erscheinen Steer et al. 2020 und die übrigen
11 Grenzfälle aus dem Nachtrag in der Grenzfall-Warteschlange und verschwinden nicht.
"""

from __future__ import annotations

import sqlite3

import pytest
from research_fakes import pubmed_article
from test_research_pool_screening import make_project

from zotivity.research.errors import ResearchError
from zotivity.research.pool import pattern_regex
from zotivity.research.store import SCHEMA_VERSION, Store

# Die 12 Grenzfälle aus Cyberaggression/Recherche_Onlineaggression_2026-10-29.md („Nachtrag: Grenzfälle“);
# None = OpenAlex hat kein Abstract
GRENZFAELLE = [
    ("10.1016/j.chb.2020.106297", "“I feel like everyone does it”- adolescents' perceptions and awareness of the association "
                                  "between humour, banter, and cyberbullying", None),
    ("10.1080/17482798.2016.1233893", "“People think it’s a harmless joke”: young people’s understanding of the impact of "
                                      "technology, digital vulnerability and cyberbullying in the United Kingdom", "a" * 80),
    ("10.1177/0044118x241301062", "Cyber-Ostracism, Depression, and Adolescents’ Cyberbullying Perpetration: A Cross-Lagged "
                                  "Panel Analysis", "b" * 80),
    ("10.1177/1329878x211048512", "‘[Cyber]bullying is too strong a word…’: Parental accounts of their children's "
                                  "experiences of online conflict and relational aggression", "c" * 80),
    ("10.1016/j.acap.2019.11.001", "What Counts?: A Qualitative Study of Adolescents’ Lived Experience With Online "
                                   "Victimization and Cyberbullying", None),
    ("10.1080/14680777.2015.1137959", "Cyberbullying, conflict management or just messing? Teenage girls’ understandings "
                                      "and experiences of gender, friendship, and conflict on Facebook", "d" * 80),
    ("10.1375/ajgc.20.2.143", "Cyber-Aggression: Definition and Concept of Cyberbullying", "e" * 80),
    ("10.3389/fpsyt.2026.1746672", "A thematic analysis of adolescents’ perceptions of cyberbullying and cyberaggression: "
                                   "definitional distinctions and educational gaps", "f" * 80),
    ("10.1016/j.chb.2011.11.013", "Are Cyberbullies really bullies? An investigation of reactive and proactive online "
                                  "aggression", None),
    ("10.1016/j.chb.2015.10.005", "Adolescents' perception of the characterizing dimensions of cyberbullying: "
                                  "Differentiation between bullies' and victims' perceptions", None),
    ("10.3389/fpubh.2022.1000504", "Cyberbullying definitions and measurements in children and adolescents: Summarizing 20 "
                                   "years of global efforts", "g" * 80),
    ("10.1016/j.copsyc.2020.06.003", "Bystander reactions to cyberbullying and cyberaggression: individual, contextual, and "
                                     "social factors", None),
]
RULE = {"kind": "title", "pattern": "cyberbull*, bully*, mobbing", "active": True,
        "exceptions": "banter, teas*, jok*, humour, humor, drama, conflict*, \"just messing\", \"what counts\", defin*, "
                      "percept*, perceiv*, distinct*, threshold*, cyber-aggress*, ostraci*, exclu*, \"online aggress*\"",
        "exception_scope": "text"}


def pool_with_cases(service, extra=()):
    pid = make_project(service, prefilters=[RULE, {"kind": "no_abstract", "active": False}])["id"]
    run = service.store.add_run(pid, kind="import", source="ris")
    recs = [{"doi": d, "title": t, "abstract": a or "", "year": 2020} for d, t, a in GRENZFAELLE]
    recs += [{"doi": "10.9/plain", "title": "Cyberbullying victimization and depression in adolescents",
              "abstract": "x" * 80, "year": 2019}, *extra]
    service.store.add_records(pid, run, recs)
    return pid


def test_patterns():
    rx = pattern_regex("bully*")
    assert rx.search("Are Cyberbullies really bullies?") and rx.search("bullying")
    assert pattern_regex("cyber-bully*").search("cyber bullying") and pattern_regex("cyber-bully*").search("cyberbullying")
    assert not pattern_regex("mobbing").search("Mobbingopfer")
    assert pattern_regex("bull(y|ie)s").search("bullies") and pattern_regex('"what counts"').search("What Counts?")


def test_twelve_borderline_cases_do_not_disappear(service):
    pid = pool_with_cases(service)
    q = service.queue(pid, "borderline")
    dois = {it["doi"] for it in q["items"]}
    assert dois == {d for d, _, _ in GRENZFAELLE}
    assert all(it["borderline"][0]["where"] == "title" and not it["hidden_by"] for it in q["items"])
    steer = next(it for it in q["items"] if it["doi"] == "10.1016/j.chb.2020.106297")
    assert steer["no_abstract"] and steer["borderline"][0]["term"].lower() in ("perceptions", "humour", "banter")
    pool = service.pool(pid)
    assert pool["hidden"] == 1  # nur der Treffer ohne Ausnahmebegriff ist ausgeblendet – und bleibt im Pool
    rule = next(f for f in pool["prefilters"] if f["kind"] == "title")
    assert (rule["matched"], rule["hidden"], rule["exception"]) == (13, 1, 12)
    assert service.summary(pid)["borderline_open"] == 12


def test_exception_only_in_abstract_is_weaker(service):
    extra = [{"doi": "10.9/abs", "title": "Cyberbullying in schools", "abstract": "We study banter among adolescents " * 3}]
    pid = pool_with_cases(service, extra)
    items = service.queue(pid, "borderline")["items"]
    assert items[-1]["doi"] == "10.9/abs" and items[-1]["borderline_strength"] == 1
    p = service.get_project(pid)
    rule = next(f for f in p["prefilters"] if f["kind"] == "title")
    service.update_project(pid, {"prefilters": [{**rule, "exception_scope": "title"}, *p["prefilters"][1:]]})
    assert "10.9/abs" not in {it["doi"] for it in service.queue(pid, "borderline")["items"]}


def test_recall_check(service):
    pid = pool_with_cases(service)
    text = "\n".join(f"| Titel | [{d}](https://doi.org/{d}) |" for d, _, _ in GRENZFAELLE) + "\nund 10.9999/missing."
    r = service.set_key_papers(pid, text)
    assert len(r["papers"]) == 13 and r["warnings"] == 1
    assert next(x for x in r["papers"] if x["doi"] == "10.9999/missing")["status"] == "missing"
    assert all(x["status"] == "borderline" for x in r["papers"] if x["doi"] != "10.9999/missing")
    # Mit dem Vorfilter „ohne Abstract“ meldet der Recall-Check die still ausgeblendeten Schlüsselarbeiten
    p = service.get_project(pid)
    service.update_project(pid, {"prefilters": [p["prefilters"][0], {**p["prefilters"][1], "active": True}]})
    hidden = [x for x in service.recall(pid)["papers"] if x["status"] == "hidden"]
    # Ausnahmen gelten nur für die Titelregel: „ohne Abstract“ blendet die 5 ohne Abstract aus
    assert len(hidden) == 5 and all("ohne Abstract" in x["message"] for x in hidden)
    assert service.summary(pid)["recall_warnings"] == 6


def test_review_hidden(service):
    pid = pool_with_cases(service)
    hidden = service.pool(pid, status="hidden")["items"]
    assert [it["title"] for it in hidden] == ["Cyberbullying victimization and depression in adolescents"]
    rid = hidden[0]["id"]
    service.review(pid, [rid], "restore")
    assert not service.pool(pid, status="hidden")["items"]
    service.review(pid, [rid], "exclude", rule_id=hidden[0]["matched_by"][0])
    d = service.store.current_decision(pid, rid)
    assert d["status"] == "exclude" and d["reason"].startswith("Vorfilter: Titel enthält cyberbull*")
    service.review(pid, [rid], "borderline")
    assert service.store.current_decision(pid, rid)["borderline"] == 1
    with pytest.raises(ResearchError):
        service.review(pid, [rid], "vielleicht")
    md, _, _ = service.protocol(pid, "md")
    assert "| Titel enthält cyberbull*, bully*, mobbing (mit Ausnahmen) – Ausnahmen:" in md
    assert "| 13 | 12 | 0 | 1 | 13 | 0 | 1 |" in md  # getroffen, Ausnahme, ausgeblendet, geprüft, Grenzfall, auf, aus


def test_borderline_flag_carries_over_and_undo(service):
    pid = pool_with_cases(service)
    rid = service.pool(pid, status="hidden")["items"][0]["id"]
    service.review(pid, [rid], "restore")
    service.mark_borderline(pid, rid, True, "Grenze Spass/Bullying")
    service.decide(pid, rid, "include", 2)
    d = service.store.current_decision(pid, rid)
    assert (d["status"], d["folder"], d["borderline"], d["borderline_reason"]) == ("include", 2, 1, "Grenze Spass/Bullying")
    items = service.queue(pid, "borderline")["items"]
    assert items[-1]["id"] == rid  # entschiedene ans Ende, sonst nach Stärke
    service.undo(pid)
    d = service.store.current_decision(pid, rid)
    assert (d["status"], d["borderline"]) == ("open", 1)
    service.mark_borderline(pid, rid, False)
    assert not service.store.current_decision(pid, rid)["borderline"]
    md, _, _ = service.protocol(pid, "md")
    assert "Grenzfälle: 12" in md


def test_fetch_abstracts(service, sim):
    long = "Adolescents described many everyday conflicts online and how they handled them with friends."
    sim.pubmed_articles = [pubmed_article("111", "Teasing online among adolescents", doi="10.1/abc", abstract=long),
                           pubmed_article("222", "Bystanders in group chats", doi="10.1/def", abstract=long)]
    sim.crossref["10.1/xyz"]["abstract"] = "<jats:p>Digital stress among adolescents is common and often unspoken.</jats:p>" * 2
    sim.s2_abstracts["10.7/s2"] = "An abstract that only Semantic Scholar has, long enough to count as one."
    pid = make_project(service)["id"]
    run = service.store.add_run(pid, kind="import", source="ris")
    service.store.add_records(pid, run, [
        {"title": "Digital stress and friendship conflict", "doi": "10.1/xyz"},          # Crossref
        {"title": "Bystanders in group chats among youth", "pmid": "222"},                # PubMed über PMID
        {"title": "Teasing online among adolescents (copy)", "doi": "10.1/abc"},          # PubMed über DOI
        {"title": "Only semantic scholar knows this one", "doi": "10.7/s2"},              # Semantic Scholar
        {"title": "Nobody has an abstract for this work", "doi": "10.7/none"},
        {"title": "Already has an abstract here, nothing to do", "abstract": "z" * 80},
    ])
    r = service.fetch_abstracts(pid, limit=10)
    assert r["checked"] == 5 and r["filled"] == 4 and r["remaining"] == 0
    assert r["by_source"] == {"Crossref": 1, "PubMed": 2, "Semantic Scholar": 1}
    items = {it["title"]: it for it in service.pool(pid, show_hidden=True)["items"]}
    assert items["Digital stress and friendship conflict"]["abstract_source"] == "Crossref"
    nothing = items["Nobody has an abstract for this work"]
    assert nothing["no_abstract"] and not nothing["hidden_by"] and not nothing["decision"]  # nur Hinweis, kein Ausschluss
    assert service.fetch_abstracts(pid)["checked"] == 0  # kein zweiter Versuch


def test_fetch_abstracts_survives_rate_limit(service, sim):
    sim.s2_status = 429
    pid = make_project(service)["id"]
    run = service.store.add_run(pid, kind="import", source="ris")
    service.store.add_records(pid, run, [{"title": "A work without abstract anywhere", "doi": "10.7/none"}])
    r = service.fetch_abstracts(pid)
    assert r["filled"] == 0 and any("Semantic Scholar" in e for e in r["errors"]) and r["retry_possible"] == 1
    rec = service.store.records(pid)[0]
    assert rec["data"]["abstract_failed"] == ["Semantic Scholar"]
    sim.s2_status, sim.s2_abstracts["10.7/none"] = 200, "Found later, once a key was configured for Semantic Scholar."
    calls = len(sim.calls)
    r = service.fetch_abstracts(pid, retry=True)
    assert r["filled"] == 1 and r["by_source"] == {"Semantic Scholar": 1} and r["retry_possible"] == 0
    assert {c[0] for c in sim.calls[calls:]} == {"api.semanticscholar.org"}  # nur die ausgefallene Quelle erneut


def test_migration_from_schema_1(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE project(id INTEGER PRIMARY KEY, title TEXT NOT NULL, question TEXT NOT NULL DEFAULT '',
          description TEXT NOT NULL DEFAULT '', criteria_in TEXT NOT NULL DEFAULT '', criteria_out TEXT NOT NULL DEFAULT '',
          target_library TEXT NOT NULL DEFAULT 'users/0', target_name TEXT NOT NULL DEFAULT '',
          zotero_backend TEXT NOT NULL DEFAULT 'web', folder_map TEXT NOT NULL DEFAULT '[]',
          prefilters TEXT NOT NULL DEFAULT '[]', settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE TABLE decision(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, record_id INTEGER NOT NULL,
          status TEXT NOT NULL, folder INTEGER, reason TEXT NOT NULL DEFAULT '', by TEXT NOT NULL DEFAULT '',
          ai_suggestion TEXT, ai_reason TEXT, at TEXT NOT NULL);
        INSERT INTO project(title, created_at, updated_at) VALUES('alt', 'x', 'x');
        INSERT INTO decision(project_id, record_id, status, at) VALUES(1, 1, 'include', 'x');
    """)
    db.commit()
    db.close()
    s = Store(path)
    row = s.one("SELECT borderline, borderline_reason, ai_shown, method, batch FROM decision")
    assert tuple(row) == (0, "", None, "card", "")
    assert s.one("SELECT value FROM meta WHERE key = 'schema_version'")[0] == str(SCHEMA_VERSION)
    assert s.one("SELECT COUNT(*) FROM ai_suggestion")[0] == 0  # Tabelle der KI-Vorschläge ergänzt
    s.close()

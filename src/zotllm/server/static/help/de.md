# ZotLLM – Handbuch

## Überblick

ZotLLM erschliesst die eigene Zotero-Bibliothek – auch Gruppenbibliotheken – für Recherche und Schreiben. Es liest die PDFs und weiteren Texte, zerlegt sie in Abschnitte und macht sie nach Bedeutung und nach Stichworten durchsuchbar. Darauf bauen drei Arbeitsweisen auf:

- **Suchen** – eine schnelle Suchmaschine über alle Bibliotheken, ganz ohne Sprachmodell: Titel, Personen, Jahre, Schlagwörter, Abstracts und auf Wunsch der Volltext.
- **Fragen** – Fragen in eigenen Worten; das Sprachmodell antwortet nur aus den gefundenen Textstellen, und jede Aussage ist mit Quelle und Seite belegt.
- **Forschungsstand** – ein begleiteter Ablauf von der Suchstrategie über Auswertungsblätter je Text bis zur geprüften Synthese mit Literaturverzeichnis.

Davor kann die **Recherche** stehen: eine Literatursuche in Fachdatenbanken (PubMed, OpenAlex und weitere), mit Screening und Übergabe der ausgewählten Literatur in Zotero-Sammlungen.

Die Navigationsleiste links ist zweigeteilt. Oben stehen die Ansichten des aktiven **Projekts**: Projekt, Suchen, Fragen, Forschungsstand und Korpora. Unten stehen **Recherche**, **CSL-Editor**, **Index**, **Hilfe** und **Einstellungen**; sie gelten für alle Projekte (die Recherche hat eigene Projekte). Über dem Menü zeigt die Projektkachel das aktive Projekt; ein Klick darauf (oder **Strg+P**) wechselt das Projekt.

ZotLLM ist ein unabhängiges Projekt und steht in keiner Verbindung zu Zotero oder der Corporation for Digital Scholarship; „Zotero“ ist deren eingetragene Marke.

Die Statusleiste unten zeigt, ob Zotero erreichbar ist, welches Sprachmodell antwortet, welches Embedding-Modell sucht und wie viele Abschnitte durchsuchbar sind. Laufende Aufträge (Indexierung, Abgleich, Forschungsstand) erscheinen rechts mit Fortschritt; das × bricht sie ab.

Warnhinweise (braun hinterlegt) lassen sich mit dem × oben rechts ausblenden. Hinweise zum Zustand – etwa „Zotero ist nicht erreichbar“ – erscheinen nach dem nächsten Programmstart wieder; Hinweise zum Index erscheinen wieder, sobald sich die Lage ändert (z. B. ein anderes Embedding-Modell oder neue Texte).

### Der übliche Ablauf

1. **Einrichten** – Zotero verbinden, Sprachmodell und Embedding-Modell wählen (siehe Kapitel Einrichtung). Das Fenster **Einrichtung** zeigt eine Checkliste mit den offenen Schritten.
2. **Wissenskorpus anlegen** – Sammlungen oder ganze Bibliotheken aus Zotero auswählen, die durchsucht werden sollen.
3. **Indexieren** – ZotLLM liest die Texte ein. Das dauert je nach Umfang und Rechner Minuten bis Stunden und läuft im Hintergrund.
4. **Suchen, Fragen oder Forschungsstand** – die Ergebnisse lassen sich kopieren und als Word- oder LaTeX-Datei mit Zotero-Belegen exportieren.

### Tastenkürzel

- **Strg+1 … Strg+5** Projekt, Suchen, Fragen, Forschungsstand, Korpora
- **Strg+6** Index, **Strg+7** CSL-Editor, **Strg+8** Recherche, **Strg+,** Einstellungen, **F1** Hilfe
- **Strg+P** Projekt wechseln
- In der Recherche: **Alt+1 … Alt+8** wechselt den Reiter; im Screening siehe Kapitel Recherche
- **Esc** schliesst Menüs, Vorschauen und Dialoge
- In Eingabefeldern startet **Enter** die Suche bzw. sendet die Frage; **Umschalt+Enter** macht im Fragefeld eine neue Zeile.

> Zeigt eine Ansicht einmal einen Anzeigefehler, hilft **Neu laden** in der Fehlermeldung. Der Fehler wird im Protokoll festgehalten (Einstellungen → Programm & Daten → Protokolle).

### Seitenleisten

Die Leisten links (bzw. rechts in der Ansicht Index) lassen sich in der Breite verschieben: den Rand mit der Maus ziehen. Ein Doppelklick auf den Rand stellt die Standardbreite wieder her; mit dem Rand im Fokus ändern die Pfeiltasten ← → die Breite. Die gewählte Breite bleibt gespeichert.

### Programm schliessen

Schliessen des Fensters beendet ZotLLM ganz. Läuft gerade eine Indexierung, ein Abgleich oder ein Forschungsstand, fragt ZotLLM nach: Auf Wunsch läuft der Auftrag unsichtbar zu Ende, danach beendet sich das Programm selbst. Mit dem Zotero-Plugin startet ZotLLM beim nächsten Start von Zotero bzw. bei einem Befehl aus Zotero wieder unsichtbar im Hintergrund und endet einige Minuten nach Zotero.

## Einrichtung

Jeder Programmstart beginnt im Fenster **Einrichtung** – oberster Eintrag der Navigationsleiste, unter dem roten ZotLLM-Symbol. Oben stehen **Alle Projekte** (springt zur Ansicht Projekt mit allen Projekten), **Neues Projekt** und **Projekt importieren**, darunter die Checkliste der Einrichtung mit dem nächsten offenen Schritt. Solange Pflichtschritte offen sind, trägt der Eintrag Einrichtung einen Punkt.

### Zotero verbinden

ZotLLM liest die Bibliothek über die lokale Schnittstelle von Zotero. Sie muss einmal eingeschaltet werden:

1. Zotero öffnen und **Bearbeiten → Einstellungen** wählen (macOS: Zotero → Einstellungen).
2. Den Bereich **Erweitert** öffnen.
3. Das Häkchen bei **„Anderen Anwendungen auf diesem Computer erlauben, mit Zotero zu kommunizieren“** setzen.

Zotero muss geöffnet sein, solange ZotLLM abgleicht oder indexiert. Suchen, Fragen und Forschungsstand funktionieren danach auch bei geschlossenem Zotero – nur die Links nach Zotero brauchen ein laufendes Zotero. Die Zotero-Datenbank wird nie direkt gelesen oder verändert.

### Sprachmodell und API-Schlüssel

Unter **Einstellungen → Sprachmodelle** wählen Sie den Anbieter (Anthropic Claude, OpenAI, Google Gemini, DeepSeek, Ollama lokal oder ein OpenAI-kompatibler Server) und tragen den API-Schlüssel ein. Der Schlüssel wird verschlüsselt im Anmeldeinformationsspeicher von Windows abgelegt und nie im Klartext angezeigt oder in Dateien geschrieben.

Es gibt zwei Rollen:

- Das **Hauptmodell** schreibt Antworten, Gliederung und Text des Forschungsstands – hier lohnt sich ein starkes Modell.
- Das **Hilfsmodell** formuliert Suchanfragen und trifft die Vorauswahl der Texte – es darf günstig und schnell sein.

**Denktiefe** bestimmt, wie gründlich das Modell vor der Antwort „nachdenkt“. Höher ist besser bei schwierigen Fragen, aber langsamer und teurer. **Verbindung testen** schickt eine kurze Probeanfrage. Optional lassen sich Preise je Modell eintragen; der Forschungsstand schätzt damit die Kosten.

### Embedding-Modell

Das Embedding-Modell wandelt Textabschnitte in Vektoren um, damit nach Bedeutung gesucht werden kann – auch sprachübergreifend (eine deutsche Frage findet englische Texte). Standard ist **Eingebaut**: ZotLLM führt das Modell selbst aus (mit llama.cpp, derselben Technik, die Ollama nutzt), ohne zusätzliche Installation. Die Texte verlassen den Rechner nicht. Vorausgewählt ist **bge-m3**; wie alle Modelle wird es erst per Knopf heruntergeladen (ca. 0,6 GB).

Weiterhin wählbar sind **Ollama** (falls schon installiert), Cloud-Modelle (OpenAI, Gemini – schneller, die Texte gehen dann aber an den Anbieter), ein OpenAI-kompatibler Server und Sentence-Transformers. Jedes Modell hat einen eigenen Index (siehe **Modell wechseln**); der bisherige bleibt erhalten, bis Sie ihn unter **Gespeicherte Indizes** löschen. Diese Karte ist zugeklappt und nennt Anzahl, Platzbedarf und den aktiven Index; aufgeklappt zeigt sie je Modell die Modellgrösse, die Dimensionen, die Zahl der Abschnitte und den Platzbedarf der Vektoren.

### Modellkatalog: Auswahl, Download, Kurztest

Unter **Einstellungen → Embedding → Eingebaut** stehen im Alltag nur zwei Dinge: das aktive Modell und die **Installierten Modelle** (heruntergeladene, gerade ladende und eigene Modelle) mit Grösse, Zeit für 100 Seiten, Index und Aktionen. Alle weiteren Modelle öffnet **Modell hinzufügen …** in einem Dialog mit zwei Reitern: **Katalog** und **Nach Namen suchen**. Ist noch nichts heruntergeladen, schlägt die Karte das empfohlene Modell mit einem Download-Knopf vor. Selten Gebrauchtes – CPU-Threads, Parallelität, Entladen und der zentrale Modellkatalog – steht zugeklappt unter **Erweitert**.

Der **Katalog** enthält geprüfte Modelle, gruppiert nach *Empfohlen*, *Schnell*, *Alternativen*, *Gross* und *Fachmodelle*. Jede Zeile zeigt Stärken und die Fächer, für die das Modell besonders passt, Sprachen, Textlänge, die Wertung im mehrsprachigen MTEB-Test, die Lizenz, die Download-Grösse mit Arbeitsspeicher, die **Zeit für 100 Seiten** auf diesem Rechner und den Platzbedarf des Index für Ihre Bibliothek. **Details** (bei heruntergeladenen Modellen **Details und Präfixe**) unter dem Namen klappt Präfixe, Pooling, Datei und Messwerte auf; zu Beginn ist alles zugeklappt.

- **Herunterladen** lädt die Datei mit Fortschrittsanzeige in den lokalen Datenordner (nie in einen Cloud-Ordner) und prüft ihre Prüfsumme. Abbrechen ist jederzeit möglich; **Fortsetzen** lädt nur den Rest.
- Danach misst ein **Kurztest** (10–60 Sekunden) Tempo und Arbeitsspeicher und prüft mit deutschen und englischen Testfragen, ob das Modell die richtigen Stellen findet. Aus „geschätzt“ wird „gemessen“; die Schätzungen der übrigen Modelle richten sich danach. Vor dem ersten Kurztest beruhen sie auf einem kurzen Rechentest und den Messwerten des Referenzrechners.
- **Verwenden** macht das Modell zum aktiven Embedding-Modell. Gibt es schon einen Index desselben Modells aus Ollama, bietet ZotLLM an, ihn zu übernehmen: 24 Stichproben werden neu eingebettet und verglichen; stimmen die Vektoren überein, entfällt das Neu-Einbetten der ganzen Bibliothek. Die Rückmeldung nennt gleich, was der übernommene Index nicht enthält – etwa Texte, die zuletzt mit einem anderen Modell indexiert wurden –, und bietet an, nur diese einzubetten.
- **Präfixe** stehen vor jedem Text, bevor er eingebettet wird; viele Modelle unterscheiden so Suchanfrage und Textstelle. Bei heruntergeladenen Modellen lassen sie sich in den Details ändern (bei eigenen Modellen auch das Pooling); **Standard wiederherstellen** setzt die geprüften Werte des Katalogs zurück. Geänderte Präfixe ergeben einen eigenen Index – der bisherige bleibt unter **Gespeicherte Indizes** erhalten. Beim aktiven Modell erklärt ZotLLM danach wie bei einem Modellwechsel, was einzubetten ist.
- Über **⋯** lassen sich die Modelldatei löschen, die Modellbeschreibung öffnen und ein abgebrochener Download verwerfen. Den Index eines Modells löschen Sie getrennt unter **Gespeicherte Indizes**.
- Modelle mit wählbarer **Vektorlänge** (z. B. EmbeddingGemma 2) bieten in der Detailansicht kürzere Vektoren an: kleinerer Index, etwas ungenauer.

Für die meisten Bibliotheken – auch in den Geistes- und Sozialwissenschaften mit deutsch- und englischsprachiger Literatur – sind mehrsprachige Allzweckmodelle die beste Wahl. Fachmodelle gibt es meist nur auf Englisch (z. B. MedEmbed für Medizin). Grosse Modelle wie Qwen3-Embedding 4B finden am genauesten, sind ohne Grafikkarte aber sehr langsam. Auf Rechnern ohne AVX2 (ältere oder günstige Prozessoren) läuft die eingebaute Laufzeit ebenfalls, nur langsamer; dort eignen sich die schnellen Modelle.

Der Katalog wird mit ZotLLM geliefert und mit jeder Version erneuert. Unter **Erweitert → Zentraler Modellkatalog** lässt sich zusätzlich die Adresse eines zentralen Katalogs eintragen (später die Datei im GitHub-Repository von ZotLLM): Er wird beim Start geladen und nur übernommen, wenn er neuer ist.

### Modell nach Namen suchen

Weitere Embedding-Modelle im GGUF-Format sucht der Reiter **Nach Namen suchen** (im Dialog **Modell hinzufügen …**) auf Hugging Face, z. B. „e5“, „gte“ oder „granite-embedding“; auch eine eingefügte Adresse von Hugging Face funktioniert. Die Treffer zeigen Bauweise (ob llama.cpp sie als Embedding-Modell ausführen kann), Grösse, Lizenz, Downloads und Datum. **Auswählen** öffnet die Dateivarianten (Q8_0 empfohlen) und schlägt Präfixe und Pooling aus der Beschreibung des Originalmodells vor. Das Modell erscheint dann unter **Eigene Modelle**, als „nicht geprüft“ markiert – der Kurztest nach dem Download zeigt, ob die Suche damit funktioniert. Modelle, die eine Anmeldung bei Hugging Face verlangen, werden nicht unterstützt.

### Modelle vergleichen und Modell je Projekt

**Modelle vergleichen …** (bei den gespeicherten Indizes, sobald zwei Modelle einen Index haben) stellt in einem Dialog dieselbe Frage an zwei Modelle mit Index (reine Bedeutungssuche) und zeigt die Treffer nebeneinander; Texte, die beide finden, sind hervorgehoben. So lässt sich am eigenen Bestand entscheiden, welches Modell besser passt.

Im Dialog **Projekt bearbeiten** kann ein Projekt ein eigenes Embedding-Modell bekommen. Beim Öffnen des Projekts schaltet ZotLLM dann auf dieses Modell um; jedes Modell behält seinen eigenen Index, und fehlen dem Modell noch Texte, bietet ZotLLM das Einbetten an (siehe unten).

### Modell wechseln

Die Vektoren eines Modells passen nur zu diesem Modell – darum hat jedes Modell seinen eigenen Index. Nach einem Wechsel werden die Texte **nicht neu gelesen**: Der gelesene Text und seine Abschnitte bleiben, sie müssen nur für das neue Modell **eingebettet** werden (zum Begriff siehe **Index → Indexieren = Lesen + Einbetten**). Das geht deutlich schneller als eine erste Indexierung.

- Direkt nach dem Wechsel fragt ZotLLM einmal, ob die Texte gleich eingebettet werden sollen, und nennt die Zahl der Texte und Abschnitte und die geschätzte Dauer. **Jetzt einbetten** bettet nur ein – es wird nichts neu gelesen und nichts mit Zotero abgeglichen; **Später** schliesst den Dialog. Derselbe Wechsel wird nicht ein zweites Mal gemeldet.
- Bis dahin gelten diese Texte als **einzubetten**: Sie sind gelesen, aber mit dem neuen Modell noch nicht durchsuchbar. **Indexiert** heisst immer: mit dem aktiven Modell durchsuchbar. Die Bedeutungssuche findet einzubettende Texte noch nicht, die Stichwortsuche schon.
- Fragen und Forschungsstand zeigen in dieser Zeit einen Hinweis „Mit … sind erst … von … Texten durchsuchbar“ mit **Jetzt einbetten** und **Zurück zu …** (dem Modell mit dem bisher grössten Index).
- Unter **Gespeicherte Indizes** wechselt **Verwenden** sofort zu einem Modell zurück, dessen Index vorhanden ist – samt seinen Präfixen.
- Neue Texte, die nach dem Wechsel dazukommen, liest und bettet die nächste Indexierung wie gewohnt ein; dabei werden auch die einzubettenden Texte mit erledigt.
- **Wechsel während einer Indexierung**: Der laufende Lauf endet nach dem aktuellen Paket von Abschnitten mit dem Ergebnis „Modell gewechselt“. Bereits Verarbeitetes bleibt erhalten, und kein Vektor landet im Index des falschen Modells. Läufe in der Warteschlange arbeiten mit dem neuen Modell; im Bericht setzt **Mit dem neuen Modell weitermachen** den Lauf fort. Während ein Lauf arbeitet, weist **Einstellungen → Embedding** darauf hin.

### Schreibzugriff und Zotero-Plugin

Beide sind optional.

- **Schreibzugriff** braucht ZotLLM, um Auswertungsblätter als Notizen an Einträgen zu speichern und für den Forschungsstand Sammlungen anzulegen. Nach **Schreibzugriff freigeben** fragt Zotero in einem eigenen Dialog nach. Wählen Sie dort **„Entscheidung merken“**, sonst gilt die Freigabe nur bis zum nächsten Neustart. Liegt der Dialog hinter anderen Fenstern, in der Taskleiste auf Zotero klicken.
- Das **Zotero-Plugin** ergänzt Zotero um das Rechtsklick-Menü „ZotLLM“ (Indexieren, Fragen, Forschungsstand für Sammlungen und Einträge) und startet ZotLLM zusammen mit Zotero. Installation: **Einstellungen → Zotero und Export → Plugin speichern**, dann in Zotero **Werkzeuge → Plugins → Zahnrad → Plugin aus Datei installieren**.

## Projekte

Ein Projekt bündelt Korpora, Chats und Forschungsstände zu einem Vorhaben, z. B. einer Masterarbeit oder einem Artikel. Alles wird laufend gespeichert; es gibt kein „Speichern“.

Die Ansicht **Projekt** zeigt links alle Projekte untereinander; oben stehen **Neues Projekt** und **Importieren**. Bei vielen Projekten scrollt die Liste für sich. Ein Klick öffnet ein Projekt; es wird hervorgehoben, die Reihenfolge bleibt. Die Reihenfolge lässt sich von Hand ändern: eine Kachel mit der Maus nach oben oder unten ziehen (eine Linie zeigt, wo sie landet; am Rand scrollt die Liste mit), oder im Menü **⋯** **Nach oben** bzw. **Nach unten** wählen. Neue Projekte kommen ans Ende. Rechts steht die Übersicht des aktiven Projekts: seine Korpora mit Indexierstand, die letzten Fragen und die Forschungsstände.

- **Neues Projekt** legt ein leeres Projekt an (Name, Beschreibung, Farbe).
- Das Menü **⋯** auf einer Projektkachel bietet Bearbeiten, Nach oben/unten, Als Datei exportieren, Duplizieren, Archivieren und Löschen.
- **Als Datei exportieren** speichert das Projekt als `.zllm`-Datei – mit Korpus-Definitionen, Chats, Forschungsständen, Auswertungsblättern und Suchverlauf, aber ohne Index. So lässt sich ein Projekt sichern oder auf einen anderen Rechner bringen. **Importieren** lädt eine solche Datei; fehlende Sammlungen werden gemeldet.
- Ein Korpus kann zu mehreren Projekten gehören. Beim Löschen eines Projekts bleiben Korpora, die auch anderswo verwendet werden, erhalten.

### Archiv

**Archivieren** (Menü **⋯** oder Knopf in der Projektübersicht) räumt abgeschlossene Projekte weg, ohne etwas zu löschen: Das Projekt verschwindet aus der Liste und aus dem Projektumschalter und liegt unten in der Projektspalte unter **Archiv** (aufklappbar). Ein Klick auf ein archiviertes Projekt zeigt **Aus dem Archiv holen**, **Zurückholen und öffnen**, **Als Datei exportieren** und **Löschen**. Archivierte Projekte lassen sich erst nach dem Zurückholen öffnen. Mindestens ein Projekt bleibt immer offen.

## Wissenskorpora

Ein Wissenskorpus legt fest, welche Texte aus Zotero durchsucht werden. Er besteht aus Sammlungen (jeweils mit allen Untersammlungen), ganzen Bibliotheken oder einzelnen Einträgen – aus der eigenen Bibliothek und aus Gruppen.

### Korpus anlegen und bearbeiten

1. **Korpora → Neuer Korpus** wählen und einen Namen eingeben.
2. In der Liste **Zotero-Bibliothek** die gewünschten Sammlungen anhaken. Eine angehakte Sammlung schliesst ihre Untersammlungen ein; diese erscheinen dann ebenfalls markiert.
3. **Korpus anlegen** bzw. **Speichern**.

Die Sammlungsliste scrollt in einem eigenen Bereich; Kopf und Suchfeld bleiben stehen. Die eigene Bibliothek und die Gruppen sind farblich unterschieden: Bibliothekstitel und die Überschriften „Eigene Bibliothek“ und „Gruppen“ tragen einen farbigen Balken. Das Suchfeld filtert die Sammlungen nach Namen; **Alle aufklappen/zuklappen** und **Aktualisieren** stehen oben rechts.

Einzelne Einträge kommen über die Ansicht **Suchen** in einen Korpus (**In Korpus aufnehmen**). Sie erscheinen als gestrichelte Chips über der Sammlungsliste.

Das **⋯** neben einem Korpus in der linken Liste bietet **Aus diesem Projekt entfernen** (der Korpus bleibt bestehen und steht dann unter „Weitere Korpora“), **Indexieren** und **Korpus löschen …**. Beim Löschen fragt ein kleiner Dialog nach; dort lässt sich der Korpus stattdessen auch nur aus dem Projekt entfernen.

### Die Kennzahlen

Unter den gewählten Quellen zeigt ZotLLM – schon vor dem Indexieren:

- **Einträge** – Zotero-Einträge in der Auswahl (ohne Notizen).
- **Texte (PDF u. a.)** – Dateien mit Text, die indexiert werden können. Sie verteilen sich vollständig auf die nächsten vier Zahlen: Texte = indexiert + einzubetten + offen + ohne Text / Fehler.
- **indexiert** – mit dem aktiven Embedding-Modell durchsuchbar. Der Zusatz **davon … zu aktualisieren** nennt indexierte Texte, die der nächste Lauf neu einliest, etwa für genauere Seitenzahlen nach einem Update oder weil sich die Datei geändert hat; bis dahin sind sie mit dem bisherigen Text durchsuchbar.
- **einzubetten** – gelesen, aber für das aktive Embedding-Modell noch nicht eingebettet (nach einem Modellwechsel). Der Hinweis darunter bietet **Jetzt einbetten** an.
- **offen** – mit dem aktiven Modell noch nicht durchsuchbar; der nächste Lauf liest sie. Das sind neue Texte, aber auch früher gelesene, denen die Vektoren des aktiven Modells fehlen und die ohnehin neu gelesen werden.
- **ohne Text / Fehler** – z. B. Scans ohne Textebene.
- **Abschnitte durchsuchbar** – Textabschnitte, die mit dem aktiven Embedding-Modell gefunden werden.

Für eine Bibliothek, die noch nie abgeglichen wurde, steht „–“ und der Hinweis **Jetzt abgleichen**: Der Abgleich liest die Metadaten aus Zotero, danach erscheinen die Zahlen.

Über die Knöpfe unten lässt sich der Korpus direkt indexieren, befragen, für einen Forschungsstand verwenden oder seine Texte im Index ansehen.

## Index

Die Ansicht **Index** gilt für alle Projekte. Hier werden die Texte aller Korpora eingelesen und durchsuchbar gemacht – auch von Korpora anderer Projekte und von Korpora, die zu keinem Projekt mehr gehören («Aus diesem Projekt entfernen» löscht einen Korpus nicht; löschen lässt er sich unter **Korpora → Weitere Korpora → ⋯**). Die Karte **Zustand des Index (alle Korpora)** zählt deshalb alle Korpora zusammen, jeden Text einmal. Die Tabelle **Korpora (alle Projekte)** zeigt oben die Korpora des aktiven Projekts («Dieses Projekt») und darunter die übrigen («Andere Korpora», jeweils mit ihrem Projekt bzw. «in keinem Projekt»).

### Indexieren = Lesen + Einbetten

Indexieren besteht aus zwei Schritten:

1. **Lesen** – ZotLLM holt den Text aus der Datei, erkennt die Seitenzahlen und zerlegt den Text in Abschnitte. Ab hier findet die Stichwortsuche den Text.
2. **Einbetten** – das Embedding-Modell rechnet jeden Abschnitt in einen Vektor um, eine Liste von Zahlen, die die Bedeutung abbildet. Erst dann findet die Bedeutungssuche den Abschnitt, auch sprachübergreifend.

Die Vektoren gehören zum jeweiligen Modell. Nach einem Modellwechsel ist deshalb nur Schritt 2 nötig („einbetten“); ein Text, der nur neu gelesen werden muss, bleibt mit seinen bisherigen Vektoren durchsuchbar („zu aktualisieren“).

### Indexieren

**Alle Korpora indexieren** gleicht zuerst die Metadaten mit Zotero ab und liest dann alle neuen und geänderten Texte. Bereits eingelesene Texte werden nicht erneut verarbeitet; geänderte Dateien erkennt ZotLLM an ihrer Prüfsumme. **Vollständig abgleichen** lädt alle Metadaten neu (sonst geschieht das automatisch wöchentlich).

Beim Lesen bestimmt ZotLLM die **gedruckten Seitenzahlen** aus Kopf- und Fusszeilen (Jahrgang, Jahr und Heftnummer werden dabei herausgefiltert, die Seitenspanne aus Zotero dient als Gegenprobe) und merkt sich, wo innerhalb eines Abschnitts eine neue Seite beginnt. Findet sich keine Zählung, gilt die Quelle als „ohne Seitenzahlen“ (o. S.).

Ganz oben steht immer der **Zustand des Index** über alle Korpora: das aktive Embedding-Modell, Texte, indexiert (mit dem Zusatz „davon … zu aktualisieren“), einzubetten, offen, Probleme und durchsuchbare Abschnitte, dazu wann zuletzt geprüft wurde und wann die nächste automatische Prüfung ansteht. Texte = indexiert + einzubetten + offen + Probleme. Der Knopf sagt, was ein Lauf tut, z. B. **Indexieren: 9 lesen · 44 neu einlesen · 2 einbetten** – ein Lauf erledigt alles auf einmal. Fehlen nur Vektoren, bettet **Nur einbetten** (bzw. **… für … einbetten**) mit der geschätzten Dauer ein, ohne etwas neu zu lesen. Die Tabelle **Korpora** zeigt dieselben Zahlen je Korpus, „zu aktualisieren“ als kleines Symbol neben der Zahl der indexierten Texte; sie wird zusammen mit dem Zustand nachgeladen, auch nach einem Abgleich im Hintergrund. Bei mehr als zehn Korpora scrollt sie in sich, statt die Seite zu verlängern.

Während eines Laufs zeigt die Karte **Laufende Indexierung** oben einen Fortschrittsring mit Prozent, das Embedding-Modell und die **geschätzte Restzeit** („noch ca. …“). Sie beruht auf dem Tempo dieses Laufs und wird nach den ersten Texten genauer; solange ein Teil noch nicht abschätzbar ist, steht „noch mindestens …“. Darunter folgen „Text … von …“ (wie viele zu lesen und wie viele nur einzubetten sind), der aktuelle Text mit Seiten- und Abschnittsfortschritt, die nächsten Texte dieses Laufs und die zuletzt fertigen Texte. Derselbe Ring mit Prozent und Restzeit steht in der Statusleiste. Drei Zählungen sind zu unterscheiden:

- **in diesem Lauf eingebettet** – Abschnitte, die dieser Lauf verarbeitet hat;
- **… von … Abschnitten aller Korpora durchsuchbar** – alle Abschnitte im Index, die mit dem aktiven Modell durchsuchbar sind, auch aus früheren Läufen; dieselbe Zahl steht in der Statusleiste. Sie ist darum meist grösser als die Zahl dieses Laufs;
- **… von … Abschnitten dieses Texts** (unter dem aktuellen Text) – nur der Fortschritt des Texts, der gerade eingebettet wird.

Wie lange 100 Seiten dauern, zeigt der Modellkatalog unter **Einstellungen → Embedding**. Sie können ZotLLM währenddessen weiter benutzen. Ein Abbruch verliert höchstens den laufenden Text; der nächste Lauf macht dort weiter.

### Warteschlange

Starten Sie eine Indexierung, während schon eine läuft – etwa **Indexieren** bei einem Korpus, **Nur einbetten**, **Alle Korpora indexieren** oder über das Rechtsklick-Menü in Zotero –, kommt sie in die **Warteschlange**, statt abgelehnt zu werden. Die Karte **Warteschlange** unter „Laufende Indexierung“ zeigt je Auftrag die Art (Indexieren, Nur einbetten, Fehlerhafte Texte erneut versuchen …), den Korpus und seine Projekte, was dort gerade offen ist, und seit wann der Auftrag wartet.

- Mit den Pfeilen ändern Sie die Reihenfolge; der Papierkorb entfernt einen Auftrag.
- Die Läufe starten nacheinander, sobald der laufende fertig ist. **Abbrechen** beendet nur den laufenden Lauf; danach kommt der nächste an die Reihe.
- Ein Auftrag, der schon wartet, wird nicht doppelt aufgenommen. Die Statusleiste zeigt, wie viele Läufe warten.
- Solange Läufe warten, pausiert die automatische Prüfung. Die Warteschlange gilt bis zum Beenden von ZotLLM.

### Nach dem Lauf: Bericht und Verlauf

Ist ein Lauf beendet, meldet ZotLLM das Ergebnis – auch wenn Sie gerade in einer anderen Ansicht arbeiten („Anzeigen“ führt zum Index). Die Live-Ansicht weicht dem Bericht **Letzter Lauf**: Ergebnis (fertig, fertig mit Problemen, Etappe beendet, Modell gewechselt, abgebrochen oder Fehler), Zeitpunkt, Dauer, Auslöser (von Hand oder automatisch) und die Kennzahlen. Je nach Ergebnis gibt es **Probleme ansehen**, **Jetzt weitermachen**, **Mit dem neuen Modell weitermachen**, **Fortsetzen** oder **Erneut starten**. Unter **Verarbeitete Texte** stehen alle Texte des Laufs (anklickbar nach Zotero), darunter das Protokoll. Das × blendet den Bericht aus.

Der **Verlauf der Läufe** speichert die letzten Läufe dauerhaft im Index – so sehen Sie auch nach einem Neustart, was etwa nachts in Etappen geschah. Er zeigt die fünf neuesten auf einen Blick, ältere per Scrollen. Ein Klick auf eine Zeile zeigt deren Bericht. Automatische Prüfungen, bei denen nichts zu tun war, erscheinen nicht im Verlauf; sie aktualisieren nur „zuletzt geprüft“.

### Texte eines Korpus

Rechts steht immer der in der Tabelle **Korpora** gewählte Korpus (sein Name oben in der Spalte). Vorgewählt ist der Korpus des aktiven Projekts, dessen Texte zuletzt gelesen oder eingebettet wurden; ein angeklickter Korpus bleibt gewählt, bis Sie das Projekt wechseln. Die Spalte zeigt die Texte dieses Korpus in Gruppen: **In Arbeit** (der Text, der gerade gelesen oder eingebettet wird, mit Fortschritt), **Indexiert** (mit dem aktiven Modell durchsuchbar; mit Titel, Autor/in, Jahr, Seiten und Abschnitten), **Einzubetten** (gelesen, für das aktive Modell noch nicht eingebettet), **Zu aktualisieren** (durchsuchbar, wird beim nächsten Lauf neu gelesen), **Offen** (wird beim nächsten Lauf gelesen; früher gelesene Texte sind mit „früher gelesen, wird neu gelesen“ markiert) und **Probleme** (mit der Fehlermeldung). Während einer Indexierung wird die Spalte laufend aktualisiert („live“); ein Text erscheint erst unter „Indexiert“, wenn er fertig eingebettet ist. Ein Klick auf einen Titel zeigt den Eintrag in Zotero, das PDF-Symbol öffnet die Datei. Das Filterfeld sucht in Titel, Personen und Jahr.

### Dubletten

Liegt dasselbe Werk mehrfach in Zotero – etwa in «Meine Bibliothek» und in einer Gruppe, oder als nicht zusammengeführte Dublette –, verwendet ZotLLM je Werk nur eine Kopie. Erkannt wird das an der DOI (Feld DOI oder «DOI: …» im Feld Extra), sonst an Titel, Erstautor/in und Jahr. Kurze Titel wie «Editorial» werden nur über die DOI zusammengefasst, Einträge mit verschiedenen DOIs nie (meist verschiedene Fassungen, z. B. Preprint und Artikel). Steckt derselbe Eintrag in mehreren Sammlungen, ist das keine Dublette – er ist ohnehin nur einmal im Index.

- **Vor dem Indexieren**: Starten Sie einen Lauf von Hand und liegen im Umfang neue Dubletten, fragt ZotLLM vorher nach – nie während des Laufs. Je Werk sehen Sie die Kopien mit Bibliothek, Sammlungen und ob ihr Text gelesen ist bzw. Seitenzahlen erkannt sind. Vorgewählt ist der Vorschlag der Regel; «Für alle: Kopie aus …» wählt eine Bibliothek für alle Werke (ausser dort fehlt eine lesbare Datei). «Keine Dublette» verwendet alle Kopien.
- **Die Regel** (für Läufe im Hintergrund und aus Zotero, die nicht fragen): zuerst die Kopie mit lesbarem Text, dann die mit erkannten Seitenzahlen, dann die bevorzugte Bibliothek (**Einstellungen → Index → Dubletten**). Dort lässt sich die Rückfrage auch ausschalten.
- **Wirkung**: Nur die gewählte Kopie wird gelesen und eingebettet. Bei Fragen und im Forschungsstand zählt das Werk als eine Quelle mit einem Auswertungsblatt; Belege, Seiten und Links stammen aus der gewählten Kopie. Das gilt auch in Korpora, die nur eine andere Kopie enthalten – rechts unter «Texte im Korpus» steht dann «Kopie aus …».
- **Nachträglich ändern**: Unter **Index → Dubletten** stehen alle erkannten Werke. Eine andere Wahl liest der nächste Lauf ein; bis dahin bleibt die bisherige Kopie in Gebrauch.

### Automatisch, in Etappen und sicher

Diese Einstellungen stehen unter **Einstellungen → Index**; das Zahnrad oben in der Ansicht Index führt direkt dorthin.

- **Im Hintergrund aktualisieren**: Solange Zotero offen ist, prüft ZotLLM regelmässig auf neue und geänderte Einträge.
- **Etappen**: höchstens so viele Texte pro Lauf und nur in einem Zeitfenster (z. B. 22:00 bis 07:00). Für grosse Bibliotheken mit Tausenden PDFs ist das die bequemste Art.
- **Texte in einem eigenen Prozess lesen**: Eine defekte PDF, die das Lesen abstürzen lässt oder hängt, wird nach dem Zeitlimit als Fehler markiert – der Lauf geht weiter.
- **Rechner wach halten** verhindert den Ruhezustand während der Indexierung.
- Fällt der Embedding-Dienst kurz aus (z. B. Ollama neu gestartet), wartet ZotLLM eine einstellbare Zeit, statt abzubrechen.
- **Sicherung des Index**: nach Indexierläufen höchstens alle 12 Stunden; die zwei neuesten bleiben.

### Texte ohne Text

„Ohne Text“ sind meist Scans ohne Textebene. Abhilfe: unter **Einstellungen → Experten → Einlesen** die Texterkennung (OCR) einschalten (benötigt eine Tesseract-Installation) oder die PDF mit Texterkennung neu speichern. Danach **Erneut versuchen**.

Die Liste der Probleme führt jeden Anhang einzeln auf. Hat ein Eintrag mehrere Anhänge, kann er trotz eines Problems durchsuchbar sein – die Suche zeigt dann „indexiert“.

### Webseiten-Schnappschüsse

Gespeicherte Webseiten (Schnappschüsse, HTML) werden nur indexiert, wenn der Eintrag keine PDF bzw. EPUB hat. Sonst stünde derselbe Text doppelt im Index – samt Menüs und Literaturliste der Verlagsseite – und Antworten zeigten doppelte Fundstellen. Liefert die PDF keinen Text oder wird sie gelöscht, liest ZotLLM beim nächsten Indexieren den Schnappschuss.

### Word- und LibreOffice-Dokumente

Neben PDF, EPUB und Webseiten liest ZotLLM auch **Word-Dateien (.docx)** und **LibreOffice-Dokumente (.odt)**, die in Zotero als Anhang gespeichert sind: Haupttext mit Überschriften, Listen und Tabellen; Fuss- und Endnoten stehen am Ende ihrer Seite bzw. des Dokuments. Bei Dokumenten mit nachverfolgten Änderungen gilt der aktuelle Stand. Kopf- und Fusszeilen, Kommentare und Verzeichnisse werden nicht gelesen. Das alte Word-Format (.doc) wird nicht unterstützt – in Word mit **Speichern unter → Word-Dokument (.docx)** umwandeln.

**Seitenzahlen:** Word und LibreOffice merken sich beim Speichern, wo die Seiten umbrechen. Diese Angaben übernimmt ZotLLM, einschliesslich einer abweichenden ersten Seitenzahl. Es sind die Seiten, wie das Dokument beim letzten Speichern umbrochen war – auf einem anderen Rechner oder mit anderen Schriften können sie leicht abweichen. Fehlen die Angaben (z. B. bei einem Export aus Google Docs), lauten die Belege „o. S.“.

Ein Klick auf einen Beleg zeigt die Textstelle wie gewohnt. Weil Zotero Word-Dateien nicht selbst anzeigt, gibt es statt **PDF öffnen** nur **In Zotero zeigen**; von dort öffnet ein Doppelklick das Dokument.

## Suchen

Die Ansicht **Suchen** ist eine Suchmaschine über die ganze Zotero-Bibliothek – die eigene und alle Gruppen. Sie braucht kein Sprachmodell und ist daher schnell und kostenlos.

### Suchkatalog

Die Suche verwendet einen lokalen Katalog der Metadaten aller Bibliotheken. Beim ersten Öffnen legt ZotLLM ihn an (Zotero muss dafür laufen). Danach führt ZotLLM ihn selbst nach: Solange Zotero läuft, vergleicht es jede Minute die Versionsnummern der Bibliotheken mit dem Stand beim letzten Abgleich und gleicht bei einer Änderung ab – höchstens alle zwei Minuten und nur das Geänderte, meist in Sekunden; sonst stündlich. Bei Gruppenbibliotheken meldet Zotero keine Versionsnummer; dort fallen neue und gelöschte Einträge sofort auf, geänderte Felder beim stündlichen Abgleich. Die Leiste oben zeigt Umfang und Stand des Katalogs und – solange ein Abgleich aussteht, etwa während einer Indexierung – den Hinweis **Zotero wurde seither geändert** mit **Jetzt abgleichen**. Die Suche funktioniert auch ohne Zotero.

### Einfeld-Suche

Ins grosse Feld schreiben und **Enter** drücken. Gesucht wird in Titel, Personen, Publikation, Schlagwörtern, Abstract und DOI. Es gelten diese Regeln:

- Alle Wörter müssen vorkommen (UND).
- Wörter werden als Wortanfang gesucht: `digit` findet „digital“ und „Digitalisierung“.
- `"genaue Phrase"` in Anführungszeichen sucht die Wortfolge.
- `-wort` schliesst Treffer mit diesem Wort aus.
- `ODER` (oder `OR`) zwischen zwei Wörtern findet Treffer mit einem von beiden, z. B. `Jugend ODER Adoleszenz`.

### Erweiterte Suche

**Erweiterte Suche** öffnet einzelne Felder, die zusätzlich zum grossen Feld gelten:

- **Titel**, **Autor/in, Herausgeber/in**, **Publikation / Zeitschrift / Verlag**, **Schlagwörter**, **Abstract**, **DOI**
- **Volltext (indexierte Texte)** – sucht im Text der indexierten PDFs und zeigt die Fundstelle als Ausschnitt mit Markierung.
- **Jahr** von–bis, **Eintragsart** (z. B. Zeitschriftenartikel, Buch), **Bibliotheken** und **In Sammlung** (inkl. Untersammlungen)
- **nur mit PDF**, **nur indexierte Texte**

**Felder leeren** setzt alles zurück. Die Treffer lassen sich nach Relevanz, Jahr, Titel oder Autor/in sortieren; **Weitere laden** zeigt die nächsten 100.

### Bisherige Suchen

Die Leiste links zeigt alle Suchen des aktiven Projekts, die neueste oben – mit Suchbegriff, weiteren Feldern und Filtern, Trefferzahl und Zeitpunkt. Eine erneut ausgeführte Suche rückt nach oben statt doppelt zu erscheinen. Ein Klick auf eine Suche **füllt die Suchfelder** (bei Bedarf mit geöffneter Erweiterter Suche), sucht aber noch nicht: So lässt sie sich zuerst anpassen; **Suchen** oder **Enter** führt sie aus. Das **×** entfernt eine Suche aus dem Verlauf, der Papierkorb leert den Verlauf des Projekts. Ab sechs Einträgen erscheint ein Filterfeld. Jedes Projekt hat seinen eigenen Verlauf; er wird mit dem Projekt exportiert.

### Treffer

Jeder Treffer zeigt Titel, Personen, Jahr, Eintragsart und Publikation, darunter seine **Fundorte in Zotero**: die Bibliothek (farbig: eigene oder Gruppe) und alle Sammlungen, in denen der Eintrag liegt. Ein Klick auf einen Fundort zeigt den Eintrag in Zotero genau in dieser Sammlung.

- **In Zotero zeigen** – liegt der Eintrag an mehreren Orten, öffnet sich eine Auswahl.
- **PDF-Symbol** – öffnet die PDF in Zotero.
- **Zitat-Symbol (❝)** – kopiert den **Literaturnachweis** im Zitierstil der Einstellungen (Einstellungen → Zotero und Export), mit Formatierung für Word (Kursives bleibt kursiv) und als reiner Text. Die Meldung nennt den Stil. Den Nachweis liefert Zotero; ist Zotero geschlossen, baut ZotLLM eine vereinfachte Form nach und sagt das.
- **Korpus-Symbol** – **In Korpus aufnehmen**: Angeboten werden nur die Korpora des aktiven Projekts. Ist der Eintrag schon enthalten, ist er markiert und lässt sich dort wieder entfernen. **Neuer Korpus aus Auswahl** legt einen Korpus mit genau diesen Einträgen an.
- **⋯** – Kurzbeleg kopieren (z. B. «(Gong/Li 2026)»), DOI-Link oder Zotero-Link kopieren, speichern als Word, BibTeX, RIS oder Markdown, Fragen zu diesem Eintrag, in eine Zotero-Sammlung ablegen.
- Rechts stehen der Indexierstand (indexiert, noch nicht indexiert, ohne Text, ohne PDF) und die Korpora des Projekts, die den Eintrag schon enthalten.

### Auswahl und Sammelaktionen

Mit den Häkchen links wählen Sie Treffer aus: **Shift+Klick** wählt einen Bereich, **Strg+A** alle angezeigten Treffer (ausserhalb der Suchfelder), **Esc** hebt die Auswahl auf. Die Auswahl **bleibt über mehrere Suchen erhalten** – so lassen sich Quellen aus verschiedenen Suchen sammeln; sie gilt je Projekt, bis sie aufgehoben wird. Sobald etwas ausgewählt ist, erscheint über den Treffern eine Leiste, die beim Scrollen oben bleibt. Sie zeigt, wie viele Einträge gewählt sind und wie viele davon aus früheren Suchen stammen, und bietet:

- **Literaturliste kopieren** – alle gewählten Einträge im eingestellten Zitierstil, sortiert wie im Stil.
- **Kurzbelege kopieren** – z. B. «(Gong/Li 2026; Samatha et al. 2025)».
- **Exportieren** – **Word (.docx)** mit Belegen und Literaturverzeichnis als Zotero-Felder (mit dem Zotero-Word-Plugin im Stil änderbar), **BibTeX (.bib)** für LaTeX, **RIS (.ris)** für andere Literaturprogramme, **Markdown (.md)**.
- **In Korpus** – in einen Korpus des Projekts aufnehmen oder einen neuen anlegen. Neu aufgenommene Texte müssen anschliessend indexiert werden; die Meldung bietet dafür **Jetzt indexieren** an.
- **Fragen stellen** – öffnet **Fragen** mit genau diesen Einträgen als Umfang. Sind einige noch nicht indexiert, fragt ZotLLM, ob sie zuerst indexiert werden sollen (der Lauf kommt bei Bedarf in die Warteschlange) oder ob nur mit den indexierten gefragt wird.
- **⋯** – **In Zotero-Sammlung ablegen** (bestehende oder neue Sammlung; braucht den Schreibzugriff, siehe Einrichtung). Eine Zotero-Sammlung gehört zu einer Bibliothek: Liegen gewählte Einträge in verschiedenen Bibliotheken, wählen Sie die Bibliothek; Einträge aus den anderen werden übersprungen.
- **Nur Auswahl zeigen** listet alle gewählten Einträge, auch die aus früheren Suchen; **Aufheben** leert die Auswahl.

## Fragen

In **Fragen** stellen Sie Fragen in eigenen Worten. ZotLLM sucht die passenden Textstellen in den gewählten Korpora und lässt das Sprachmodell daraus eine Antwort schreiben. Das Modell darf nur verwenden, was in den Textstellen steht; jede Aussage ist mit einer Nummer belegt.

### Was durchsucht wird

Oben wählen Sie die **Wissenskorpora** – mehrere sind möglich. Ohne Auswahl werden alle Korpora des Projekts durchsucht. Aus dem Zotero-Plugin lässt sich auch direkt eine Sammlung oder eine Auswahl von Einträgen befragen; sie erscheint dann als Chip, das × kehrt zu den Korpora zurück.

Daneben wählen Sie **Antwort** oder **Nur Textstellen** (zeigt die gefundenen Textstellen ohne Antwort des Sprachmodells – schnell und kostenlos). Das **Preset** setzt die Such- und Antwortwerte für einen Zweck auf einmal (schnell, ausgewogen, gründlich). Ein Punkt zeigt, dass Werte vom Preset abweichen. Das Regler-Symbol öffnet die **Suchoptionen**: Zahl der Textstellen, höchstens je Text, Recherche-Runden und Mehrfachsuche – nur für diese Sitzung.

### Wie gesucht wird

1. Das Hilfsmodell formuliert mehrere Suchanfragen auf Deutsch und Englisch (**Mehrfachsuche**). Sie stehen aufklappbar über der Antwort.
2. Jede Anfrage sucht nach Bedeutung (Embeddings) und nach Stichworten (BM25); die Ranglisten werden zusammengeführt.
3. Ähnliche Textstellen werden zugunsten von Vielfalt ausgedünnt, höchstens wenige je Text.
4. Optional prüfen **Recherche-Runden**, ob Aspekte fehlen, und suchen gezielt nach; die **Neusortierung** ordnet die Kandidaten mit dem Hilfsmodell oder einem lokalen Cross-Encoder neu.

### Antwort und Belege

Ein Klick auf eine Belegnummer **[n]** zeigt die Textstelle mit Seite; von dort öffnet **PDF öffnen** die Datei an genau dieser Seite, und das Kopier-Symbol kopiert die ganze Textstelle mit dem Beleg im eingestellten Zitierstil (z. B. „(Gong/Li 2026: 2)“ bei FHNW) und dem Eintrag fürs Literaturverzeichnis. Unter der Antwort stehen alle Textstellen; die Balken zeigen ihre **Relevanz** im Vergleich zur besten Textstelle dieser Frage (keine Wahrscheinlichkeit).

Nach der Antwort lassen sich mit den Symbolen rechts unten **kopieren** (Text mit Quellenangaben) und **exportieren** (Word, LaTeX, Markdown). Auch die Liste der Textstellen lässt sich so kopieren und exportieren. Mehr dazu im Kapitel Export.

Folgefragen beziehen sich auf den bisherigen Verlauf. Links stehen die bisherigen Fragen des Projekts; **Neue Frage** beginnt einen neuen Verlauf.

## Recherche

Die **Recherche** (Strg+8) führt eine Literatursuche in Fachdatenbanken von der Fragestellung bis zur ausgewählten Literatur in Zotero. Die Maschine sucht, entfernt Duplikate und schlägt vor – entscheiden tun Sie. Recherche-Projekte sind unabhängig von den Projekten von ZotLLM; sie liegen in `research.db` im Datenordner. Ein Projekt hat acht Reiter (Alt+1 … Alt+8): Projekt, Datenbanken, Suchstrategie, Suche & Import, Pool, Ordner, Screening und Übergabe. Die Kopfzeile zeigt, wo das Projekt steht, z. B. „PubMed 503 · OpenAlex 934 · gesichtet 380/1150“.

### Projekt und Datenbanken

Unter **Projekt** stehen Fragestellung, Kurzbeschreibung sowie Ein- und Ausschlusskriterien (eine Zeile je Kriterium; die Ausschlussgründe stehen im Screening zur Wahl). Unter **Datenbanken** wählen Sie Disziplinen; die App schlägt passende Datenbanken aus ihrem Katalog vor, mit Zugang, Bedingungen und nötigem Schlüssel. Direkt durchsuchbar sind PubMed, OpenAlex, Europe PMC, ERIC, EconBiz, Semantic Scholar, arXiv, OSF-Preprints und swisscovery. Lizenzierte Datenbanken (PsycInfo, CINAHL, SocINDEX …) laufen über den **RIS-Weg**: dort suchen und exportieren, hier importieren. Die App meldet sich nie bei lizenzierten Datenbanken an und automatisiert keinen Browser.

Schlüssel liest die Recherche aus dem Schlüsselspeicher von ZotLLM: `openalex` (bei OpenAlex seit Februar 2026 nötig), `ncbi` (10 statt 3 PubMed-Anfragen pro Sekunde), `semanticscholar` und `zotero-web` für die Zotero-Web-API. Fehlt ein Schlüssel, zeigt der Reiter Datenbanken das an.

### Suchstrategie, Suche und Import

Die **Suchstrategie** besteht aus Konzeptblöcken (z. B. Population, Phänomen, Kontext, dazu ein Ausschlussblock): innerhalb eines Blocks gilt ODER, zwischen Blöcken UND, Ausschlussblöcke kommen mit NOT dazu. Daraus entstehen Suchstrings je Datenbank, mit Trefferzahl live. Blöcke sind freiwillig: Fertige Suchstrings lassen sich unter **Suche & Import** einfügen oder als Textdateien laden. Dort sind die Suchstrings versioniert; ein PubMed-String lässt sich in alle gewählten Datenbanken übersetzen (die Übersetzung ist ein Vorschlag – prüfen und zählen). **Alle zählen** und **Alle suchen** laufen über alle direkt durchsuchbaren Quellen; RIS-Dateien zieht man in die Drop-Zone. Jede Suche kommt ins Protokoll.

### Pool und Vorfilter

Der **Pool** enthält alle Treffer ohne Duplikate (DOI, PMID, OpenAlex-ID, Accession Number, Titel) – je Suchstring die Treffer der letzten Suche und dazu die Importe. **Mit Zotero abgleichen** markiert, was in der Zielbibliothek schon da ist. **Vorfilter** markieren nur, sie löschen nie: Eine Ausschlussregel wie „cyberbull*, bully*“ kann Ausnahmebegriffe haben; Treffer mit einem Ausnahmebegriff werden **Grenzfälle** statt ausgeblendet. **Ausgeblendete prüfen** öffnet eine Schnellsichtung mit Mehrfachauswahl. Fehlende Abstracts lädt die App über Crossref, PubMed und Semantic Scholar nach; ohne Abstract erscheint ein Treffer mit „nur Titel“, nie als Ausschluss. Der **Recall-Check** prüft bekannte Schlüsselarbeiten (DOIs) und warnt, wenn eine fehlt oder still ausgeblendet ist.

### Ordner

Unter **Ordner** wählen Sie die Zielbibliothek (eigene oder Gruppe, über Zotero auf diesem Computer oder die Zotero-Web-API) und legen bis zu 20 Ordner mit festen Nummern an, je einer Zotero-Sammlung zugeordnet; die ersten neun haben im Screening die Kürzel 1–9. Sammlungen wählen Sie im Baum wie in ZotLLM; neue lassen sich vormerken. In Zotero angelegt wird erst nach Ihrer Bestätigung.

### Screening

Das **Screening** zeigt die Treffer als **Karten** (ein Treffer mit ganzem Abstract) oder als **Liste** (alle offenen auf einmal). Kürzel auf den Karten: **J**/**K** blättern, **1–9** in den Ordner aufnehmen, **X** ausschliessen (mit Grund), **?** unsicher, **G** Grenzfall (mit Begründung; das Kennzeichen bleibt beim Entscheid), **A** KI-Vorschlag übernehmen, **Z** rückgängig. In der Liste haken Sie an, was aufgenommen wird; **Übernehmen …** zeigt die Bilanz und speichert alles als einen Stapel, den **Z** als Ganzes zurücknimmt. Warteschlangen für offene Treffer, Grenzfälle, unsichere und ausgeblendete Treffer.

### KI-Vorschläge

KI-Vorschläge sind freiwillig: im Screening (passend mit Ordner-Vorschlag, nicht passend, Grenzfall – je mit Kriterium und einem Satz Begründung), für Datenbanken aus der Fragestellung, für Konzeptblöcke und für Unterordner. Die Recherche nutzt das Modell der **Vorauswahl im Forschungsstand** (Einstellungen → Experten → Forschungsstand: Hilfs- oder Hauptmodell) mit dessen Denktiefe. Gesendet werden nur Titel, Zeitschrift, Jahr und Abstract der Treffer sowie der Projekttext, nichts aus Zotero und keine Volltexte. Vor jedem Lauf zeigt die App die geschätzten Token und – mit eingetragenen Preisen – die Kosten; der Lauf lässt sich anhalten. Der Schalter **KI-Vorschläge** blendet die Vorschläge aus (blind sichten). Ein Vorschlag ersetzt nie den Entscheid; beide stehen im Protokoll.

### Übergabe und Protokoll

Die **Übergabe** zeigt den Plan je Ordner: neue Einträge (Angaben auf Wunsch über Crossref vervollständigt, Schlagwort „litsearch“) und vorhandene, die nur der Sammlung zugeordnet werden. Nach Zotero geschrieben wird nur nach ausdrücklicher Bestätigung; für Zotero auf diesem Computer braucht es die Schreibfreigabe in Zotero. Das **Suchprotokoll** (Markdown, im Stil von PRISMA-S) enthält Quellen, Suchstrings mit Datum und Version, Trefferzahlen, Duplikate, Vorfilter je Regel, Ein- und Ausschlüsse je Grund, KI-Nutzung und die ausgewählte Literatur; dazu CSV-Dateien für Suchen sowie Treffer und Entscheide.

## Forschungsstand

Der Forschungsstand führt in fünf Schritten zu einem belegten Überblickstext. Jeder Schritt wartet auf Ihre Bestätigung; Sie können jederzeit zu einem früheren Schritt zurück. Jeder Schritt ist gleich aufgebaut: Oben stehen die fünf Schritte, darunter links der eingeklappte **Prompt** (Titel, Forschungsfrage, Korpora, Sprache, Ziel-Länge) und rechts die Knöpfe, mit denen es weitergeht – immer an derselben Stelle.

### 1. Stichworte

Sie geben eine Forschungsfrage ein, wählen die Korpora des Projekts, die Sprache des Textes und die Ziel-Länge. ZotLLM schlägt eine **Suchstrategie** vor: viele Suchanfragen auf Deutsch und Englisch, mit Synonymen und Fachbegriffen. Sie lassen sich ändern, löschen und ergänzen – wie Suchstrings in Literaturdatenbanken. **Suche starten** sucht mit allen Anfragen und wechselt zum nächsten Schritt. Danach zeigt jede Anfrage, wie viele Texte sie gefunden hat und wie viele nur durch sie; **Suche wiederholen** sucht nach einer Änderung neu (die bisherigen Häkchen gehen dabei verloren).

### 2. Literatur auswählen

Das Hilfsmodell schlägt eine Auswahl vor (vorgeschlagen, vielleicht, ausgeschlossen, jeweils mit Begründung). Sie prüfen die Häkchen. **Als Zotero-Sammlung** legt die Auswahl als Sammlung an; dort ergänzte Einträge holt **Aus Sammlung übernehmen** zurück. **Auswahl bestätigen** schliesst den Schritt ab.

### 3. Auswerten

Jeder Text wird einzeln gelesen – bis zu einer einstellbaren Länge ganz, sonst die zur Frage passenden Teile – und in einem **Auswertungsblatt** festgehalten: Fragestellung, Methode, Stichprobe, Befunde, Grenzen und wörtliche Kernzitate mit Seite. Die Seite eines Kernzitats überlässt ZotLLM nicht dem Sprachmodell: Es sucht das Zitat im Text und setzt die gedruckte Seitenzahl (oder „o. S.“). Vorher zeigt ZotLLM die gezählten Input-Token, die geschätzten Output- und Denk-Token und – wenn Preise eingetragen sind – die geschätzten Kosten. Blätter werden wiederverwendet; auf Wunsch speichert ZotLLM sie auch als Notiz am Zotero-Eintrag.

Ein Klick auf einen Text mit Häkchen zeigt sein Auswertungsblatt: Kurzbeschreibung, Felder, zentrale Befunde, Kernzitate und Stichworte, dazu Modell, Datum und Grundlage (ganzer Text oder Auszüge). Ein Klick auf die Seite eines Kernzitats öffnet die PDF in Zotero an dieser Stelle. **Blatt neu erstellen** liest nur diesen Text noch einmal und ersetzt das Blatt (und die Notiz in Zotero); ein bereits geschriebener Text bleibt unverändert.

### 4. Schreiben

Aus allen Blättern entsteht eine **thematische Gliederung** (nicht Text für Text). Überschriften, Fokus, Wortzahl und zugeordnete Texte lassen sich anpassen, Abschnitte hinzufügen, verschieben und entfernen. Danach werden die Abschnitte nacheinander geschrieben; jede Aussage wird mit dem Text belegt, aus dem sie stammt. Ist der Text geschrieben, wechselt ZotLLM zu **Prüfen** und zeigt ihn dort.

**Länge:** Die Ziel-Länge meint den Text mit Überschriften und Belegen – Literaturverzeichnis und der Anhang „Methode der Literatursuche“ kommen dazu (die Wortzählung von Word zählt sie mit). Die Gliederung verteilt die Ziel-Länge auf die Abschnitte; jeder Abschnitt erhält seine Wortzahl als verbindliche Obergrenze. Sprachmodelle schreiben trotzdem oft länger. Wird ein Abschnitt zu lang, bekommen die folgenden entsprechend weniger Platz (höchstens bis auf 60 % ihrer geplanten Länge). In der Gliederung steht neben jeder Wortzahl, wie viele Wörter tatsächlich geschrieben wurden.

Bricht der Anbieter einen Abschnitt vorzeitig ab – beim Längenlimit (bei Gemini zählen die Denk-Token mit) oder weil die Ausgabe eine längere Passage wörtlich wiedergab (eine Sperre von Gemini) –, schreibt ZotLLM ihn sofort ein zweites Mal: mit mehr Platz bzw. mit der Vorgabe, kürzer wörtlich zu zitieren. Einen einzelnen Abschnitt neu schreiben lassen Sie über das Stift-Symbol in der Gliederung; die übrigen Abschnitte bleiben dabei unverändert.

### 5. Prüfen und ausgeben

Die Prüfung zählt Wörter und zitierte Texte, sucht jedes wörtliche Zitat im Originaltext und meldet Belege auf Texte ausserhalb der Auswahl. Nicht gefundene Zitate sind oft nur Silbentrennungen oder Auslassungen – trotzdem vor der Verwendung mit der PDF vergleichen. Die Hinweise sind unter **Hinweise der Prüfung** eingeklappt; die Zeile nennt, was es zu prüfen gibt, ein Klick zeigt die Einzelheiten. Darunter steht der Text.

Sie meldet ausserdem **unvollständige Abschnitte**: vom Anbieter abgebrochen, mit einem Zitat ohne schliessendes Anführungszeichen, mitten im Satz endend oder zusätzlich deutlich kürzer als geplant. **Neu schreiben** neben dem Abschnitt ersetzt nur diesen. Abschnitte, die mehr als 20 % über ihrer geplanten Länge liegen, erscheinen als **zu lange Abschnitte**: **Kürzen** lässt das Sprachmodell einen Abschnitt auf die Länge aus der Gliederung straffen, **Alle kürzen** alle zu langen. Dabei kommt nichts Neues dazu (die Auswertungsblätter werden nicht mitgeschickt); Belege und wörtliche Zitate bleiben unverändert oder fallen weg. Die bisherige Fassung wird ersetzt – lesen Sie den Abschnitt danach. Wird die Antwort nicht kürzer, bleibt der Abschnitt, wie er war. **Erneut prüfen** wiederholt die Prüfung ohne Sprachmodell, etwa nach einer Änderung am Text.

**In Zotero gelöschte Texte:** Löschen Sie in Zotero einen Eintrag, den ein Forschungsstand oder eine gespeicherte Antwort zitiert, behält ZotLLM dessen Kurzangaben (Titel, Personen, Jahr, DOI). Gibt es vom selben Werk noch eine Kopie – etwa nachdem Sie eine Dublette gelöscht haben –, zeigen die Belege automatisch auf diese; stehen danach zwei gleiche Belege nebeneinander, bleibt einer. Gibt es keine Kopie mehr, bleibt der Beleg lesbar («Autor Jahr» statt «o. A. o. J.»), und die Prüfung meldet ihn. Korrigierte Angaben in Zotero (z. B. Name oder Jahr) erscheinen in den Belegen und im Literaturverzeichnis automatisch; den vom Sprachmodell geschriebenen Fliesstext ändert das nicht.

Ein Klick auf einen Beleg im Text öffnet eine kleine Auswahl: **In Zotero anzeigen** (wählt den Eintrag in Zotero aus) oder **PDF in Zotero öffnen** (an der zitierten Seite). Hat ein Beleg keine Seitenangabe, sucht ZotLLM im zitierten Text die Stelle, die der belegten Aussage am nächsten kommt, und öffnet die PDF dort; die Auswahl nennt dann die PDF-Seite. Diese Seite wird nur zum Öffnen verwendet, nicht in den Text geschrieben. Bei mehreren Seiten („S. 1, 9“ oder „12–14“) gilt die erste. Wohin die Belege in Exporten (Markdown, Notiz in Zotero) verlinken, legt **Einstellungen → Zotero und Export → Links der Belege in Exporten** fest. Ausgabe: **Kopieren**, **Exportieren** als Word, LaTeX oder Markdown, oder **Als Notiz in Zotero**. Alle Exporte enthalten am Ende die „Methode der Literatursuche“ mit Korpora, Suchanfragen und Treffern.

## Export nach Word und LaTeX

Antworten, Textstellen und Forschungsstände lassen sich kopieren und exportieren. Belege und Literaturverzeichnis stammen aus Zotero, damit sie dort weiter bearbeitbar bleiben.

### Word (.docx)

Jeder Beleg ist ein **Zotero-Feld**, das Literaturverzeichnis ebenfalls – genau so, als hätten Sie die Belege mit dem Zotero-Plugin für Word eingefügt. Nach dem Öffnen in Word:

1. Im Reiter **Zotero** auf **Refresh** klicken. Zotero formatiert Belege und Literaturverzeichnis im eingestellten Stil.
2. Belege lassen sich wie gewohnt mit **Add/Edit Citation** ändern; **Document Preferences** wechselt den Zitierstil (zu „o. S.“ siehe unten).

Damit das funktioniert, müssen die Einträge in der Zotero-Bibliothek vorhanden sein, mit der Word arbeitet. Einträge aus Gruppen werden über die Gruppe verknüpft. Mit installiertem ZotLLM-Plugin sind die Belege immer genau mit den Einträgen verknüpft, auch in einer nicht synchronisierten Bibliothek. Ist Zotero beim Export geschlossen, erzeugt ZotLLM die Belege aus den gespeicherten Metadaten; das Feld bleibt mit dem Eintrag verknüpft, das Literaturverzeichnis ist dann schlichter formatiert, bis Sie in Word auf Refresh klicken.

### LaTeX (.tex)

Die .tex-Datei ist sofort übersetzbar: Belege stehen als `\parencite[S.~12]{schluessel}`, die BibTeX-Daten aus Zotero in einer `filecontents`-Umgebung am Anfang. Übersetzen mit pdflatex oder lualatex und **biber**. Die erzeugte `literatur.bib` lässt sich auch in Zotero importieren oder durch die eigene Better-BibTeX-Datei ersetzen.

### Kopieren und Markdown

- **Als Text** kopiert den Text mit Kurzbelegen (Autor, Jahr, Seite) und Literaturverzeichnis.
- **Formatiert für Word** kopiert dasselbe mit Überschriften und Hervorhebungen zum Einfügen in Word, Mail oder andere Programme (ohne Zotero-Felder).
- **Markdown (.md)** speichert eine Textdatei mit Kurzbelegen und Literaturverzeichnis.

Den Zitierstil für Exporte wählen Sie unter **Einstellungen → Zotero und Export** aus den Stilen, die in Zotero installiert sind (neue Stile in Zotero unter *Einstellungen → Zitieren* installieren, dann in ZotLLM die Liste aktualisieren). Fussnotenstile werden noch nicht unterstützt. Die Sprache des Literaturverzeichnisses folgt der Sprache der KI-Ausgaben.

### Seitenzahlen und „o. S.“

Belege nennen die **gedruckte Seitenzahl** (aus Kopf- oder Fusszeile), nicht die Seite der PDF-Datei – Gillingham (2019) in *Child Abuse Review* 28: 114–126 wird also mit „S. 114“ belegt, auch wenn die PDF mit Seite 1 beginnt. Der Link in die PDF führt trotzdem an die richtige Stelle. Hat eine Quelle keine Seitenzahlen (Berichte, Webseiten, manche Preprints), steht **„o. S.“** – bei wörtlichen Zitaten, nicht bei jedem sinngemässen Beleg.

Wie „o. S.“ in Word in den Zotero-Beleg kommt, hängt vom Stil ab; die Einstellungen zeigen einen Musterbeleg:

- Setzt der Stil die Seite **ohne** Bezeichnung (z. B. „(Müller 2019: 114)“), kommt „o. S.“ als Seitenangabe in den Beleg – das Trennzeichen setzt der Stil selbst, auch bei „ebd.: o. S.“.
- Setzt der Stil **„S.“** vor die Seite (z. B. APA: „(Müller, 2019, S. 114)“), wäre das „S. o. S.“; dann kommt „, o. S.“ als **Suffix** in den Beleg (in Word im Zotero-Dialog des Belegs sichtbar und änderbar), mit dem Trennzeichen des Stils.

Den Stil später besser in ZotLLM ändern und neu exportieren statt in Word: Die Kennzeichnung ist an den gewählten Stil angepasst. Text und Kennzeichnung („o. S.“) lassen sich unter *Kennzeichnung ohne Seitenzahl* ändern oder leeren.

## CSL-Editor

Zitierstile (CSL) legen fest, wie Belege und Literaturverzeichnis aussehen. Im **CSL-Editor** passen Sie einen bestehenden Stil an – etwa den Ihrer Hochschule – und installieren ihn in Zotero. Die Vorschau rechnet mit **citeproc-js**, derselben Software, mit der Zotero Zitate erzeugt: Was Sie sehen, erscheint auch in Word.

> **Erste Version:** Der CSL-Editor befindet sich noch in Entwicklung. Hinweise, Fehlermeldungen und Beiträge sind willkommen – als Issue oder Pull Request auf [GitHub](https://github.com/avibecoder42/ZotLLM/issues).

### Stile finden und übernehmen

Links stehen drei Listen: **Eigene** (in ZotLLM bearbeitete Stile), **Zotero** (in Zotero installierte Stile) und **zotero.org** (Suche in den rund 10 000 Stilen des Zotero-Stilverzeichnisses, filterbar nach Format). Die Liste von zotero.org wird erst bei einer Suche geladen (einmalig rund 300 KB) und danach nur abgefragt, wenn sie sich geändert hat. Ausserdem lässt sich eine .csl-Datei importieren.

Fremde Stile sehen Sie zuerst nur in der Vorschau. **Als eigenen Stil übernehmen** legt eine Kopie mit eigenem Namen und eigener Kennung an – das Original bleibt unverändert und wird beim Installieren nicht überschrieben. Bei **abhängigen Stilen** (viele Zeitschriftenstile verweisen nur auf einen Elternstil) entsteht eine eigenständige Kopie des Elternstils.

### Bearbeiten in der Vorschau

Die Vorschau zeigt Belege im Text (mit Seitenangabe) und Einträge im Literaturverzeichnis für typische Dokumenttypen: Buch, Sammelbandbeitrag, Zeitschriftenartikel, Artikel mit vier Autor:innen, Zeitungsartikel, Webseite, Hochschulschrift, Bericht und herausgegebenes Buch. Gibt es in Ihrer Bibliothek einen passenden Eintrag, nimmt ZotLLM ihn (den vollständigsten; bei Artikeln mit der passenden Zahl Autor:innen, beim herausgegebenen Buch nur mit Herausgeber:innen) – sonst ein erfundenes englisches Beispiel. Einzelne eigene Einträge kommen unten über die Suche dazu. Die Sprache der Vorschau (Begriffe wie „S.“ oder „Hrsg.“) ist wählbar.

**Eintragsarten wählen …** legt fest, welche Arten die Vorschau zeigt: Standardbeispiele lassen sich abwählen, und alle weiteren Arten, die Zotero kennt, kommen dazu – etwa Gerichtsentscheidung, Gesetz, Konferenzbeitrag, Vortrag, Film oder Datensatz. Die Liste und die Namen liefert Zotero selbst (zuletzt gespeicherte Fassung, wenn Zotero nicht läuft). Auch hier kommt das Beispiel aus Ihrer Bibliothek, wo es einen Eintrag dieser Art gibt; der Schalter oben im Fenster lässt stattdessen nur erfundene Beispiele zeigen. Das × an einem Beispiel blendet es aus, **Standardauswahl wiederherstellen** stellt die neun Standardbeispiele wieder her. Die Auswahl gilt für alle Stile. Hat ein Stil für eine Art keine eigene Regel, zeigt die Vorschau, wie er sie allgemein darstellt.

**Sammlung …** zeigt die Einträge einer Zotero-Sammlung (mit Untersammlungen, höchstens 40) als Beispiele – etwa eine Sammlung mit typischen Fällen, an denen Sie einen Stil prüfen. Im Fenster wählen Sie die Sammlung aus Ihren Bibliotheken; **Nur diese Sammlung zeigen** blendet die Eintragsarten aus. Oben steht dann die Sammlung mit der Zahl der Einträge; ihr × hebt die Auswahl wieder auf.

**Klicken Sie auf einen Teil eines Belegs**, etwa auf die Jahreszahl: Rechts erscheinen genau die Eigenschaften dieses Bausteins – Text davor und danach, kursiv, fett, Kapitälchen, Gross-/Kleinschreibung; bei Namen „und“ oder „&“, Reihenfolge, Initialen und ab wie vielen Namen „et al.“ steht; bei Daten die Form; bei Seitenangaben „S.“ oder „Seite“. Die Leiste oben im Panel zeigt den Weg vom Text bzw. Verzeichnis über die Bausteine bis zum angeklickten Teil; ein Klick darauf wählt diese Ebene – etwa die Stelle, an der ein Baustein im Verzeichnis steht. Teile lassen sich verschieben, entfernen oder um ein Feld ergänzen.

**Verschieben:** **Früher** und **Später** tauschen mit dem Nachbarn; am Anfang bzw. Ende einer Gruppe verlässt der Teil die Gruppe. **Ganz nach vorne** und **Ganz nach hinten** setzen ihn an den Anfang bzw. das Ende des Eintrags (genauer: der äussersten Gruppe). Steht der gewählte Teil allein – wie das Jahr im Baustein „date“ –, verschiebt ZotLLM die nächsthöhere Ebene: die Stelle des Bausteins im Verzeichnis oder die ganze Bedingung („wenn Buch …, sonst …“), deren Fälle in ihrer Reihenfolge bleiben. Ein Hinweis sagt, was verschoben wird. So steht etwa das Jahr mit einem Klick auf **Ganz nach hinten** am Schluss des Eintrags.

**„et al.“** braucht zwei Zahlen: **„et al.“ ab … Namen** (ab wie vielen Namen gekürzt wird) und **Davon nennen** (wie viele davor stehen bleiben). APA kürzt im Text ab 3 Namen auf den ersten, manche Verzeichnisse ab 6 Namen auf die ersten 3. Unter den Feldern steht ein Beispiel der Einstellung.

Viele Stile verwenden Bausteine (Makros) an mehreren Stellen. Liegt der gewählte Teil in einem solchen Baustein, sagt das Panel, an wie vielen Stellen er wirkt. Oft teilen sich Belege im Text und Literaturverzeichnis einen Baustein, etwa für das Jahr. Dann erscheint **Änderung gilt**: Vorgegeben ist der Teil, in den Sie geklickt haben (**nur im Text** bzw. **nur im Verzeichnis**). Bei der ersten Änderung bekommt dieser Teil eine eigene Kopie des Bausteins (z. B. „date-bibliography“), der andere bleibt unverändert. Mit **in Text und Verzeichnis** wirkt die Änderung in beiden. Nach jeder Änderung sind die betroffenen Beispiele markiert („Die letzte Änderung betrifft 5 von 9 Beispielen“). Ohne Auswahl zeigt das Panel Einstellungen für den ganzen Stil, z. B. „et al.“ in Belegen und Verzeichnis, hängender Einzug oder Seitenbereiche.

### Code und frühere Fassungen

Unter **Code** steht der Stil als XML. Änderungen erscheinen sofort in der Vorschau; Fehler werden mit Zeile und Spalte gemeldet. **Zur Auswahl springen** markiert den in der Vorschau gewählten Baustein im Code. Was die Klick-Bearbeitung nicht abdeckt (z. B. Sortierung, Disambiguierung, neue Bedingungen je Dokumenttyp), lässt sich hier bearbeiten.

**Rückgängig** und **Wiederholen** (Strg+Z) gelten für alle Änderungen. **Speichern** (Strg+S) legt die bisherige Fassung unter **Frühere Fassungen** ab (die letzten 30).

### In Zotero installieren

**In Zotero installieren** übergibt den gespeicherten Stil dem ZotLLM-Plugin, das ihn mit der Zotero-eigenen Funktion installiert. Der Stil steht danach sofort in Zotero, im Word-Plugin und in ZotLLM (**Einstellungen → Zotero und Export**) zur Wahl. Installieren Sie einen geänderten Stil erneut, ersetzt er die frühere Fassung in Zotero. Ohne aktuelles Plugin speichert ZotLLM den Stil als .csl-Datei; in Zotero dann **Einstellungen → Zitieren → „+“** wählen und die Datei öffnen.

## Einstellungen

- **Sprachmodelle** – Anbieter, API-Schlüssel, Haupt- und Hilfsmodell, Denktiefe, Preise.
- **Embedding** – Anbieter (eingebaut, Ollama, Cloud), Modellkatalog mit Download und Kurztest, Namenssuche auf Hugging Face, gespeicherte Indizes, Modellvergleich; Laufzeit (CPU-Threads, gleichzeitige Abschnitte, Entladen nach Leerlauf, zentraler Modellkatalog).
- **Index** – automatisch im Hintergrund und in Etappen, Schutz für grosse Bibliotheken (eigener Prozess, Zeitlimit, wach halten, Warten bei Ausfall des Embedding-Dienstes), Dubletten (Rückfrage, bevorzugte Bibliothek), Sicherung des Index.
- **Zotero und Export** – Verbindung, Schreibzugriff, Notizen für Auswertungsblätter, Ziel der Beleg-Links in Exporten des Forschungsstands (PDF-Seite oder Zotero-Eintrag), Zitierstil für Exporte (aus den in Zotero installierten Stilen, mit Musterbeleg), Kennzeichnung ohne Seitenzahl, Zotero-Plugin.
- **Sprache** – Sprache der Oberfläche und der Hilfe; Sprache der KI-Ausgaben (Antworten, Auswertungsblätter, Forschungsstand). „Wie die Frage“ antwortet in der Sprache der Frage. Wörtliche Zitate bleiben immer in der Originalsprache.
- **Darstellung** – System, Hell, Grau oder Dunkel. Die Titelleiste des Programmfensters passt sich an: unter Windows 11 in den Farben der Oberfläche, unter Windows 10 hell oder dunkel.
- **Experten** – Presets sowie alle Such-, Antwort-, Forschungsstand-, Zerlegungs- und Einlesewerte. Geänderte Werte sind markiert und lassen sich einzeln zurücksetzen. Eigene Presets lassen sich als Datei weitergeben.
- **Programm & Daten** – Updates, Kennzahlen des Index, Speicherorte (Daten, Einstellungen, Protokolle) und Beenden.

Das Programmfenster passt sich beim ersten Start dem Bildschirm an und merkt sich danach Grösse und Position. Auf sehr breiten Bildschirmen wird der Inhalt höchstens im Format 16:9 dargestellt und mittig angeordnet.

### Updates

Ist eine Update-Quelle eingetragen, sucht ZotLLM beim Start nach neuen Versionen. **Jetzt aktualisieren** lädt den Installer, beendet ZotLLM und startet es nach der Installation neu. Einstellungen, Index, Korpora und Schlüssel bleiben erhalten.

## Datenschutz und Daten

- Index, Projekte, Chats und Forschungsstände liegen lokal im Datenordner (Einstellungen → Programm & Daten). Er liegt bewusst nicht in einem synchronisierten Ordner.
- Mit einem lokalen Embedding-Modell (eingebaut oder Ollama) verlassen die Texte den Rechner beim Indexieren nicht. Mit einem Cloud-Embedding gehen alle Textabschnitte an den Anbieter. Die eingebaute Laufzeit nimmt nur Anfragen von ZotLLM an (zufälliger Schlüssel, nur 127.0.0.1) und greift nie aufs Netz zu; Hugging Face wird nur für Downloads per Knopf und für die Namenssuche angefragt.
- Beim Fragen und beim Forschungsstand gehen die gefundenen Textstellen bzw. die Texte der Auswahl an den Anbieter des Sprachmodells. Mit Ollama als Sprachmodell bleibt alles lokal.
- **Suchen** arbeitet ganz ohne Sprachmodell.
- API-Schlüssel liegen verschlüsselt im Anmeldeinformationsspeicher des Betriebssystems.
- ZotLLM verändert Zotero nur mit Schreibzugriff und nur auf Ihren Auftrag: Notizen für Auswertungsblätter, Sammlungen für den Forschungsstand.

## Probleme lösen

### Zotero ist nicht erreichbar

Läuft Zotero, und ist die lokale Schnittstelle eingeschaltet (Kapitel Einrichtung)? Die Statusleiste zeigt den Zustand; **Prüfen** unter Einstellungen → Zotero und Export fragt neu ab.

### Schreibzugriff: Es erscheint kein Dialog

Der Dialog von Zotero liegt oft hinter anderen Fenstern. In der Taskleiste auf Zotero klicken. Erscheint nach der Freigabe weiterhin „nicht freigegeben“, die Seite mit **Prüfen** aktualisieren; gilt die Freigabe nur für diese Sitzung, steht das daneben – beim nächsten Mal in Zotero „Entscheidung merken“ wählen.

### Ollama läuft nicht

Ollama von ollama.com installieren und starten, dann unter Einstellungen → Embedding **Erneut prüfen**. Fehlt das Modell, bietet ZotLLM den Download an.

### Die eingebaute Laufzeit startet nicht

Meldet ZotLLM, dass die Laufzeit oder eine ihrer Dateien fehlt, ZotLLM neu installieren. Virenscanner entfernen gelegentlich Programmdateien, die sie nicht kennen (Fehlalarm); dann den Ordner von ZotLLM im Virenscanner als vertrauenswürdig eintragen. Bricht das Laden eines Modells ab, steht die Ursache im Protokoll `llama-<Modell>.log` (Einstellungen → Programm & Daten → Protokolle). Bei eigenen Modellen ist oft die Bauweise nicht unterstützt.

### Indexierung ist langsam

Lokale Modelle sind auf Laptops langsam; die Zeit pro 100 Seiten zeigt der Modellkatalog. Möglichkeiten: ein schnelleres Modell aus der Gruppe *Schnell* wählen, in Etappen nachts indexieren, weniger Texte pro Korpus wählen oder ein Cloud-Embedding verwenden. Mit Ollama lässt sich auch eine Grafikkarte nutzen (Einstellungen → Embedding → Ollama → Gerät).

### Antworten finden nichts

Prüfen Sie, ob die gewählten Korpora indexierte Texte haben (Index → Korpora), und ob sie mit dem aktiven Embedding-Modell schon eingebettet sind – nach einem Modellwechsel zeigt ein Hinweis über den Antworten, wie viele Texte erst durchsuchbar sind, mit **Jetzt einbetten** und **Zurück zu …**. Mehrfachsuche und mehr Textstellen (Preset „gründlich“) helfen bei breiten Fragen.

### Knöpfe reagieren nicht

Zeigt eine Ansicht einen Anzeigefehler, **Neu laden** wählen. Hilft das nicht, ZotLLM beenden und neu starten. Die Protokolle (Einstellungen → Programm & Daten) helfen bei der Fehlersuche.

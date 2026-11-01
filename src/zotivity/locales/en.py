"""English messages of the service. Keys: German text or template with {placeholders} (see zotivity.i18n)."""

MESSAGES: dict[str, str] = {
    # -- Einrichtung -----------------------------------------------------------------------------
    "Zotero verbinden": "Connect Zotero",
    "Verbunden mit Zotero": "Connected to Zotero",
    "Verbunden mit Zotero {v}": "Connected to Zotero {v}",
    "Zotero läuft nicht.": "Zotero is not running.",
    "Sprachmodell und API-Schlüssel": "Language model and API key",
    "Für {p} ist kein API-Schlüssel gespeichert.": "No API key is stored for {p}.",
    "Embedding-Modell": "Embedding model",
    "Wissenskorpus anlegen": "Create a knowledge corpus",
    "Wähle Sammlungen aus deiner Zotero-Bibliothek, die durchsucht werden sollen.":
        "Choose the collections from your Zotero library that should be searched.",
    "Texte indexieren": "Index texts",
    "{a} von {b} Dokumenten indexiert": "{a} of {b} documents indexed",
    "{a} von {b} Dokumenten mit {m} durchsuchbar": "{a} of {b} documents searchable with {m}",
    "1 Text einzubetten": "1 text to embed",
    "{n} Texte einzubetten": "{n} texts to embed",
    "1 Text zu aktualisieren": "1 text to refresh",
    "{n} Texte zu aktualisieren": "{n} texts to refresh",
    "Nach dem Anlegen eines Korpus.": "After creating a corpus.",
    "Schreibzugriff auf Zotero": "Write access to Zotero",
    "Für Auswertungsblätter als Notizen und Sammlungen aus dem Forschungsstand.":
        "For evaluation sheets as notes and collections from the literature review.",
    "Zotero-Plugin": "Zotero plugin",
    "Rechtsklick-Menüs in Zotero und Start von Zotivity mit Zotero.":
        "Right-click menus in Zotero and starting Zotivity with Zotero.",
    "Version {v} ist veraltet – bitte neu installieren (u. a. für genaue Word-Belege).":
        "Version {v} is outdated – please reinstall (e.g. for exact Word citations).",
    "Das Plugin heisst jetzt Zotivity: in Zotero das alte Plugin „ZotLLM“ entfernen und das neue installieren.":
        "The plugin is now called Zotivity: remove the old “ZotLLM” plugin in Zotero and install the new one.",

    # -- Aufträge: Titel ---------------------------------------------------------------------------
    "Ollama: {model} herunterladen": "Ollama: download {model}",
    "Suchkatalog abgleichen": "Synchronising search catalogue",
    "Indexierung aller Korpora": "Indexing all corpora",
    "Indexierung: {name}": "Indexing: {name}",
    # gleich lange Vorlagen: die spezifischere zuerst (die Sortierung ist stabil)
    "Einbetten für {model}: alle Korpora": "Embedding for {model}: all corpora",
    "Einbetten für {model}: {name}": "Embedding for {model}: {name}",
    "Indexierung ({n} Sammlung(en))": "Indexing ({n} collection(s))",
    "Indexierung ({n} Einträge)": "Indexing ({n} items)",
    "Hintergrund-Indexierung": "Background indexing",
    "Forschungsstand: Suchstrategie": "Literature review: search strategy",
    "Forschungsstand: Texte finden": "Literature review: find texts",
    "Forschungsstand: Auswertungsblätter": "Literature review: evaluation sheets",
    "Forschungsstand: Gliederung": "Literature review: outline",
    "Forschungsstand: Schreiben": "Literature review: writing",
    "Forschungsstand: Abschnitt neu schreiben": "Literature review: rewrite section",
    "Auswertungsblätter für {n} Texte": "Evaluation sheets for {n} texts",

    # -- Aufträge: Phasen --------------------------------------------------------------------------
    "Download": "Download",
    "Abgleich": "Synchronisation",
    "Suchkatalog": "Search catalogue",
    "Fertig": "Done",
    "Warte auf Embedding-Dienst": "Waiting for the embedding service",
    "Sicherung": "Backup",
    "Abgleich mit Zotero": "Synchronising with Zotero",
    "Vorbereitung": "Preparation",
    "Indexierung": "Indexing",
    "Einbetten": "Embedding",
    "Abschluss": "Finishing",
    "Suchstrategie": "Search strategy",
    "Suche": "Search",
    "Vorauswahl": "Pre-selection",
    "Auswertungsblätter": "Evaluation sheets",
    "Gliederung": "Outline",
    "Schreiben": "Writing",
    "Abgebrochen": "Cancelled",
    "Es läuft bereits ein Auftrag: {title}": "A task is already running: {title}",

    # -- Indexierung ---------------------------------------------------------------------------------
    "{name}: Sammlungen": "{name}: collections",
    "{name}: alle Einträge laden": "{name}: loading all items",
    "{name}: geänderte Einträge seit Version {since}": "{name}: changed items since version {since}",
    "{name}: {n} neue Einträge laden": "{name}: loading {n} new items",
    "Meine Bibliothek": "My library",
    "ganze Bibliothek": "whole library",
    # Kurzbelege ohne Angaben (rag/sources.author_year)
    "o. A. o. J.": "n.a. n.d.",
    "o. A. {year}": "n.a. {year}",
    "{who} o. J.": "{who} n.d.",
    "Meine Bibliothek ({i} von {n})": "My library ({i} of {n})",
    "{name} ({i} von {n})": "{name} ({i} of {n})",
    "{n} Bibliotheken abgeglichen": "{n} libraries synchronised",
    "{e} – neuer Versuch in {s} s (wartet seit {w} s)": "{e} – retrying in {s} s (waiting for {w} s)",
    "Index wird gesichert …": "Backing up index …",
    "Einträge werden abgeglichen …": "Synchronising items …",
    "Embedding-Modell wird geladen …": "Loading embedding model …",
    "{n} Dokumente zu verarbeiten": "{n} documents to process",
    "Alle Dokumente sind aktuell": "All documents are up to date",
    "Text wird gelesen": "Reading text",
    "Abschnitte werden eingebettet": "Embedding passages",
    "fertig": "done",
    "Abstracts und übrige Abschnitte": "Abstracts and remaining passages",
    "{n} übrige Abschnitte": "{n} remaining passages",
    "Abstracts von Einträgen ohne Volltext": "Abstracts of items without full text",
    "{n} Abstracts": "{n} abstracts",
    "{a} Texte zu lesen, {b} Texte nur für {m} einzubetten": "{a} texts to read, {b} texts only to embed for {m}",
    "Index ist aktuell": "Index is up to date",
    "Zeitfenster beendet nach {i} Texten – Fortsetzung im nächsten Zeitfenster":
        "Time window ended after {i} texts – continuing in the next time window",
    "Etappe beendet: {a} Texte verarbeitet, {b} folgen im nächsten Lauf":
        "Stage finished: {a} texts processed, {b} follow in the next run",
    "Kein Abgleich: {e}": "No synchronisation: {e}",
    "Nichts zu indexieren: Lege unter „Wissenskorpora“ einen Korpus an und wähle Sammlungen oder ganze Bibliotheken aus.":
        "Nothing to index: create a corpus under “Knowledge corpora” and choose collections or whole libraries.",
    "Die gewählten Sammlungen enthalten (noch) keine Einträge – ist Zotero geöffnet?":
        "The selected collections contain no items (yet) – is Zotero open?",
    "Zu wenig Speicherplatz auf dem Laufwerk von {folder}: frei {free} GB, benötigt etwa {need} GB für {n} Texte (inkl. Sicherung).":
        "Not enough disk space on the drive of {folder}: {free} GB free, about {need} GB needed for {n} texts (incl. backup).",
    "Es läuft bereits eine Indexierung.": "Indexing is already running.",
    "Das Embedding-Modell wurde während des Laufs gewechselt – Lauf beendet. Bereits Verarbeitetes bleibt erhalten; der nächste Lauf arbeitet mit dem neuen Modell.":
        "The embedding model was switched during the run – run ended. Work already done is kept; the next run uses the new model.",
    "Dieser Auftrag wartet nicht mehr (schon gestartet oder entfernt).":
        "This task is no longer waiting (already started or removed).",
    "Ungültige Auswahl – die Dubletten haben sich inzwischen geändert.":
        "Invalid choice – the duplicates have changed in the meantime.",
    "Keine Einträge ausgewählt.": "No items selected.",
    "Höchstens 2000 Einträge auf einmal.": "At most 2000 items at a time.",
    "Der Export ist abgelaufen – bitte erneut speichern.": "The export has expired – please save again.",
    "Keiner der gewählten Einträge liegt in dieser Bibliothek.": "None of the selected items is in this library.",
    "Bitte eine Sammlung wählen oder einen Namen für eine neue angeben.":
        "Please choose a collection or enter a name for a new one.",
    "Embedding-Dienst nicht verfügbar: {e}": "Embedding service not available: {e}",
    "Datei nicht lesbar: {e}": "File not readable: {e}",
    "Datei nicht vorhanden (nicht synchronisiert?)": "File not present (not synchronised?)",
    "Kein Dateipfad": "No file path",
    "Zotero-Volltext verwendet (ohne Seitenzahlen)": "Zotero full text used (without page numbers)",
    "Unbekannter Fehler": "Unknown error",
    "Kein Text gefunden": "No text found",
    "Schnappschuss nicht nötig – der Eintrag hat eine PDF": "Snapshot not needed – the item has a PDF",
    "Scan ohne Textebene – Texterkennung (OCR) nötig": "Scan without text layer – text recognition (OCR) needed",
    "Zotero ist nicht erreichbar oder die lokale API ist deaktiviert.":
        "Zotero cannot be reached or the local API is disabled.",
    "Passwortgeschütztes Dokument": "Password-protected document",
    "Nur die ersten {a} von {b} Seiten indexiert": "Only the first {a} of {b} pages indexed",
    "Texterkennung nicht möglich: {e}": "Text recognition not possible: {e}",
    "Nicht unterstützter Dateityp: {t}": "Unsupported file type: {t}",
    "Lese-Prozess nicht erreichbar": "Reader process not reachable",
    "Datei hat das Lesen zum Absturz gebracht (Code {c})": "File crashed the reader (code {c})",
    "Lesen nach {s} s abgebrochen (Zeitlimit)": "Reading aborted after {s} s (time limit)",

    # -- Forschungsstand ---------------------------------------------------------------------------
    "Formuliere Suchanfragen …": "Phrasing search queries …",
    "{n} Suchanfragen vorgeschlagen": "{n} search queries proposed",
    "{n} Suchanfragen – Treffer je Dokument zählen …": "{n} search queries – counting hits per document …",
    "{a} von {b} geprüft": "{a} of {b} checked",
    "{a} Texte vorgeschlagen, {b} weitere zur Prüfung": "{a} texts suggested, {b} more to check",
    "{a} Blätter zu erstellen ({b} vorhanden)": "{a} sheets to create ({b} available)",
    "{a} Blätter erstellt, {b} Notizen in Zotero": "{a} sheets created, {b} notes in Zotero",
    "Gliederung aus {n} Auswertungsblättern …": "Outline from {n} evaluation sheets …",
    "{n} Abschnitte geplant": "{n} sections planned",
    "Abschnitt: {heading}": "Section: {heading}",
    "Seiten der Belege suchen": "Finding the pages of the citations",
    "{w} Wörter geschrieben; {u} unbekannte Belege, {q} ungeprüfte Zitate":
        "{w} words written; {u} unknown citations, {q} unverified quotations",
    "{w} Wörter geschrieben; {u} unbekannte Belege, {q} ungeprüfte Zitate; {n} unvollständige Abschnitte":
        "{w} words written; {u} unknown citations, {q} unverified quotations; {n} incomplete sections",
    "Diesen Abschnitt gibt es nicht (mehr) – bitte den ganzen Text neu schreiben.":
        "This section no longer exists – please rewrite the whole text.",
    "Abschnitt nicht gefunden": "Section not found",
    # -- Recherche: Einrichtung, Schlüssel, Volltexte -----------------------------------------------
    "Schlüssel für Datenbanken": "Keys for databases",
    "Alle hinterlegt.": "All stored.",
    "Für die Recherche, soweit nötig. Noch ohne Schlüssel: {names}": "For database search, where needed. No key yet: {names}",
    "Für OpenAlex nötig (kostenloses Konto).": "Required for OpenAlex (free account).",
    "Optional: 10 statt 3 Anfragen pro Sekunde an PubMed.": "Optional: 10 instead of 3 requests per second to PubMed.",
    "Optional: ohne Schlüssel ist der Dienst oft überlastet.": "Optional: without a key the service is often overloaded.",
    "Nur nötig, wenn eine Recherche über zotero.org statt über Zotero auf diesem Computer schreibt.":
        "Only needed if a database search writes through zotero.org instead of Zotero on this computer.",
    "Unbekannter Schlüssel": "Unknown key",
    "Kein Schlüssel für die Zotero-Web-API gespeichert. Einstellungen → Zotero und Export, oder unter Ziel in Zotero „Zotero auf diesem Computer“ wählen.":
        "No key stored for the Zotero web API. Go to Settings → Zotero and export, or choose “Zotero on this computer” under Target in Zotero.",
    "Kein Sprachmodell eingerichtet: unter Einstellungen → Sprachmodelle einen Schlüssel speichern.":
        "No language model set up: save a key under Settings → Language models.",
    "Suchdatum bitte als JJJJ-MM-TT angeben.": "Please give the search date as YYYY-MM-DD.",
    "Unbekannter Stand: {status}": "Unknown status: {status}",
    "Nach Zotero wird nur nach ausdrücklicher Bestätigung geschrieben.": "Nothing is written to Zotero without explicit confirmation.",
    "Kein Schreibzugriff auf die Zielbibliothek (Schlüssel oder Freigabe fehlt).":
        "No write access to the target library (key or permission missing).",
    "Für einen Vorschlag braucht es eine Fragestellung oder Kurzbeschreibung (Projekt).":
        "A suggestion needs a research question or short description (Project).",
    "Kürzen": "Shortening",
    "Gekürzt: {a} → {b} Wörter": "Shortened: {a} → {b} words",
    "Gekürzt: {a} → {b} Wörter; unverändert: {list}": "Shortened: {a} → {b} words; unchanged: {list}",
    "Kein Abschnitt ist länger als geplant.": "No section is longer than planned.",
    "Ungültige Abschnitte": "Invalid sections",
    "Forschungsstand: Abschnitte kürzen": "Literature review: shorten sections",
    "Suchanfragen konnten nicht erzeugt werden: {e}": "Search queries could not be generated: {e}",
    "Vorauswahl-Fehler: {e}": "Pre-selection error: {e}",
    "Notizen nicht gespeichert: Schreibzugriff auf Zotero nicht freigegeben.":
        "Notes not saved: write access to Zotero not allowed.",
    "Notiz nicht gespeichert: {e}": "Note not saved: {e}",
    "Keine Texte ausgewählt.": "No texts selected.",
    "Keine Auswertungsblätter vorhanden – zuerst Schritt 2 ausführen.": "No evaluation sheets yet – run step 2 first.",
    "Die Gliederung konnte nicht erstellt werden.": "The outline could not be created.",
    "Ungültige Gliederung": "Invalid outline",
    "Zuerst die Gliederung erstellen.": "Create the outline first.",
    "Ungültige Suchanfragen": "Invalid search queries",
    "Höchstens 80 Suchanfragen.": "At most 80 search queries.",
    "Bitte einen Titel angeben.": "Please enter a title.",
    "Für diesen Forschungsstand wurde noch keine Zotero-Sammlung angelegt.":
        "No Zotero collection has been created for this literature review yet.",
    "Ungültiges Auswertungsblatt": "Invalid evaluation sheet",
    "Kein Auswertungsblatt für diesen Text": "No evaluation sheet for this text",
    "Forschungsstand: Auswertungsblatt neu erstellen": "Literature review: recreate evaluation sheet",
    "Für diesen Text gibt es noch kein Auswertungsblatt.": "There is no evaluation sheet for this text yet.",
    "Auswertungsblatt nicht neu erstellt: {e}": "Evaluation sheet not recreated: {e}",
    "Auswertungsblatt neu erstellt": "Evaluation sheet recreated",
    "Auswertung fehlgeschlagen: {e}": "Evaluation failed: {e}",
    "nicht bewertet": "not rated",
    "Kein indexierter Text vorhanden": "No indexed text available",
    # Anhang des Exports (Sprache des Forschungsstands)
    "Anhang: Methode der Literatursuche": "Appendix: Literature search method",
    "Durchsucht: {what} (Zotero-Bibliothek, hybride Bedeutungs- und Stichwortsuche, Zotivity)":
        "Searched: {what} (Zotero library, hybrid semantic and keyword search, Zotivity)",
    "alle indexierten Texte": "all indexed texts",
    "Forschungsfrage: {q}": "Research question: {q}",
    "Suche am: {when}; {n} Kandidaten, davon {k} einbezogen (Vorauswahl durch Sprachmodell, geprüft und bestätigt)":
        "Search on: {when}; {n} candidates, {k} of them included (pre-selected by language model, checked and confirmed)",
    "Suchanfrage": "Search query",
    "gefundene Texte": "texts found",
    "nur durch diese Anfrage": "only by this query",

    # -- Fragen ------------------------------------------------------------------------------------
    "Durchsuche die Bibliothek …": "Searching the library …",
    "Recherche-Runde {n}: prüfe Lücken …": "Research round {n}: checking for gaps …",
    "Recherche-Runde abgebrochen: {e}": "Research round aborted: {e}",
    "Mehrfachsuche nicht möglich ({e}); suche nur mit der Frage.":
        "Multi-query not possible ({e}); searching with the question only.",
    "Schreibe Antwort mit {model} …": "Writing answer with {model} …",
    "Antwort wurde wegen der Längenbegrenzung abgeschnitten.": "The answer was cut off because of the length limit.",
    "Die Antwort brach ab, weil sie eine längere Passage wörtlich wiedergab (Sperre des Anbieters). Nochmals fragen, z. B. mit der Bitte um kürzere Zitate.":
        "The answer stopped because it reproduced a longer passage verbatim (blocked by the provider). Ask again, e.g. asking for shorter quotations.",
    "Zu dieser Frage habe ich in den indexierten Texten nichts gefunden. Prüfe den gewählten Wissenskorpus und ob seine Texte indexiert sind.":
        "I found nothing on this question in the indexed texts. Check the selected knowledge corpus and whether its texts are indexed.",
    "Für Antworten ist {p} eingestellt, aber dafür ist kein API-Schlüssel gespeichert.{hint}":
        "{p} is set for answers, but no API key is stored for it.{hint}",
    "Gespeichert ist ein Schlüssel für {names} – unter Einstellungen → Sprachmodelle diesen Anbieter wählen.":
        "A key is stored for {names} – choose this provider under Settings → Language models.",
    "Unter Einstellungen → Sprachmodelle einen Schlüssel eintragen.": "Enter a key under Settings → Language models.",

    # -- Embedding und Sprachmodelle ------------------------------------------------------------
    "Kein OpenAI-API-Schlüssel gespeichert.": "No OpenAI API key stored.",
    "Für einen OpenAI-kompatiblen Server muss die Basis-URL gesetzt sein.":
        "An OpenAI-compatible server requires the base URL to be set.",
    "API-Schlüssel ungültig.": "Invalid API key.",
    "Embedding-Modell „{m}“ nicht gefunden.": "Embedding model “{m}” not found.",
    "Embedding-Dienst vorübergehend nicht verfügbar: {e}": "Embedding service temporarily unavailable: {e}",
    "Embedding-Fehler: {e}": "Embedding error: {e}",
    "Kein Gemini-API-Schlüssel gespeichert.": "No Gemini API key stored.",
    "Gemini-Embedding-Fehler: {e}": "Gemini embedding error: {e}",
    'sentence-transformers ist nicht installiert: pip install "zotivity[local]"':
        'sentence-transformers is not installed: pip install "zotivity[local]"',
    "Ollama ist nicht erreichbar. Läuft Ollama?": "Ollama cannot be reached. Is Ollama running?",
    "Modell „{m}“ ist in Ollama nicht vorhanden. In den Einstellungen herunterladen oder: ollama pull {p}":
        "Model “{m}” is not available in Ollama. Download it in the settings or: ollama pull {p}",
    "Ollama-Fehler {code}: {msg}": "Ollama error {code}: {msg}",
    "Kein Anthropic-API-Schlüssel gespeichert.": "No Anthropic API key stored.",
    "Anthropic: keine Berechtigung ({e}).": "Anthropic: no permission ({e}).",
    "Anthropic: Ratenlimit erreicht – bitte kurz warten.": "Anthropic: rate limit reached – please wait a moment.",
    "Anthropic: keine Verbindung.": "Anthropic: no connection.",
    "Anthropic-Fehler {code}: {e}": "Anthropic error {code}: {e}",
    "Claude hat die Anfrage aus Sicherheitsgründen abgelehnt": "Claude declined the request for safety reasons",
    "Antwort enthält kein gültiges JSON": "The response contains no valid JSON",
    "Gemini hat die Antwort aus Sicherheitsgründen blockiert.": "Gemini blocked the response for safety reasons.",
    "Gemini: API-Schlüssel ungültig oder ohne Berechtigung.": "Gemini: API key invalid or without permission.",
    "Gemini: Ratenlimit erreicht – bitte kurz warten.": "Gemini: rate limit reached – please wait a moment.",
    "Gemini-Fehler {code}: {e}": "Gemini error {code}: {e}",
    "Kein {p}-API-Schlüssel gespeichert.": "No {p} API key stored.",
    "{p}: API-Schlüssel ungültig.": "{p}: invalid API key.",
    "{p}: Modell „{m}“ nicht gefunden.": "{p}: model “{m}” not found.",
    "{p}: Ratenlimit oder Guthaben erschöpft – {e}": "{p}: rate limit or credit exhausted – {e}",
    "{p}: keine Verbindung ({url}).": "{p}: no connection ({url}).",
    "{p}: ungültige Anfrage – {e}": "{p}: invalid request – {e}",
    "{p}-Fehler: {e}": "{p} error: {e}",
    "Für den Cross-Encoder wird sentence-transformers benötigt: pip install \"zotivity[local]\"":
        "The cross-encoder requires sentence-transformers: pip install \"zotivity[local]\"",

    # -- Zotero ------------------------------------------------------------------------------------
    "Zotero ist nicht erreichbar. Läuft Zotero?": "Zotero cannot be reached. Is Zotero running?",
    "Zotero ist nicht erreichbar.": "Zotero cannot be reached.",
    "Die lokale API ist in Zotero deaktiviert. Zotero → Einstellungen → Erweitert → „Anderen Anwendungen auf diesem Computer erlauben, mit Zotero zu kommunizieren“ aktivieren.":
        "The local API is disabled in Zotero. Enable Zotero → Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”.",
    "Nicht gefunden: {url}": "Not found: {url}",
    "Zotero-Fehler {code}: {msg}": "Zotero error {code}: {msg}",
    "Zotero-Server-ID unbekannt.": "Zotero server ID unknown.",
    "Zotero-Instanz hat gewechselt – bitte erneut versuchen.": "The Zotero instance has changed – please try again.",
    "Zu viele Autorisierungsanfragen – bitte später erneut versuchen.": "Too many authorisation requests – please try again later.",
    "Schreibzugriff auf Zotero ist noch nicht freigegeben.": "Write access to Zotero has not been allowed yet.",
    "Zotero hat den Schlüssel abgelehnt – bitte erneut freigeben.": "Zotero rejected the key – please allow access again.",
    "Zotero-Schreibfehler {code}: {msg}": "Zotero write error {code}: {msg}",
    "Notiz konnte nicht angelegt werden: {e}": "Note could not be created: {e}",
    "Sammlung konnte nicht angelegt werden: {e}": "Collection could not be created: {e}",

    # -- Programm, Projekte, Updates, Schlüssel ----------------------------------------------------
    "Kein sicherer Schlüsselspeicher verfügbar ({b}). Unter Linux z. B. gnome-keyring installieren oder den Schlüssel als Umgebungsvariable setzen.":
        "No secure key store available ({b}). On Linux, e.g. install gnome-keyring or set the key as an environment variable.",
    "Leerer Schlüssel.": "Empty key.",
    "Löschen fehlgeschlagen: {e}": "Deletion failed: {e}",
    "Die Datei ist zu gross.": "The file is too large.",
    "Keine gültige Projektdatei (.zoty oder .zllm).": "Not a valid project file (.zoty or .zllm).",
    "Unbekanntes Dateiformat – stammt die Datei aus einer neueren Zotivity-Version?":
        "Unknown file format – does the file come from a newer Zotivity version?",
    "Update-Quellen müssen HTTPS oder ein lokaler bzw. Netzwerkpfad sein.":
        "Update sources must be HTTPS or a local or network path.",
    "Update-Quelle nicht gefunden: {s}": "Update source not found: {s}",
    "Update-Information konnte nicht gelesen werden: {e}": "Update information could not be read: {e}",
    "Kein Installer angegeben.": "No installer specified.",
    "Die Prüfsumme des Installers stimmt nicht. Update abgebrochen.": "The installer checksum does not match. Update aborted.",

    # -- Programmfenster ---------------------------------------------------------------------------
    "Es läuft noch:": "Still running:",
    "wartet": "waiting",
    "Ja – im Hintergrund weiterlaufen lassen; Zotivity beendet sich danach von selbst.":
        "Yes – keep running in the background; Zotivity quits by itself afterwards.",
    "Nein – abbrechen und Zotivity beenden.": "No – cancel and quit Zotivity.",
    "Abbrechen – Fenster offen lassen.": "Cancel – keep the window open.",
    "Zotivity konnte nicht starten:": "Zotivity could not start:",
    "Der Dienst konnte nicht starten – ist Port {port} belegt?": "The service could not start – is port {port} in use?",

    # -- Antworten der Schnittstelle --------------------------------------------------------------
    "Unbekannter Anbieter": "Unknown provider",
    "Der aktive Embedding-Raum kann nicht gelöscht werden.": "The active embedding space cannot be deleted.",
    "Modellname fehlt": "Model name missing",
    "Wissenskorpus nicht gefunden": "Knowledge corpus not found",
    "Bitte einen Namen für den Wissenskorpus angeben.": "Please enter a name for the knowledge corpus.",
    "Es gibt bereits einen Wissenskorpus „{name}“.": "A knowledge corpus “{name}” already exists.",
    "Ungültige Quellen": "Invalid sources",
    "Projekt nicht gefunden": "Project not found",
    "Bitte einen Namen für das Projekt angeben.": "Please enter a name for the project.",
    "Es gibt bereits ein Projekt „{name}“.": "A project “{name}” already exists.",
    "Das letzte Projekt kann nicht gelöscht werden.": "The last project cannot be deleted.",
    "Das letzte offene Projekt kann nicht gelöscht werden.": "The last open project cannot be deleted.",
    "Ungültige Reihenfolge": "Invalid order",
    "Das letzte offene Projekt kann nicht archiviert werden.": "The last open project cannot be archived.",
    "Das Projekt ist archiviert. Erst aus dem Archiv holen, dann öffnen.":
        "The project is archived. Restore it from the archive first, then open it.",
    "Preset nicht gefunden": "Preset not found",
    "Bitte einen Namen für das Preset angeben.": "Please enter a name for the preset.",
    "Ungültige Werte im Preset": "Invalid values in the preset",
    "Nur eigene Presets können gelöscht werden.": "Only custom presets can be deleted.",
    "Der Wissenskorpus enthält noch keine Sammlungen.": "The knowledge corpus does not contain any collections yet.",
    "Während einer Indexierung wird am Ende automatisch gesichert.": "During indexing, a backup is made automatically at the end.",
    "Sicherung fehlgeschlagen – Details im Protokoll.": "Backup failed – details in the log.",
    "Auftrag nicht gefunden": "Task not found",
    "Suchbegriff fehlt": "Search term missing",
    "Frage fehlt": "Question missing",
    "Titel fehlt": "Title missing",
    "Forschungsfrage fehlt": "Research question missing",
    "Forschungsstand nicht gefunden": "Literature review not found",
    "Nicht gefunden": "Not found",
    "Bitte zuerst die laufende Indexierung abbrechen oder abwarten.": "Please cancel or wait for the running indexing first.",
    "Download fehlgeschlagen: {e}": "Download failed: {e}",
    "Unbekannte Art": "Unknown kind",
    "Unbekanntes Format": "Unknown format",
    "Header X-Zotivity fehlt": "Header X-Zotivity missing",

    # -- Eingebaute Embedding-Modelle (llama.cpp) ---------------------------------------------------------
    "Download: {name}": "Download: {name}",
    "Kurztest: {name}": "Short test: {name}",
    "Index übernehmen": "Take over index",
    "Kurztest": "Short test",
    "Vergleich": "Comparison",
    "Übernahme": "Takeover",
    "Download startet …": "Download starting …",
    "Download wird fortgesetzt …": "Resuming download …",
    "Download läuft …": "Downloading …",
    "Prüfsumme wird kontrolliert …": "Checking checksum …",
    "Modell wird geladen …": "Loading model …",
    "Tempo wird gemessen …": "Measuring speed …",
    "Suchqualität wird geprüft …": "Checking search quality …",
    "Stichprobe wird neu eingebettet …": "Re-embedding a sample …",
    "Index wird übernommen …": "Taking over index …",
    "„{name}“ ist noch nicht heruntergeladen – unter Einstellungen → Embedding herunterladen.":
        "“{name}” has not been downloaded yet – download it under Settings → Embedding.",
    "Das Modell „{model}“ steht nicht im Modellkatalog.": "The model “{model}” is not in the model catalog.",
    "Die eingebaute Laufzeit (llama.cpp) fehlt in dieser Installation. Bitte Zotivity neu installieren oder einen "
    "anderen Embedding-Anbieter wählen.":
        "The built-in runtime (llama.cpp) is missing from this installation. Please reinstall Zotivity or choose "
        "another embedding provider.",
    "Die eingebaute Laufzeit konnte nicht starten: {e}": "The built-in runtime could not start: {e}",
    "Eine Programmdatei der eingebauten Laufzeit fehlt. Bitte Zotivity neu installieren (Virenscanner prüfen, falls "
    "er Dateien entfernt hat).":
        "A program file of the built-in runtime is missing. Please reinstall Zotivity (check your virus scanner in "
        "case it removed files).",
    "Die eingebaute Laufzeit ist beim Laden des Modells abgebrochen: {detail}":
        "The built-in runtime stopped while loading the model: {detail}",
    "Die eingebaute Laufzeit hat das Modell nicht rechtzeitig geladen.":
        "The built-in runtime did not load the model in time.",
    "Die eingebaute Laufzeit antwortet nicht.": "The built-in runtime is not responding.",
    "Fehler der eingebauten Laufzeit ({status}): {msg}": "Error of the built-in runtime ({status}): {msg}",
    "Ein Textabschnitt ist zu lang für das Modell ({n} Tokens).": "A passage is too long for the model ({n} tokens).",
    "Zu wenig Speicherplatz: frei {a} GB, benötigt {b} GB.": "Not enough disk space: {a} GB free, {b} GB needed.",
    "Download fehlgeschlagen (HTTP {status}).": "Download failed (HTTP {status}).",
    "Download unterbrochen ({e}). Erneut starten setzt ihn fort.": "Download interrupted ({e}). Starting it again resumes it.",
    "Die heruntergeladene Datei stimmt nicht mit der Prüfsumme überein und wurde verworfen.":
        "The downloaded file does not match its checksum and was discarded.",
    "Die Datei ist kein gültiges GGUF-Modell: {e}": "The file is not a valid GGUF model: {e}",
    "Hugging Face ist nicht erreichbar – besteht eine Internetverbindung?":
        "Hugging Face cannot be reached – is there an internet connection?",
    "Dieses Modell gibt es auf Hugging Face nicht (oder es ist privat).":
        "This model does not exist on Hugging Face (or it is private).",
    "Hugging Face meldet Fehler {status}.": "Hugging Face reports error {status}.",
    "Diese Datei gibt es im Repository nicht.": "This file does not exist in the repository.",
    "Dieses Modell verlangt auf Hugging Face eine Anmeldung oder Lizenzbestätigung – das unterstützt Zotivity nicht.":
        "This model requires a login or licence confirmation on Hugging Face – Zotivity does not support that.",
    "Das ist ein Sprachmodell, kein Embedding-Modell.": "This is a language model, not an embedding model.",
    "Dieses Modell steht bereits im Katalog.": "This model is already in the catalog.",
    "Eigenes Modell nicht gefunden.": "Own model not found.",
    "Der Modellkatalog verlangt eine neuere Version von Zotivity.": "The model catalog requires a newer version of Zotivity.",
    "Katalog ungültig: {detail}": "Invalid catalog: {detail}",
    "Modellkatalog nicht erreichbar: {e}": "Model catalog not reachable: {e}",
    "Modell nicht im Katalog": "Model not in the catalog",
    "Das Modell ist bereits heruntergeladen.": "The model has already been downloaded.",
    "Das Modell ist noch nicht heruntergeladen.": "The model has not been downloaded yet.",
    "Das aktive Modell kann nicht gelöscht werden – zuerst ein anderes wählen.":
        "The active model cannot be deleted – choose another one first.",
    "Diese Vektorlänge unterstützt das Modell nicht.": "The model does not support this vector length.",
    "Dieser Index lässt sich nicht übernehmen.": "This index cannot be taken over.",
    "Bitte warten, bis die Indexierung beendet ist.": "Please wait until indexing has finished.",
    "Keine Adresse für den Modellkatalog eingestellt.": "No address set for the model catalog.",
    "Ungültiger Name eines Repositorys": "Invalid repository name",
    "Bitte zwei verschiedene Modelle wählen.": "Please choose two different models.",
    "Für eines der Modelle gibt es keinen Index.": "There is no index for one of the models.",
    "Der Index enthält keine Vektoren.": "The index contains no vectors.",
    "Die Dimension der Vektoren unterscheidet sich.": "The vector dimension differs.",

    # -- Word und OpenDocument (0.9.0) ------------------------------------------------------------
    "Keine Word-Datei (word/document.xml fehlt)": "Not a Word file (word/document.xml is missing)",
    "Keine OpenDocument-Datei (content.xml fehlt)": "Not an OpenDocument file (content.xml is missing)",
    "{name} ist zu gross ({mb} MB entpackt)": "{name} is too large ({mb} MB unpacked)",

    # -- CSL-Editor (1.0.0) -----------------------------------------------------------------------
    "Der Stil ist zu gross.": "The style is too large.",
    "Kein gültiges XML: {e}": "Not valid XML: {e}",
    "Keine CSL-Datei: Das Wurzelelement muss <style> (CSL 1.0) sein.": "Not a CSL file: the root element must be <style> (CSL 1.0).",
    "Dem Stil fehlt der Abschnitt <info>.": "The style lacks the <info> section.",
    "Das Attribut version=\"1.0\" fehlt am Element <style>.": "The attribute version=\"1.0\" is missing on the <style> element.",
    "Der Stil hat keinen Titel.": "The style has no title.",
    "Dem Stil fehlt der Abschnitt <citation> (Belege im Text).": "The style lacks the <citation> section (in-text citations).",
    "Ungültiger Name des Stils.": "Invalid style name.",
    "Ungültiger Stilname.": "Invalid style name.",
    "zotero.org ist nicht erreichbar ({e}).": "zotero.org cannot be reached ({e}).",
    "Unerwartete Antwort von zotero.org.": "Unexpected response from zotero.org.",
    "zotero.org antwortet mit Fehler {code}.": "zotero.org responds with error {code}.",
    "Der Elternstil liegt nicht auf zotero.org.": "The parent style is not on zotero.org.",
    "Diesen Stil gibt es auf zotero.org nicht.": "This style does not exist on zotero.org.",
    "Für diesen abhängigen Stil fehlt der Elternstil.": "The parent style of this dependent style is missing.",
    "Stil nicht gefunden": "Style not found",
    "Version nicht gefunden": "Version not found",
    "Für das direkte Installieren braucht es das Zotivity-Plugin ab Version 1.1.0.":
        "Installing directly requires the Zotivity plugin version 1.1.0 or later.",
    "Zotero konnte den Stil nicht installieren: {detail}": "Zotero could not install the style: {detail}",
}

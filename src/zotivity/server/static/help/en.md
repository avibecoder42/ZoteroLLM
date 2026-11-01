# Zotivity – Manual

## Overview

Zotivity (formerly ZotLLM) enables comprehensive scholarly work with your own Zotero library, group libraries included: from searching subject databases through reading and asking about your texts to a checked literature review. It reads the PDFs and other texts, splits them into passages and makes them searchable by meaning and by keyword. Three ways of working build on this:

- **Search** – a fast search engine across all libraries, without any language model: titles, people, years, tags, abstracts and, if you like, the full text.
- **Ask** – questions in your own words; the language model answers only from the passages found, and every statement cites its source and page.
- **Literature review** – a guided process from the search strategy through an evaluation sheet per text to a checked synthesis with bibliography.

**Database search** can come first: a search in subject databases (PubMed, OpenAlex and others), with screening and handover of the selected literature to Zotero collections.

The navigation bar on the left has two parts. At the very top is the **Guide**, below it the views of the active **project** in the order of the workflow: Project, Database search, Corpora, Ask and Literature review – first find new literature, then decide what is read, then work with it. Set apart follows **Search**, a tool for any time. At the bottom are **CSL editor**, **Index**, **Help** and **Settings**; they apply to all projects. Above the menu, the project tile shows the active project; click it (or press **Ctrl+P**) to switch projects.

Zotivity is an independent project, not affiliated with Zotero or the Corporation for Digital Scholarship; “Zotero” is their registered trademark.

The status bar at the bottom shows whether Zotero can be reached, which language model answers, which embedding model searches and how many passages are searchable. Running tasks (indexing, synchronisation, literature review) appear on the right with their progress; the × cancels them.

Warning notices (brown background) can be hidden with the × at the top right. Notices about the current state – such as "Zotero cannot be reached" – reappear after the next program start; notices about the index reappear as soon as the situation changes (e.g. another embedding model or new texts).

### The usual workflow

The **Guide**, the top entry of the navigation bar, shows the workflow, with links into the views and the status in the active project:

1. **Create a project**
2. **Database search** (optional) – if you already have a collection in Zotero, go straight to step 3
3. **Create and index a corpus**
4. **Work with the corpora** – Ask and Literature review

The technical part belongs to Setup (see the chapter Setup).

### Keyboard shortcuts

- **Ctrl+1 … Ctrl+6** Project, Database search, Corpora, Ask, Literature review, Search
- **Ctrl+7** CSL editor, **Ctrl+8** Index, **Ctrl+,** Settings, **F1** Help
- **Ctrl+P** switch project
- In database search: **Alt+1 … Alt+9** switches the tab; for screening see the chapter Database search
- In the program window: **Ctrl + mouse wheel**, **pinch** on the touchpad or **Ctrl +/−** zooms the whole interface, **Ctrl+0** resets it
- **Esc** closes menus, previews and dialogs
- In input fields, **Enter** starts the search or sends the question; **Shift+Enter** inserts a new line in the question field.

> If a view ever shows a display error, click **Reload** in the message. The error is written to the log (Settings → Program & data → Logs).

### Side panels

The panels on the left and the panels on the right (Index, Database search) can be resized: drag their edge with the mouse. A double-click on the edge restores the default width; with the edge focused, the arrow keys ← → change the width. The chosen width is remembered. Panels on the right adapt to the screen until you drag them.

### Width and zoom

Reading text and forms keep a readable width and are centred; lists and tables (such as Pool or Search & import) use the full width, up to a limit on very wide screens. In the program window you can zoom the whole interface at the bottom right of the status bar; the value is kept across restarts.

### Closing the program

Closing the window quits Zotivity completely. If indexing, a catalog sync or a literature review is running, Zotivity asks first: if you wish, the job finishes invisibly and the program then quits by itself. With the Zotero plugin, Zotivity starts again invisibly in the background the next time Zotero starts or on a command from Zotero, and ends a few minutes after Zotero.

## Setup

Setup covers only the technical part and happens once per computer: Zotero, language model, embedding model and, if you like, write access, the plugin and keys for databases. On the first start Zotivity opens **Settings → Setup** for this; any step can be skipped and says what it is needed for. **Next: guide** leads to the workflow. After that, Zotivity always reopens the last open project in the view used last, even if Zotero is not running.

The checklist stays available under **Settings → Setup**. If something is missing later, the status bar or the place that needs it says so; if a language model or embedding model is missing, the Settings entry shows a dot. The **Guide** and the **Next step** line on the project page show how the work continues.

### Connecting Zotero

Zotivity reads the library through Zotero's local interface. It has to be switched on once:

1. Open Zotero and choose **Edit → Settings** (macOS: Zotero → Settings).
2. Open the **Advanced** pane.
3. Tick **"Allow other applications on this computer to communicate with Zotero"**.

Zotero must be open while Zotivity synchronises or indexes. Search, Ask and Literature review also work when Zotero is closed – only the links into Zotero need a running Zotero. The Zotero database is never read or changed directly.

### Language model and API key

Under **Settings → Language models** you choose the provider (Anthropic Claude, OpenAI, Google Gemini, DeepSeek, local Ollama or an OpenAI-compatible server) and enter the API key. The key is stored encrypted in the Windows Credential Manager and is never shown in plain text or written to files.

There are two roles:

- The **main model** writes answers, outlines and the text of the literature review – a strong model pays off here.
- The **helper model** phrases search queries and pre-selects texts – it may be cheap and fast.

**Reasoning depth** determines how thoroughly the model "thinks" before answering. Higher is better for difficult questions but slower and more expensive. **Test connection** sends a short test request. Optionally, prices per model can be entered; the literature review uses them to estimate costs.

### Embedding model

The embedding model turns passages into vectors so that texts can be searched by meaning – across languages, too (a German question finds English texts). The default is **Built-in**: Zotivity runs the model itself (with llama.cpp, the same technology Ollama uses), without any additional installation. The texts never leave the computer. **bge-m3** is preselected; like all models it is only downloaded at the push of a button (about 0.6 GB).

You can still choose **Ollama** (if already installed), cloud models (OpenAI, Gemini – faster, but the texts are then sent to the provider), an OpenAI-compatible server and Sentence-Transformers. Each model has its own index (see **Switching the model**); the previous one is kept until you delete it under **Stored indexes**. This card is collapsed and states the number, the space used and the active index; expanded, it shows for each model its size, the dimensions, the number of passages and the space used by the vectors.

### Model catalog: choice, download, short test

For everyday use, **Settings → Embedding → Built-in** shows just two things: the active model and the **Installed models** (downloaded, currently downloading and your own models) with size, time for 100 pages, index and actions. All other models are opened by **Add model …** in a dialog with two tabs: **Catalog** and **Search by name**. If nothing has been downloaded yet, the card suggests the recommended model with a download button. Rarely needed settings – CPU threads, parallelism, unloading and the central model catalog – are collapsed under **Advanced**.

The **Catalog** contains tested models, grouped into *Recommended*, *Fast*, *Alternatives*, *Large* and *Domain-specific models*. Each row shows strengths and the disciplines the model suits particularly well, languages, text length, the score on the multilingual MTEB benchmark, the licence, the download size with memory use, the **time for 100 pages** on this computer and the index size for your library. **Details** (for downloaded models **Details and prefixes**) below the name expands prefixes, pooling, file and measurements; everything starts collapsed.

- **Download** loads the file with a progress bar into the local data folder (never into a cloud folder) and verifies its checksum. You can cancel at any time; **Resume** loads only the rest.
- Afterwards a **short test** (10–60 seconds) measures speed and memory and checks with German and English test questions whether the model finds the right passages. "Estimated" becomes "measured"; the estimates of the other models follow this measurement. Before the first short test they are based on a brief computing test and the values of the reference computer.
- **Use** makes the model the active embedding model. If there is already an index of the same model from Ollama, Zotivity offers to take it over: 24 samples are re-embedded and compared; if the vectors match, there is no need to re-embed the whole library. The result immediately states what the adopted index does not contain – for example texts last indexed with another model – and offers to embed only those.
- **Prefixes** are placed before each text before it is embedded; many models use them to tell search queries from passages. For downloaded models they can be changed in the details (for your own models also the pooling); **Restore default** brings back the tested catalog values. Changed prefixes result in a separate index – the previous one is kept under **Stored indexes**. For the active model, Zotivity then explains what needs embedding, just as after a model switch.
- **⋯** lets you delete the model file, open the model description and discard a cancelled download. The index of a model is deleted separately under **Stored indexes**.
- Models with a selectable **vector length** (e.g. EmbeddingGemma 2) offer shorter vectors in the detail view: smaller index, slightly less accurate.

For most libraries – including the humanities and social sciences with German and English literature – multilingual general-purpose models are the best choice. Domain models mostly exist only in English (e.g. MedEmbed for medicine). Large models like Qwen3-Embedding 4B are the most accurate but very slow without a graphics card. On computers without AVX2 (older or budget processors) the built-in runtime runs as well, only more slowly; the fast models suit them.

The catalog ships with Zotivity and is renewed with every version. Under **Advanced → Central model catalog** you can also enter the address of a central catalog (later the file in the Zotivity GitHub repository): it is loaded at start-up and only used if it is newer.

### Search a model by name

The **Search by name** tab (in the **Add model …** dialog) finds more embedding models in GGUF format on Hugging Face, e.g. "e5", "gte" or "granite-embedding"; a pasted Hugging Face address works too. The results show the architecture (whether llama.cpp can run it as an embedding model), size, licence, downloads and date. **Select** opens the file variants (Q8_0 recommended) and suggests prefixes and pooling from the description of the original model. The model then appears under **Your models**, marked "untested" – the short test after the download shows whether search works with it. Models that require a Hugging Face login are not supported.

### Compare models and a model per project

**Compare models …** (at the stored indexes, once two models have an index) asks two models with an index the same question in a dialog (semantic search only) and shows the results side by side; texts found by both are highlighted. This lets you decide on your own library which model suits it better.

In the **Edit project** dialog a project can get its own embedding model. When the project is opened, Zotivity then switches to this model; each model keeps its own index, and if texts are still missing for that model, Zotivity offers to embed them (see below).

### Switching the model

The vectors of a model only fit that model – that is why each model has its own index. After a switch the texts are **not read again**: the text that was read and its passages are kept; they only need to be **embedded** for the new model (for the term see **Index → Indexing = reading + embedding**). This is much faster than a first indexing run.

- Right after the switch, Zotivity asks once whether to embed the texts now and states the number of texts and passages and the estimated duration. **Embed now** only embeds – nothing is read again and nothing is synchronised with Zotero; **Later** closes the dialog. The same switch is not reported a second time.
- Until then these texts count as **to embed**: they have been read but are not yet searchable with the new model. **Indexed** always means searchable with the active model. Semantic search does not find texts still to embed yet; keyword search does.
- Meanwhile, Ask and Literature review show a notice "With … only … of … texts are searchable" with **Embed now** and **Back to …** (the model with the largest index so far).
- Under **Stored indexes**, **Use** switches back at once to a model whose index exists – including its prefixes.
- New texts added after the switch are read and embedded by the next indexing run as usual; the texts still to embed are handled in the same run.
- **Switching during indexing**: the current run ends after the current batch of passages with the result "model switched". Work already done is kept, and no vector ends up in the index of the wrong model. Runs in the queue use the new model; in the report, **Continue with the new model** resumes the run. While a run is working, **Settings → Embedding** points this out.

### Write access and Zotero plugin

Both are optional.

- **Write access** lets Zotivity save evaluation sheets as notes on items and create collections for the literature review. After **Allow write access**, Zotero asks in a dialog of its own. Choose **"Remember my decision"** there, otherwise the permission only lasts until the next restart. If the dialog is hidden behind other windows, click Zotero in the taskbar.
- The **Zotero plugin** adds the right-click menu "Zotivity" to Zotero (index, ask, literature review for collections and items) and starts Zotivity together with Zotero. Installation: **Settings → Zotero and export → Save plugin**, then in Zotero **Tools → Plugins → gear icon → Install Plugin From File**.
## Projects

A project bundles corpora, chats and literature reviews for one undertaking, e.g. a master's thesis or an article. Everything is saved continuously; there is no "Save".

The **Project** view lists all projects on the left, one below the other; **New project** and **Import** are at the top. With many projects, the list scrolls on its own. A click opens a project; it is highlighted and the order stays the same. You can change the order by hand: drag a tile up or down with the mouse (a line shows where it will land; the list scrolls at its edge), or choose **Move up** or **Move down** in the **⋯** menu. New projects are added at the end. On the right is the overview of the active project: its corpora with their indexing status, the latest questions and the literature reviews.

- **New project** creates an empty project (name, description, colour).
- The **⋯** menu on a project tile offers Edit, Move up/down, Export as file, Duplicate, Archive and Delete.
- **Export as file** saves the project as a `.zoty` file (`.zllm` files from earlier versions can still be imported) – with corpus definitions, chats, literature reviews, evaluation sheets and search history, but without the index. Use it to back up a project or move it to another computer. **Import** loads such a file; missing collections are reported.
- A corpus can belong to several projects. When a project is deleted, corpora that are used elsewhere are kept.

### Archive

**Archive** (the **⋯** menu or the button in the project overview) puts finished projects away without deleting anything: the project disappears from the list and from the project switcher and moves to **Archive** at the bottom of the project column (expandable). A click on an archived project offers **Restore from archive**, **Restore and open**, **Export as file** and **Delete**. Archived projects can only be opened after restoring them. At least one project always stays open.

## Knowledge corpora

A knowledge corpus defines which texts from Zotero are searched. It consists of collections (each with all its subcollections), whole libraries or single items – from your own library and from groups.

### Creating and editing a corpus

1. Choose **Corpora → New corpus** and enter a name.
2. Tick the desired collections in the **Zotero library** list. A ticked collection includes its subcollections; they appear ticked as well.
3. Click **Create corpus** or **Save**.

The collection list scrolls in its own area; the header and the search field stay in place. Your own library and the groups are distinguished by colour: library titles and the headings "My library" and "Groups" carry a coloured bar. The search field filters collections by name; **Expand/collapse all** and **Refresh** are at the top right.

Single items are added to a corpus from the **Search** view (**Add to corpus**). They appear as dashed chips above the collection list.

The **⋯** next to a corpus in the list on the left offers **Remove from this project** (the corpus is kept and then appears under "Other corpora"), **Index** and **Delete corpus …**. Deleting asks in a small dialog; there you can also choose to only remove the corpus from the project instead.

### The figures

Below the selected sources Zotivity shows – even before indexing:

- **Items** – Zotero items in the selection (without notes).
- **Texts (PDF etc.)** – files with text that can be indexed. They split completely into the next four figures: texts = indexed + to embed + open + no text / error.
- **indexed** – searchable with the active embedding model. The addition **of which … to refresh** names indexed texts that the next run reads again, e.g. for more accurate page numbers after an update or because the file has changed; until then they are searchable with their previous text.
- **to embed** – read, but not yet embedded for the active embedding model (after a model switch). The notice below offers **Embed now**.
- **open** – not yet searchable with the active model; the next run reads them. These are new texts, but also texts read before that lack the vectors of the active model and are read again anyway.
- **no text / error** – e.g. scans without a text layer.
- **passages searchable** – passages that can be found with the active embedding model.

For a library that has never been synchronised, "–" is shown together with **Synchronise now**: the synchronisation reads the metadata from Zotero, and the figures appear afterwards.

The buttons below index the corpus, ask questions about it, use it for a literature review or show its texts in the index.

## Index

The **Index** view applies to all projects. This is where the texts of all corpora are read and made searchable – including corpora of other projects and corpora that no longer belong to any project ("Remove from this project" does not delete a corpus; you can delete it under **Corpora → More corpora → ⋯**). The **Index status (all corpora)** card therefore counts all corpora together, each text once. The **Corpora (all projects)** table shows the corpora of the active project at the top ("This project") and the others below ("Other corpora", each with its project or "in no project").

### Indexing = reading + embedding

Indexing consists of two steps:

1. **Reading** – Zotivity extracts the text from the file, recognises the page numbers and splits the text into passages. From here on, keyword search finds the text.
2. **Embedding** – the embedding model turns each passage into a vector, a list of numbers representing its meaning. Only then does semantic search find the passage, across languages too.

The vectors belong to their model. After a model switch only step 2 is needed ("to embed"); a text that only needs to be read again stays searchable with its previous vectors ("to refresh").

### Indexing

**Index all corpora** first synchronises the metadata with Zotero and then reads all new and changed texts. Texts already read are not processed again; Zotivity recognises changed files by their checksum. **Full synchronisation** reloads all metadata (otherwise this happens automatically once a week).

While reading, Zotivity determines the **printed page numbers** from headers and footers (volume, year and issue numbers are filtered out, the page range from Zotero serves as a cross-check) and remembers where a new page begins inside a section. If no numbering can be found, the source counts as "without page numbers" (n.p., German "o. S.").

At the top there is always the **Index status** across all corpora: the active embedding model, texts, indexed (with the addition "of which … to refresh"), to embed, open, problems and searchable passages, plus when the last check took place and when the next automatic check is due. Texts = indexed + to embed + open + problems. The button states what a run does, e.g. **Index: read 9 · re-read 44 · embed 2** – one run does everything at once. If only vectors are missing, **Embed only** (or **Embed … for …**) embeds them with the estimated duration, without reading anything again. The **Corpora** table shows the same figures per corpus, "to refresh" as a small symbol next to the number of indexed texts; it is reloaded together with the status, also after a synchronisation in the background. With more than ten corpora it scrolls within itself instead of making the page longer.

During a run, the **Running indexing** card shows a progress ring with percentage at the top, the embedding model and the **estimated remaining time** ("approx. … left"). It is based on the speed of this run and becomes more accurate after the first texts; while part of it cannot be estimated yet, it reads "at least … left". Below follow "Text … of …" (how many to read and how many only to embed), the current text with page and passage progress, the next texts in this run and the texts finished last. The same ring with percentage and remaining time appears in the status bar. Three counts must be distinguished:

- **embedded in this run** – passages this run has processed;
- **… of … passages searchable across all corpora** – all passages in the index that are searchable with the active model, including earlier runs; the same number appears in the status bar. It is therefore usually larger than the count of this run;
- **… of … passages of this text** (below the current text) – only the progress of the text currently being embedded.

How long 100 pages take is shown by the model catalog under **Settings → Embedding**. You can keep using Zotivity meanwhile. Cancelling loses at most the current text; the next run continues from there.

### Queue

If you start indexing while another run is already working – e.g. **Index** for a corpus, **Embed only**, **Index all corpora** or via the context menu in Zotero – it is added to the **queue** instead of being refused. The **Queue** card below "Running indexing" shows for each task its kind (index, embed only, retry texts with problems …), the corpus and its projects, what is currently open there, and how long the task has been waiting.

- The arrows change the order; the bin removes a task.
- The runs start one after another once the current one has finished. **Cancel** only stops the current run; then the next one starts.
- A task that is already waiting is not added twice. The status bar shows how many runs are waiting.
- While runs are waiting, the automatic check pauses. The queue lasts until Zotivity is closed.

### After the run: report and history

When a run has finished, Zotivity reports the result – even if you are working in another view ("Show" leads to the index). The live view gives way to the **Last run** report: result (done, done with problems, stage finished, model switched, cancelled or error), time, duration, trigger (manual or automatic) and the key figures. Depending on the result there is **View problems**, **Continue now**, **Continue with the new model**, **Resume** or **Start again**. **Processed texts** lists all texts of the run (clickable to Zotero), followed by the log. The × hides the report.

The **History of runs** keeps the last runs permanently in the index – so even after a restart you can see what happened, e.g. at night in stages. It shows the five newest at a glance, older ones by scrolling. Clicking a row shows its report. Automatic checks with nothing to do do not appear in the history; they only update "last checked".

### Texts of a corpus

The right column always shows the corpus selected in the **Corpora** table (its name at the top of the column). Preselected is the corpus of the active project whose texts were most recently read or embedded; a corpus you click stays selected until you switch projects. The column shows the texts of this corpus in groups: **In progress** (the text currently being read or embedded, with its progress), **Indexed** (searchable with the active model; with title, author, year, pages and passages), **To embed** (read, not yet embedded for the active model), **To refresh** (searchable, will be read again in the next run), **Open** (will be read in the next run; texts read before are marked "read before, will be read again") and **Problems** (with the error message). During indexing the column is updated continuously ("live"); a text only appears under "Indexed" once it is fully embedded. Clicking a title shows the item in Zotero; the PDF icon opens the file. The filter field searches title, people and year.

### Duplicates

If the same work exists more than once in Zotero – e.g. in "My library" and in a group, or as a duplicate that was not merged – Zotivity uses only one copy per work. It is detected by DOI (DOI field or "DOI: …" in the Extra field), otherwise by title, first author and year. Short titles like "Editorial" are only grouped by DOI, items with different DOIs never (usually different versions, e.g. preprint and article). If the same item is in several collections, that is not a duplicate – it is in the index only once anyway.

- **Before indexing**: when you start a run by hand and there are new duplicates in its scope, Zotivity asks beforehand – never during the run. For each work you see the copies with library, collections and whether their text has been read and page numbers detected. The rule's suggestion is preselected; "For all: Copy from …" picks one library for all works (unless a readable file is missing there). "Not a duplicate" uses all copies.
- **The rule** (for background runs and runs started from Zotero, which do not ask): first the copy with readable text, then the one with detected page numbers, then the preferred library (**Settings → Index → Duplicates**). The question can also be switched off there.
- **Effect**: only the chosen copy is read and embedded. In questions and literature reviews the work counts as one source with one evaluation sheet; citations, pages and links come from the chosen copy. This also applies in corpora that only contain another copy – on the right under "Texts in the corpus" it then says "copy from …".
- **Changing it later**: **Index → Duplicates** lists all detected works. The next run reads a newly chosen copy; until then the previous copy stays in use.

### Automatic, in stages and safe

These settings are under **Settings → Index**; the gear at the top of the Index view leads straight there.

- **Update in the background**: while Zotero is open, Zotivity regularly checks for new and changed items.
- **Stages**: at most a given number of texts per run and only within a time window (e.g. 22:00 to 07:00). For large libraries with thousands of PDFs this is the most convenient way.
- **Read texts in a separate process**: a broken PDF that crashes or hangs the reader is marked as an error after the time limit – the run continues.
- **Keep the computer awake** prevents sleep mode during indexing.
- If the embedding service is briefly unavailable (e.g. Ollama restarted), Zotivity waits for a configurable time instead of aborting.
- **Index backup**: after indexing runs, at most every 12 hours; the two newest are kept.

### Texts without text

"No text" usually means scans without a text layer. Remedy: enable text recognition (OCR) under **Settings → Expert → Reading** (requires a Tesseract installation) or save the PDF again with text recognition. Then click **Try again**.

The list of problems shows each attachment separately. An item with several attachments can be searchable despite a problem – the search then shows "indexed".

### Web page snapshots

Saved web pages (snapshots, HTML) are only indexed if the item has no PDF or EPUB. Otherwise the same text would be in the index twice – including the menus and reference list of the publisher's page – and answers would show duplicate passages. If the PDF yields no text or is deleted, Zotivity reads the snapshot at the next indexing run.

### Word and LibreOffice documents

Besides PDF, EPUB and web pages, Zotivity also reads **Word files (.docx)** and **LibreOffice documents (.odt)** stored as attachments in Zotero: the main text with headings, lists and tables; footnotes and endnotes follow at the end of their page or of the document. For documents with tracked changes, the current state counts. Headers and footers, comments and indexes are not read. The old Word format (.doc) is not supported – convert it in Word with **Save as → Word Document (.docx)**.

**Page numbers:** Word and LibreOffice record where the pages break when a document is saved. Zotivity uses this, including a different first page number. These are the pages as the document was laid out when last saved – on another computer or with other fonts they may differ slightly. Without this information (e.g. a Google Docs export), citations read "o. S." (n.p.).

Clicking a citation shows the passage as usual. Because Zotero does not display Word files itself, there is **Show in Zotero** instead of **Open PDF**; from there, a double-click opens the document.

## Search

The **Search** view is a search engine for the whole Zotero library – your own and all groups. It needs no language model and is therefore fast and free.

### Search catalogue

The search uses a local catalogue of the metadata of all libraries. Zotivity creates it when the view is opened for the first time (Zotero must be running). Afterwards Zotivity keeps it up to date by itself: while Zotero is running, it compares the version numbers of the libraries with the state at the last synchronisation every minute and synchronises when something has changed – at most every two minutes and only what changed, usually within seconds; otherwise hourly. Group libraries report no version number in Zotero; there, new and deleted items are noticed immediately and changed fields at the hourly synchronisation. The bar at the top shows the size and date of the catalogue and – while a synchronisation is pending, e.g. during indexing – the notice **Zotero has changed since** with **Synchronise now**. The search also works without Zotero.

### Single-field search

Type into the large field and press **Enter**. Title, people, publication, tags, abstract and DOI are searched. These rules apply:

- All words must occur (AND).
- Words are matched as word beginnings: `digit` finds "digital" and "digitisation".
- `"exact phrase"` in quotation marks searches for the word sequence.
- `-word` excludes hits containing that word.
- `OR` (or the German `ODER`) between two words finds hits with either, e.g. `youth OR adolescence`.

### Advanced search

**Advanced search** opens individual fields that apply in addition to the large field:

- **Title**, **Author, editor**, **Publication / journal / publisher**, **Tags**, **Abstract**, **DOI**
- **Full text (indexed texts)** – searches the text of the indexed PDFs and shows the passage found as a highlighted excerpt.
- **Year** from–to, **Item type** (e.g. journal article, book), **Libraries** and **In collection** (including subcollections)
- **only with PDF**, **only indexed texts**

**Clear fields** resets everything. Results can be sorted by relevance, year, title or author; **Load more** shows the next 100.

### Previous searches

The panel on the left lists all searches of the active project, newest first – with the search term, further fields and filters, number of results and time. A search that is run again moves to the top instead of appearing twice. A click on a search **fills the search fields** (opening the advanced search if needed) but does not search yet, so you can adjust it first; **Search** or **Enter** runs it. The **×** removes a search from the history, the bin clears the project's history. From six entries on, a filter field appears. Each project has its own history; it is exported with the project.

### Results

Each result shows title, people, year, item type and publication, and below that its **locations in Zotero**: the library (coloured: your own or a group) and all collections containing the item. Clicking a location shows the item in Zotero in exactly that collection.

- **Show in Zotero** – if the item is in several places, a selection opens.
- **PDF icon** – opens the PDF in Zotero.
- **Quote icon (❝)** – copies the **reference** in the citation style from the settings (Settings → Zotero and export), formatted for Word (italics stay italic) and as plain text. The message names the style. Zotero provides the reference; if Zotero is closed, Zotivity builds a simplified form and says so.
- **Corpus icon** – **Add to corpus**: only the corpora of the active project are offered. If the item is already included it is marked and can be removed there. **New corpus from selection** creates a corpus with exactly these items.
- **⋯** – copy the in-text citation (e.g. "(Gong/Li 2026)"), copy the DOI link or Zotero link, save as Word, BibTeX, RIS or Markdown, ask about this item, file in a Zotero collection.
- On the right are the indexing status (indexed, not yet indexed, no text, no PDF) and the project corpora that already contain the item.

### Selection and bulk actions

Use the checkboxes on the left to select results: **Shift+click** selects a range, **Ctrl+A** all results shown (outside the search fields), **Esc** clears the selection. The selection **is kept across several searches** – so you can collect sources from different searches; it applies per project until cleared. As soon as something is selected, a bar appears above the results and stays at the top while scrolling. It shows how many items are selected and how many of them come from earlier searches, and offers:

- **Copy reference list** – all selected items in the chosen citation style, sorted as in the style.
- **Copy in-text citations** – e.g. "(Gong/Li 2026; Samatha et al. 2025)".
- **Export** – **Word (.docx)** with citations and bibliography as Zotero fields (style can be changed with the Zotero Word plugin), **BibTeX (.bib)** for LaTeX, **RIS (.ris)** for other reference managers, **Markdown (.md)**.
- **To corpus** – add to a corpus of the project or create a new one. Newly added texts must be indexed afterwards; the message offers **Index now** for this.
- **Ask questions** – opens **Ask** with exactly these items as scope. If some are not indexed yet, Zotivity asks whether to index them first (the run goes into the queue if needed) or to ask with the indexed ones only.
- **⋯** – **File in a Zotero collection** (existing or new collection; requires write access, see setup). A Zotero collection belongs to one library: if the selected items are in different libraries, you choose the library; items from the others are skipped.
- **Show selection only** lists all selected items, including those from earlier searches; **Clear** empties the selection.

## Ask

In **Ask** you put questions in your own words. Zotivity looks for matching passages in the selected corpora and has the language model write an answer from them. The model may only use what the passages say; every statement carries a number as citation.

### What is searched

At the top you choose the **knowledge corpora** – several are possible. Without a selection, all corpora of the project are searched. From the Zotero plugin you can also ask directly about a collection or a selection of items; it then appears as a chip, and the × returns to the corpora.

Next to it you choose **Answer** or **Passages only** (shows the passages found without an answer from the language model – fast and free). The **preset** sets the search and answer values for a purpose all at once (fast, balanced, thorough). A dot indicates that values differ from the preset. The slider icon opens the **search options**: number of passages, maximum per text, research rounds and multi-query – for this session only.

### How the search works

1. The helper model phrases several search queries in German and English (**multi-query**). They can be expanded above the answer.
2. Each query searches by meaning (embeddings) and by keyword (BM25); the rankings are merged.
3. Similar passages are thinned out in favour of variety, with at most a few per text.
4. Optionally, **research rounds** check whether aspects are missing and search specifically for them; **re-ranking** reorders the candidates with the helper model or a local cross-encoder.

### Answer and citations

Clicking a citation number **[n]** shows the passage with its page; from there, **Open PDF** opens the file at exactly that page, and the copy icon copies the whole passage with the citation in the selected citation style (e.g. "(Gong/Li 2026: 2)" with FHNW) and the bibliography entry. All passages are listed below the answer; the bars show their **relevance** compared with the best passage for this question (not a probability).

After the answer, the icons at the bottom right **copy** it (text with references) or **export** it (Word, LaTeX, Markdown). The list of passages can be copied and exported in the same way. See the chapter Export for details.

Follow-up questions refer to the conversation so far. The project's previous questions are listed on the left; **New question** starts a new conversation.

## Database search

**Database search** (Ctrl+2) takes a search in subject databases from the research question to the selected literature in Zotero. The machine searches, removes duplicates and suggests – you decide. Every database search belongs to a project; the view shows the searches of the active project, the project page their status. The data is stored in `research.db` in the data folder. Searches without a project (e.g. after a project was deleted) are listed under “Without project” and can be assigned. A project has nine tabs (Alt+1 … Alt+9): Project, Databases, Search strategy, Search & import, Pool, Folders, Screening, Handover and Full texts. Everything is saved automatically. The header shows where the project stands, e.g. "PubMed 503 · OpenAlex 934 · screened 380/1150".

### Project and databases

**Project** holds the research question, a short description and the inclusion and exclusion criteria (one line per criterion). The exclusion criteria work in three ways: they are offered as reasons in screening and for full texts, they feed into the AI suggestions, and they go into the log. They filter nothing automatically; an exclusion block in the search strategy arises from them only if a criterion is clearly recognisable in the title. Also here are the **selection process** (up to three reviewers, procedure) and the **target in Zotero**: the target library, normally through Zotero on this computer. Under **Databases** you choose disciplines; the app suggests matching databases from its catalog, with access, terms of use and the key needed. Directly searchable are PubMed, OpenAlex, Europe PMC, ERIC, EconBiz, Semantic Scholar, arXiv, OSF Preprints and swisscovery. Licensed databases (PsycInfo, CINAHL, SocINDEX …) use the **RIS route**: search and export there, import here. The app never logs in to licensed databases and does not automate a browser.

You store keys under **Settings → Databases**: OpenAlex (required since February 2026), PubMed (10 instead of 3 requests per second) and Semantic Scholar. The Databases tab shows when a key is missing. The key for the Zotero web API is under **Settings → Zotero and export**; it is only needed if a database search writes through zotero.org instead of Zotero on this computer.

### Search strategy, search and import

The **search strategy** consists of concept blocks (e.g. population, phenomenon, context, plus an exclusion block): within a block OR applies, between blocks AND, exclusion blocks are added with NOT. From them come the search strings per database on the right, with live hit counts; both sides scroll on their own. **AI suggestions** appear directly with the blocks: what a block still lacks in its card, new blocks as a dashed card of their own. × drops a term, ↻ requests a block again, **Adopt** or **Adopt all** turns them into firm terms. Blocks are optional: ready-made search strings can be pasted under **Search & import** or loaded as text files. There, search strings are versioned; a PubMed string can be translated into all selected databases (the translation is a suggestion – check and count). **Count all** and **Search all** run over all directly searchable sources; If a search string says “searched with v1 – search again”, the last search ran with an earlier version: only **Search** runs the current one; the circle icon only fetches the hit count. RIS files are dropped into the drop zone in the panel on the right, together with the **search date**, the day of the search in the database. Also on the right you enter **other sources** (reference lists, websites, registers). Every search is logged; **Log of runs** opens a window.

### Pool and prefilters

The **pool** holds all records without duplicates (DOI, PMID, OpenAlex ID, accession number, title) – per search string the records of the latest search, plus the imports. It remains the complete list after screening, so the filter “all decisions” also shows the decisions from screening. Prefilters and the recall check are in the panel on the right. **Check against Zotero** marks what is already in the target library. **Prefilters** only mark, they never delete: an exclusion rule such as "cyberbull*, bully*" can have exception terms; records with an exception term become **borderline cases** instead of being hidden. **Review hidden records** opens a quick review with multiple selection. Missing abstracts are fetched via Crossref, PubMed and Semantic Scholar; without an abstract a record appears as "title only", never as an exclusion. The **recall check** tests known key papers (DOIs) and warns if one is missing or silently hidden.

### Folders

Under **Folders** you create up to 20 folders with fixed numbers, each mapped to a collection of the target library (chosen under Project). The tab comes before screening because including a record there means putting it into a folder; the first nine have the shortcuts 1–9 in screening. You choose collections in the tree as elsewhere in Zotivity; new ones can be marked for creation. Nothing is created in Zotero before you confirm.

### Screening

**Screening** shows the records as **cards** (one record with the full abstract) or as a **list** (all open ones at once). Shortcuts on the cards: **J**/**K** browse, **1–9** include into the folder, **X** exclude (with reason), **?** unsure, **G** borderline case (with reason; the flag stays with the decision), **A** accept the AI suggestion, **Z** undo. In the list you tick what is included; **Apply …** shows the balance and saves everything as one batch, which **Z** undoes as a whole. Queues for open records, borderline cases, unsure and hidden records. If reviewers are entered under Project, you choose at the top who is deciding; the name is kept with the decision and in the log. Each record holds one person's decision: this is not independent double screening, and the log and the report say so.

### AI suggestions

AI suggestions are optional: in screening (relevant with a folder suggestion, not relevant, borderline case – each with the criterion and a one-sentence reason), for databases from the research question, for concept blocks, for subfolders and for the report. Database search uses the model of the **pre-selection in literature reviews** (Settings → Expert → Literature review: helper or main model) with its reasoning depth. Only title, journal, year and abstract of the records plus the project text are sent – nothing from Zotero and no full texts. Before each run the app shows the estimated tokens and – with prices entered – the costs; a run can be stopped. The **AI suggestions** switch hides the suggestions (blind screening). A suggestion never replaces the decision; both are logged.

### Handover and log

**Handover** shows the plan per folder: new items (details optionally completed via Crossref, tag "litsearch") and existing ones that are only added to the collection. Writing to Zotero happens only after explicit confirmation; for Zotero on this computer, write permission in Zotero is needed. The **search log** (Markdown, in the style of PRISMA-S) contains sources, search strings with date and version, hit counts, duplicates, prefilters per rule, inclusions and exclusions per reason, AI usage, selection process, full-text assessment and the selected literature; plus CSV files for searches and for records and decisions.

**Selection flow** shows the numbers of the PRISMA 2020 flow diagram as far as Zotivity knows them and can be saved as SVG. The **report for the methods section** is a draft: a language model phrases sources, search, criteria, selection process and flow from the log data, in German or English. It adds nothing of its own; anything missing appears as [fehlt: …] (missing), and Zotivity reports numbers that are not in the data. The log data is sent, not the titles and abstracts of the records. The report does not replace a complete PRISMA report: database search does not cover data extraction, risk of bias or synthesis.

### Full texts

After the handover you obtain the full texts and assess them; PRISMA asks for separate numbers on this. The step is optional and holds nothing up: missing PDFs are the normal case. Get them in Zotero, e.g. with “Find Full Text”; the next time you open the tab it says “available” (PDF, EPUB, Word and ODT count, web snapshots do not). If Zotero is closed, the last known status applies.

For each text you set **Include**, **Exclude** (with reason) or **Not retrievable** (with reason). The log and the flow diagram state the current status; anything open counts as not yet assessed. Without this step the log documents the selection only up to title/abstract screening. Items excluded at full text stay in Zotero. **Take out of collections …** removes them from the collections of this search after confirmation and adds the tag “litsearch-volltext-ausgeschlossen”; nothing is deleted.

## Literature review

The literature review leads in five steps to a fully referenced overview text. Each step waits for your confirmation; you can go back to an earlier step at any time. Every step has the same layout: the five steps at the top, below them the collapsed **Prompt** on the left (title, research question, corpora, language, target length) and on the right the buttons that take you further – always in the same place.

### 1. Keywords

You enter a research question, choose the project corpora, the language of the text and the target length. Zotivity proposes a **search strategy**: many search queries in German and English, with synonyms and technical terms. They can be changed, deleted and added to – like search strings in literature databases. **Start search** searches with all queries and moves on to the next step. Afterwards, each query shows how many texts it found and how many only it found; **Repeat search** searches again after a change (the previous ticks are lost).

### 2. Select literature

The helper model proposes a selection (suggested, maybe, excluded, each with a reason). You check the ticks. **As Zotero collection** creates the selection as a collection; items added there are brought back with **Take over from collection**. **Confirm selection** completes the step.

### 3. Evaluate

Each text is read individually – in full up to an adjustable length, otherwise the parts relevant to the question – and recorded in an **evaluation sheet**: research question, method, sample, findings, limitations and verbatim key quotations with page. Zotivity does not leave the page of a key quotation to the language model: it looks the quotation up in the text and sets the printed page number (or "o. S."). Beforehand, Zotivity shows the counted input tokens, the estimated output and reasoning tokens and – if prices are entered – the estimated costs. Sheets are reused; if you like, Zotivity also saves them as a note on the Zotero item.

Clicking a ticked text shows its evaluation sheet: short description, fields, key findings, key quotations and keywords, plus model, date and basis (full text or excerpts). Clicking the page of a key quotation opens the PDF in Zotero at that point. **Recreate sheet** reads only this text again and replaces the sheet (and the note in Zotero); text that has already been written stays unchanged.

### 4. Write

A **thematic outline** (not text by text) is created from all sheets. Headings, focus, word count and assigned texts can be adjusted, and sections can be added, moved and removed. The sections are then written one after the other; every statement is referenced to the text it comes from. Once the text is written, Zotivity switches to **Check** and shows it there.

**Length:** the target length refers to the text with headings and citations – the bibliography and the "Literature search method" appendix come on top (Word's word count includes them). The outline distributes the target length across the sections; each section gets its word count as a binding upper limit. Language models still often write more. If a section runs long, the following ones get correspondingly less room (down to at most 60 % of their planned length). In the outline, each word count is followed by the number of words actually written.

If the provider stops a section early – at the length limit (with Gemini, reasoning tokens count towards it) or because the output reproduced a longer passage verbatim (a Gemini block) – Zotivity writes it a second time right away: with more room or with the instruction to quote verbatim more briefly. To rewrite a single section, use the pencil icon in the outline; the other sections stay unchanged.

### 5. Check and output

The check counts words and cited texts, looks up every verbatim quotation in the original text and reports citations of texts outside the selection. Quotations not found are often only hyphenation or omissions – still compare them with the PDF before use. The findings are collapsed under **Check findings**; the line says what there is to check, a click shows the details. The text follows below.

It also reports **incomplete sections**: stopped by the provider, with a quotation lacking its closing quotation mark, ending mid-sentence or, in addition, much shorter than planned. **Rewrite** next to the section replaces only that section. Sections more than 20 % over their planned length appear as **sections that are too long**: **Shorten** has the language model tighten a section to the length from the outline, **Shorten all** does this for all of them. Nothing new is added (the evaluation sheets are not sent along); citations and verbatim quotations stay unchanged or are dropped. The current version is replaced – read the section afterwards. If the answer is not shorter, the section stays as it was. **Check again** repeats the check without a language model, e.g. after a change to the text.

**Texts deleted in Zotero:** if you delete an item in Zotero that a literature review or a saved answer cites, Zotivity keeps its short details (title, people, year, DOI). If another copy of the same work still exists – e.g. after you deleted a duplicate – the citations point to it automatically; if two identical citations then stand side by side, one remains. If no copy is left, the citation stays readable ("Author Year" instead of "n.a. n.d.") and the check reports it. Corrections made in Zotero (e.g. a name or year) appear in the citations and the bibliography automatically; they do not change the running text written by the language model.

A click on a citation in the text opens a small choice: **Show in Zotero** (selects the item in Zotero) or **Open PDF in Zotero** (at the cited page). If a citation has no page, Zotivity looks in the cited text for the passage closest to the cited statement and opens the PDF there; the choice then names the PDF page. That page is only used for opening, not written into the text. With several pages ("p. 1, 9" or "12–14") the first one counts. Where citations link to in exports (Markdown, note in Zotero) is set under **Settings → Zotero and export → Citation links in exports**. Output: **Copy**, **Export** as Word, LaTeX or Markdown, or **As note in Zotero**. All exports end with the "Literature search method" listing corpora, search queries and hits.

## Export to Word and LaTeX

Answers, passages and literature reviews can be copied and exported. Citations and bibliography come from Zotero so that they remain editable there.

### Word (.docx)

Each citation is a **Zotero field**, and so is the bibliography – exactly as if you had inserted the citations with the Zotero plugin for Word. After opening the file in Word:

1. Click **Refresh** on the **Zotero** tab. Zotero formats the citations and bibliography in the selected style.
2. Citations can be changed as usual with **Add/Edit Citation**; **Document Preferences** switches the citation style (for "o. S." see below).

For this to work, the items must be present in the Zotero library Word works with. Items from groups are linked via the group. With the Zotivity plugin installed, citations are always linked exactly to the items, even in an unsynchronised library. If Zotero is closed during the export, Zotivity creates the citations from the stored metadata; the bibliography is then formatted more simply until you click Refresh in Word.

### LaTeX (.tex)

The .tex file compiles straight away: citations appear as `\parencite[p.~12]{key}`, the BibTeX data from Zotero sits in a `filecontents` environment at the top. Compile with pdflatex or lualatex and **biber**. The resulting `literatur.bib` can also be imported into Zotero or replaced with your own Better BibTeX file.

### Copying and Markdown

- **As text** copies the text with short citations (author, year, page) and the bibliography.
- **Formatted for Word** copies the same with headings and emphasis for pasting into Word, e-mail or other programs (without Zotero fields).
- **Markdown (.md)** saves a text file with short citations and bibliography.

Choose the citation style for exports under **Settings → Zotero and export** from the styles installed in Zotero (install new styles in Zotero under *Settings → Cite*, then refresh the list in Zotivity). Footnote styles are not supported yet. The language of the bibliography follows the language of the AI output.

### Page numbers and "o. S."

Citations give the **printed page number** (from the header or footer), not the page of the PDF file – Gillingham (2019) in *Child Abuse Review* 28: 114–126 is cited with "p. 114", even if the PDF starts with page 1. The link into the PDF still leads to the right place. If a source has no page numbers (reports, web pages, some preprints), the citation says **"o. S."** (German for n.p.) – for verbatim quotations, not for every paraphrase.

How "o. S." goes into the Zotero citation in Word depends on the style; the settings show a sample citation:

- If the style prints the page **without** a label (e.g. "(Müller 2019: 114)"), "o. S." becomes the page locator – the style sets the separator itself, also with "ibid.: o. S.".
- If the style puts **"p."** before the page (e.g. APA: "(Müller, 2019, p. 114)"), that would give "p. o. S."; then ", o. S." goes into the citation as a **suffix** (visible and editable in Word in the Zotero dialog of the citation), with the style's separator.

Better change the style in Zotivity later and export again rather than in Word: the marker is adapted to the chosen style. The marker text ("o. S.") can be changed or cleared under *Marker for missing page numbers*.

## CSL editor

Citation styles (CSL) define how citations and the bibliography look. In the **CSL editor** you adapt an existing style – for example your university's – and install it in Zotero. The preview uses **citeproc-js**, the same software Zotero uses to create citations: what you see is what appears in Word.

> **First version:** the CSL editor is still in development. Feedback, bug reports and contributions are welcome – as an issue or pull request on [GitHub](https://github.com/avibecoder42/Zotivity/issues).

### Finding and adopting styles

On the left are three lists: **Mine** (styles edited in Zotivity), **Zotero** (styles installed in Zotero) and **zotero.org** (search across the roughly 10,000 styles of the Zotero Style Repository, filterable by format). The zotero.org list is only loaded when you search (about 300 KB once) and afterwards only fetched again when it has changed. You can also import a .csl file.

Other styles are shown in the preview first. **Use as my own style** creates a copy with its own name and ID – the original stays unchanged and is not overwritten when installing. For **dependent styles** (many journal styles only point to a parent style), an independent copy of the parent style is created.

### Editing in the preview

The preview shows in-text citations (with a page reference) and bibliography entries for typical document types: book, book chapter, journal article, article with four authors, newspaper article, web page, thesis, report and edited book. If your library has a matching item, Zotivity uses it (the most complete one; for articles with the matching number of authors, for the edited book with editors only) – otherwise a made-up English example. Add single items of your own below via the search. The preview language (terms such as "p." or "ed.") can be chosen.

**Choose item types …** sets which types the preview shows: default examples can be deselected, and every other type Zotero knows can be added – e.g. case, statute, conference paper, presentation, film or dataset. The list and the names come from Zotero itself (the last saved version when Zotero is not running). Here too the example comes from your library where it has an item of that type; the switch at the top of the window shows made-up examples only instead. The × on an example hides it, **Restore default selection** brings back the nine default examples. The selection applies to all styles. If a style has no rule of its own for a type, the preview shows how it formats it in general.

**Collection …** shows the items of a Zotero collection (with subcollections, at most 40) as examples – e.g. a collection of typical cases to check a style against. In the window you choose the collection from your libraries; **Show only this collection** hides the item types. The collection and its number of items then appear at the top; its × removes the selection again.

**Click a part of a citation**, for example the year: the panel on the right shows exactly that part's properties – text before and after, italic, bold, small caps, capitalisation; for names "and" or "&", order, initials and from how many names "et al." is used; for dates the form; for page references "p." or "page". The bar at the top of the panel shows the path from the text or bibliography via the macros to the clicked part; clicking selects that level – e.g. the place where a macro sits in the bibliography. Parts can be moved, removed or followed by a new field.

**Moving:** **Earlier** and **Later** swap with the neighbour; at the start or end of a group, the part leaves the group. **To the start** and **To the end** put it at the start or end of the entry (more precisely: of the outermost group). If the selected part stands alone – like the year in the "date" macro – Zotivity moves the next level up: the place of the macro in the bibliography or the whole condition ("if book …, else …"), whose cases keep their order. A note says what is moved. So one click on **To the end** puts the year at the end of the entry.

**"et al."** needs two numbers: **"et al." from … names** (from how many names the list is shortened) and **Of these, show** (how many remain before it). APA shortens in-text citations from 3 names to the first one, some bibliographies from 6 names to the first 3. Below the fields an example of the setting is shown.

Many styles use macros in several places. If the selected part is inside such a macro, the panel says in how many places it applies. In-text citations and bibliography often share a macro, e.g. for the year. Then **Change applies** appears: the default is the part you clicked (**only in text** or **only in bibliography**). With the first change, this part gets its own copy of the macro (e.g. "date-bibliography"); the other stays unchanged. With **in text and bibliography** the change applies to both. After each change the affected examples are marked ("The last change affects 5 of 9 examples"). Without a selection the panel shows settings for the whole style, e.g. "et al." in citations and bibliography, hanging indent or page ranges.

### Code and earlier versions

**Code** shows the style as XML. Changes appear in the preview immediately; errors are reported with line and column. **Go to selection** highlights the part selected in the preview. Whatever clicking does not cover (e.g. sorting, disambiguation, new conditions per document type) can be edited here.

**Undo** and **Redo** (Ctrl+Z) apply to all changes. **Save** (Ctrl+S) keeps the previous version under **Earlier versions** (the last 30).

### Installing in Zotero

**Install in Zotero** hands the saved style to the Zotivity plugin, which installs it with Zotero's own function. The style is then immediately available in Zotero, in the Word plugin and in Zotivity (**Settings → Zotero and export**). Installing a changed style again replaces the earlier version in Zotero. Without a current plugin, Zotivity saves the style as a .csl file; in Zotero, choose **Settings → Cite → "+"** and open the file.

## Settings

- **Language models** – provider, API key, main and helper model, reasoning depth, prices.
- **Embedding** – provider (built-in, Ollama, cloud), model catalog with download and short test, name search on Hugging Face, stored indexes, model comparison; runtime (CPU threads, concurrent passages, unloading when idle, central model catalog).
- **Index** – automatic in the background and in stages, protection for large libraries (separate process, time limit, keep awake, waiting when the embedding service is unavailable), duplicates (question, preferred library), index backup.
- **Zotero and export** – connection, write access, notes for evaluation sheets, target of citation links in literature review exports (PDF page or Zotero item), citation style for exports (from the styles installed in Zotero, with a sample citation), marker for missing page numbers, Zotero plugin.
- **Language** – language of the interface and the help; language of the AI output (answers, evaluation sheets, literature review). "Like the question" answers in the language of the question. Verbatim quotations always stay in the original language.
- **Appearance** – System, Light, Grey or Dark. The title bar of the program window follows: in the colours of the interface on Windows 11, light or dark on Windows 10.
- **Expert** – presets and all search, answer, literature review, splitting and reading values. Changed values are marked and can be reset individually. Your own presets can be shared as files.
- **Program & data** – updates, index figures, storage locations (data, settings, logs) and Quit.

On first start the program window adapts to the screen and afterwards remembers its size and position. On very wide screens the content is shown at most in 16:9 format and centred.

### Updates

If an update source is entered, Zotivity checks for new versions at start-up. **Update now** downloads the installer, quits Zotivity and restarts it after installation. Settings, index, corpora and keys are kept.

## Privacy and data

- Index, projects, chats and literature reviews are stored locally in the data folder (Settings → Program & data). It deliberately does not sit in a synchronised folder.
- With a local embedding model (built-in or Ollama), the texts do not leave the computer during indexing. With a cloud embedding, all passages are sent to the provider. The built-in runtime only accepts requests from Zotivity (random key, 127.0.0.1 only) and never accesses the network; Hugging Face is only contacted for downloads at the push of a button and for the name search.
- When asking and for the literature review, the passages found or the texts of the selection are sent to the provider of the language model. With Ollama as language model everything stays local.
- **Search** works entirely without a language model.
- API keys are stored encrypted in the operating system's credential store.
- Zotivity changes Zotero only with write access and only on your instruction: notes for evaluation sheets, collections for the literature review.

## Troubleshooting

### Zotero cannot be reached

Is Zotero running, and is the local interface switched on (chapter Setup)? The status bar shows the state; **Check** under Settings → Zotero and export queries it again.

### Write access: no dialog appears

Zotero's dialog is often hidden behind other windows. Click Zotero in the taskbar. If "not allowed" is still shown after granting access, refresh with **Check**; if the permission only applies to this session, this is noted next to it – next time choose "Remember my decision" in Zotero.

### Ollama is not running

Install and start Ollama from ollama.com, then click **Check again** under Settings → Embedding. If the model is missing, Zotivity offers to download it.

### The built-in runtime does not start

If Zotivity reports that the runtime or one of its files is missing, reinstall Zotivity. Virus scanners occasionally remove program files they do not know (false alarm); in that case add the Zotivity folder as trusted in the virus scanner. If loading a model fails, the cause is in the log `llama-<model>.log` (Settings → Program & data → Logs). For your own models the architecture is often not supported.

### Indexing is slow

Local models are slow on laptops; the model catalog shows the time per 100 pages. Options: choose a faster model from the *Fast* group, index in stages at night, choose fewer texts per corpus or use a cloud embedding. With Ollama a graphics card can be used as well (Settings → Embedding → Ollama → Device).

### Answers find nothing

Check whether the selected corpora have indexed texts (Index → Corpora) and whether they are already embedded with the active embedding model – after a model switch a notice above the answers shows how many texts are searchable so far, with **Embed now** and **Back to …**. Multi-query and more passages (preset "thorough") help with broad questions.

### Buttons do not respond

If a view shows a display error, choose **Reload**. If that does not help, quit and restart Zotivity. The logs (Settings → Program & data) help with troubleshooting.

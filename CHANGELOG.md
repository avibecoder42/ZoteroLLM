# Changelog

All notable changes, newest first.

## 1.1.0 – 2026-11-01

**ZotLLM is now Zotivity.** The name fits what the application has become: comprehensive scholarly work with your Zotero
library, not only language models.

### Moving from ZotLLM
- On the first start, Zotivity takes over the data folders, settings and stored API keys of ZotLLM automatically.
- Projects are saved as **`.zoty`** files; `.zllm` files from earlier versions can still be imported.
- **Replace the Zotero plugin:** remove the old "ZotLLM" plugin in Zotero and install the new one (Settings → Zotero and
  export → Save plugin). The setup checklist reminds you. Word documents with existing citations keep working.
- The installer updates an existing ZotLLM installation and removes its old program folder. The command `zotllm` and the
  environment variables `ZOTLLM_*` still work.

### New
- **Database search** (new project view, Ctrl+2; German: “Recherche”): the step before the literature review. A search
  project leads from the research question to the selected literature in Zotero, in nine tabs (Alt+1 … Alt+9). Everything
  is saved automatically:
  - **Project** and **Databases:** research question, criteria, up to three reviewers, target library in Zotero;
    disciplines and a database catalog with access, terms of use and keys.
  - **Search strategy** and **Search & import:** concept blocks → search strings per database with live hit counts; AI
    suggestions appear directly with the blocks;
    searches in PubMed, OpenAlex, Europe PMC, ERIC, EconBiz, Semantic Scholar, arXiv, OSF Preprints and swisscovery;
    RIS import for licensed databases (PsycInfo, CINAHL …) with the date of the search; other sources for the log. No
    browser automation.
  - **Pool:** de-duplicated records, check against the Zotero target library, prefilters that only mark (with
    exception terms that turn records into borderline cases), missing abstracts fetched, recall check with key papers.
  - **Folders** 1–20 (shortcuts 1–9) mapped to Zotero collections; **Screening** as cards (J/K, 1–9, X, ?, G, A, Z)
    or as a list with bulk apply, recording who decides; **Handover** to Zotero only after explicit confirmation, search
    log in the style of PRISMA-S and a PRISMA 2020 flow diagram (SVG).
  - **Full texts** (optional): status per included text, detected from Zotero where possible – still missing, available,
    not retrievable, included, excluded with reason. Missing PDFs hold nothing up. Items excluded at full text can be
    taken out of the search's collections after confirmation and tagged; nothing is deleted.
  - **Report for the methods section** (optional): a language model drafts sources, search, criteria, selection process
    and selection flow from the log data, in German or English. Missing information appears as a placeholder, and
    numbers not found in the log data are reported. It does not replace a complete PRISMA report.
  - Optional **AI suggestions** (screening, databases, concept blocks, subfolders, report) with the model of the pre-selection
    in literature reviews; token and cost estimate before each run; decisions are always made by hand.
  - Every database search belongs to a Zotivity project; the project page lists them with their screening status, and
    searches without a project (e.g. after deleting one) can be assigned again. Data lives in `research.db` in the data folder.
  - Keys for the databases are stored under **Settings → Databases**, the key for the optional Zotero web API under
    **Settings → Zotero and export**. Searches write through Zotero on this computer by default.

### Changed
- **Project views in the order of the workflow:** Project, Database search, Corpora, Ask, Literature review, and set
  apart Search (Ctrl+1 … Ctrl+6). Index moves to **Ctrl+8**, the CSL editor stays on Ctrl+7.
- **Setup is only the technical part** and lives under Settings → Setup, where the first start leads. Zotivity then reopens
  the last project in the view used last, even if Zotero is closed.
- **New Guide**, the top entry of the navigation bar: create a project, database search (optional), create and index a
  corpus, work with the corpora – with links into the views and the status in the active project. The project page names
  the next step.
- **Layout:** reading text and forms stay readable and centred; lists and tables use the full width. Panels on the right
  adapt to the window until you drag them. The project page tiles no longer wrap as 4 + 1.
- **Zoom:** in the program window the whole interface can be zoomed (status bar, Ctrl + mouse wheel, pinch, Ctrl +/−/0);
  the value is kept across restarts.

### Also new
- Language models can answer with a **JSON schema** where the provider supports it (Claude structured outputs, Gemini,
  OpenAI); otherwise the schema is part of the request.

## 1.0.1 – 2026-10-29

### New
- "Check" shows the written words against the planned length and lists **sections that are too long** (more than
  20 % over their plan). **Shorten** has the language model tighten a section to its planned length without adding
  anything new – citations and verbatim quotations stay unchanged or are dropped; **Shorten all** does this for all of
  them. The outline shows the words actually written next to each section's word count.
- The target length is explained: it refers to the text with headings and citations; the bibliography and the
  "Literature search method" appendix come on top (Word's word count includes them).

### Fixed
- **Length of literature reviews:** language models wrote much more than planned (e.g. about 2,400 instead of 1,600
  words). Each section's word count from the outline is now a binding upper limit in the writing prompt; if a
  section runs long, the following ones get correspondingly less room (down to at most 60 % of their plan).

## 1.0.0 – 2026-10-29

### New
- **CSL editor** (new tab, Ctrl+7): find, adapt and install citation styles. This is a first version and still in
  development – feedback, bug reports and contributions are welcome as
  [issues](https://github.com/avibecoder42/ZotLLM/issues) or pull requests.
  - Search the roughly 10,000 styles on zotero.org (the list is only loaded when you search – about 300 KB once,
    afterwards only when it has changed), open styles installed in Zotero or import a .csl file.
  - Other styles are adopted as a copy with their own name and ID, so the original is never overwritten; dependent
    styles become an independent copy of their parent style.
  - Preview with citeproc-js, the software Zotero itself uses: in-text citations and bibliography entries for nine
    typical document types, plus your own Zotero items, in a choice of languages.
  - Click a part of a citation to edit exactly that part: text before and after, italic, bold, small caps,
    capitalisation, name format ("and" or "&", initials, order, "et al."), date form, page labels; move, remove or add
    fields. Parts used in several places are flagged, and the examples changed by the last edit are marked.
  - Code view with live preview and error messages, undo/redo, earlier versions.
  - "Install in Zotero" uses the ZotLLM plugin and Zotero's own install function: the style is immediately available in
    Zotero, in the Word plugin and in ZotLLM. Without the current plugin, the style is saved as a .csl file.
- The Zotero plugin can install styles from the CSL editor – reinstall it once (Settings → Zotero and export → Save
  plugin).

### Changed
- **Literature review in five steps:** "Keywords" (search queries) and "Select literature" are now separate steps.
  Every step has the same layout: the steps at the top, below them the collapsed prompt (title, research question,
  corpora) on the left and the buttons for the next step on the right, always in the same place.
- After writing, the review switches to "Check" and shows the text there; the check findings are collapsed into one
  summary line.
- **Evaluation sheets can be viewed:** in "Evaluate", a click on a text shows its sheet – fields, key findings, key
  quotations (opening the PDF in Zotero at the page) and keywords. "Recreate sheet" re-reads a single text.
- Outline sections can now also be moved up.
- **CSL editor:** a change can apply only to in-text citations or only to the bibliography, even where both use the
  same macro (e.g. the year) – the clicked part gets its own copy of the macro. The filter for styles installed in
  Zotero also searches short titles and ignores accents ("fhnw" finds "Schreibberatung PH FHNW").
- **CSL editor – examples:**
  - "Choose item types": besides the nine default examples, every other item type Zotero knows (e.g. case,
    statute, conference paper, film); default examples can be hidden. The list comes from Zotero's schema.
  - Examples come from your own library where a matching item exists (for articles with the matching number of
    authors); otherwise made-up English examples, mapped to CSL the way Zotero does it.
  - "Collection …": show the items of a Zotero collection as examples.
- **CSL editor – moving parts:** "Earlier"/"Later" leave a group at its edge, "To the start"/"To the end" jump
  there. If the selected part stands alone (like the year in a date macro), the place of the macro or the whole
  condition is moved – e.g. the year to the end of the bibliography entry. The bar above the selection shows the
  path through the macros.
- **CSL editor – "et al.":** clearer fields ("et al." from … names / of these, show) with an example.

### Fixed
- Static files in folders starting with "v" were mistaken for versioned paths.
- Formulas in LaTeX notation written by the language model (`$\beta = .35$`, `$\ge 21$`) now appear as text (β = .35,
  ≥ 21) in Word, Markdown, copied text, the Zotero note and the app; the LaTeX export keeps them as formulas. The
  writing prompt now asks for plain text with Unicode characters instead.
- "Shin et al. [@KEY]" no longer becomes "Shin et al. (Shin et al. 2021)": if the author is named right before the
  citation, it only shows year and page – in Word via Zotero's "suppress-author", in LaTeX via `\parencite*`.

## 0.9.0 – 2026-10-23

### New
- **Word and LibreOffice documents:** ZotLLM now also reads Word files (.docx) and LibreOffice documents (.odt) stored
  as attachments in Zotero – the main text with headings, lists and tables; footnotes and endnotes follow at the end of
  their page or of the document. For tracked changes, the current state counts; headers, footers, comments and indexes
  are left out. The old Word format (.doc) is not supported.
  - **Page numbers** come from the page breaks Word or LibreOffice recorded when the document was last saved,
    including a different first page number. Without them (e.g. a Google Docs export), citations read "o. S." (n.p.).
  - Word attachments already in your library are picked up at the next sync with Zotero and read in the next indexing
    run; existing settings are extended automatically.
  - Citations of Word documents offer "Show in Zotero" instead of "Open PDF", because Zotero does not display Word files
    itself.

## 0.8.1 – 2026-10-21

First public release.

- **Ask:** questions about your knowledge corpora, answered only from the retrieved passages. Every citation opens the
  passage and its page; "Open PDF" jumps there in Zotero. "Passages only" searches without a language model.
- **Literature review:** an editable search strategy, screening, one evaluation sheet per text (stored as a Zotero
  note), an editable outline, section-by-section writing, and a check of every citation and verbatim quotation against
  the sources. Output as Markdown, Word (live Zotero fields), LaTeX or a Zotero note, with a search-method appendix.
- **Search without a language model** across your library and all groups: copy references and in-text citations in
  your Zotero citation style, export selections as Word, BibTeX, RIS or Markdown, add them to a corpus or a Zotero
  collection, or ask about exactly these items.
- **Projects** bundle corpora, chats and literature reviews; export and import as `.zllm` files, archive.
- **Language models:** Claude, ChatGPT (OpenAI), Gemini, DeepSeek and local models via Ollama. API keys stay in the
  operating system's key store.
- **Built-in embeddings** (llama.cpp) with a curated catalog of 12 models, checksum-verified downloads, a short benchmark
  on your own computer and a comparison mode; Ollama and cloud embeddings are also supported.
- **Indexing for large libraries:** printed page numbers, resumable runs, a queue, background mode in stages, duplicate
  detection across libraries, citations that follow deleted duplicates, backups.
- **Zotero plugin** with context menus; MCP server for Claude Desktop.
- Interface and manual in English and German.

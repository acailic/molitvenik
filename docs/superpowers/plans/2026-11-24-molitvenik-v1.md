# Molitvenik v1 — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the public static site with the transcribed prayer book, and the pipeline and verification tools that produce and check the text.

**Architecture:** A Python package (`tools/molitvenik_tools`, run with `uv`) turns scanned pages into `data/prayers.json` through OCR, correction and cleaning steps, and produces the material reviewers use to verify the text. A dependency-free ES-module site (`index.html`, `style.css`, `app/`) loads that one JSON file. Ten work packages are built in parallel by separate agents on disjoint files; the coordinator owns shared files and integration.

**Tech stack:** Python ≥ 3.11 (uv, Pillow, numpy, pytest, ruff; Tesseract 5 and Hunspell as system binaries), browser ES modules with Node's built-in `node --test`, GitHub Pages.

## Global constraints

* Spec: `docs/superpowers/specs/2026-11-24-molitvenik-design.md`. Its numbers are binding: half resolution, Tesseract `-l srp --psm 3 -c tessedit_load_sublangs=`, red when the red share of ink is ≥ 0.5, length tiers `< 150`, `150–450`, `> 450` words.
* Python: `requires-python >= 3.11`; no syntax newer than 3.11. Dependencies limited to Pillow and numpy; Tesseract and Hunspell are called through `subprocess`.
* Site: no build step, no dependencies, no external requests. Pure modules (`app/text.js`, `app/search.js`, `app/filters.js`, `app/random.js`) must not touch the DOM or `localStorage`.
* The PDF, page images and `build/` are never committed.
* Each agent creates and modifies only the files listed under **Files** in its package. Shared files (`pyproject.toml`, `package.json`, `tests/conftest.py`, `tests/fixtures/**`, `data/lexicon-allowlist.txt`, `tools/molitvenik_tools/__init__.py`) belong to the coordinator.
* Tests are written first and must pass before a package is reported done: `uv run pytest`, `uv run ruff check tools tests`, `npm test`, `npm run check`.
* Book page = PDF page + 3. Archive leaf = PDF page − 1. Text pages are PDF pages 8–177.
* Text is reproduced exactly as printed, misprints included; the only exceptions are the two corrections from the book's corrections page (spec, section 2).
* Nothing is committed by package agents; the coordinator commits.

---

## File map and ownership

| File | Purpose | Owner |
|---|---|---|
| `tools/molitvenik_tools/images.py` | image helpers: load, resize, greyscale, red share of a word box, strip cutting | tools-ocr |
| `tools/molitvenik_tools/fetch.py` | download Archive page images (or render a PDF) into `build/pages/` | tools-ocr |
| `tools/molitvenik_tools/ocr.py` | page images → per-page OCR JSON | tools-ocr |
| `tools/molitvenik_tools/iaocr.py` | the Archive's own OCR (DjVu XML) → per-page line files | tools-ocr |
| `tools/molitvenik_tools/overrides.py` | apply `data/ocr-overrides.json` to OCR pages | tools-clean |
| `tools/molitvenik_tools/clean.py` | OCR pages → cleaned blocks (`build/clean/book.json`) | tools-clean |
| `tools/molitvenik_tools/assemble.py` | cleaned blocks + `data/structure.toml` → `data/prayers.json` | tools-assemble |
| `tools/molitvenik_tools/checks.py` | text checks over the cleaned book and `prayers.json` | tools-assemble |
| `tools/molitvenik_tools/review.py` | reviewer material: hints, strips, comparison, collecting corrections | tools-review |
| `tools/molitvenik_tools/cli.py` | `uv run molitvenik <step>` | tools-cli |
| `app/text.js` | script folding for search | app-text-search |
| `app/search.js` | search index, query, highlighting | app-text-search |
| `app/filters.js` | facets, filtering, length tiers, filter state in the address | app-filters-random |
| `app/random.js` | random draw without immediate repeat | app-filters-random |
| `app/router.js`, `app/views.js`, `app/main.js` | routing, rendering, wiring | app-ui |
| `index.html`, `style.css` | page and look | app-ui |
| `data/structure-1.toml` | curated sections 1–6 (units, anchors, titles, authors, tags) | structure-1 |
| `data/structure-2.toml` | curated sections 7–12 | structure-2 |
| `tests/fixtures/site/prayers.sample.json` | small valid `prayers.json` for the UI package | coordinator |
| `data/ocr-overrides.json`, `data/structure.toml` | final curated files, assembled by the coordinator from the packages' output and the verification rounds | coordinator |

Python tests live in `tests/test_<module>.py`; browser tests in `tests/site/<module>.test.js`.

---

## Contracts

### C1. Paths under the repository root

| Path | Written by | Read by |
|---|---|---|
| `build/pages/nNNN_w2000.jpg` (NNN = leaf) | fetch | ocr, review |
| `build/ocr/p-NNN.json` (NNN = PDF page) | ocr | overrides, clean, review |
| `build/ia-ocr/p-NNN.json` | iaocr | review |
| `build/review/img/p-NNN.png` (half-resolution page) | ocr | review |
| `build/clean/book.json` | clean | assemble, checks |
| `data/prayers.json` | assemble | site, checks |
| `build/review/hints/p-NNN.txt`, `build/review/strips/…`, `build/review/diff.json` | review | reviewers |

### C2. OCR page file — `build/ocr/p-NNN.json`

Shape is fixed by the fixtures in `tests/fixtures/ocr/`. Coordinates are pixels of the half-resolution page image (`build/review/img/p-NNN.png`).

```
{ "page": 110,                 // PDF page number
  "book_page": 113,            // page + 3
  "width": 1055, "height": 1639,
  "source_width": 2019, "source_height": 3301,   // full-resolution image, for strips
  "lines": [
    { "kind": "content" | "header" | "footer" | "ornament",
      "cy": 312.5, "top": 299, "bottom": 380, "left": 135, "right": 858,
      "text": "бедни учествујем у Твојој бо-",       // words joined with one space
      "words": [
        { "text": "бедни", "left": 135, "top": 333, "width": 139, "height": 47,
          "conf": 96.4, "red": 0.03, "color": "black" | "red",
          "flags": ["low-confidence" | "latin-letters" | "has-inner-caps" | "differs:<name>"] } ] } ] }
```

Rules: lines are Tesseract's lines; neighbours whose centres lie within half the smaller of their median heights are merged into one line (words sorted by `left`). `kind`: `header` if `cy < 0.09 × height`; `footer` if `cy > 0.90 × height` and at most 3 tokens, one of them a 1–3 digit number, and no token with 3 or more Cyrillic letters; `ornament` if no token contains a Cyrillic letter; otherwise `content`. `red` = share of red ink pixels in the word box trimmed by a quarter of its height at top and bottom; ink = pixels with min(R,G,B) < 160; red ink = ink with R − G > 40. A second reading at 40 % scale and a third with `--psm 6` are aligned to the base tokens; a base token in a small disagreement (at most two tokens on either side) gets `differs:scale40` or `differs:psm6`.

### C3. Second reading — `build/ia-ocr/p-NNN.json`

`{ "page": 110, "lines": ["line text", …] }` — the Archive's OCR lines that contain a Cyrillic letter, in order. Shape is fixed by `tests/fixtures/ia-ocr/`.

### C4. Overrides — `data/ocr-overrides.json`

A JSON list, sorted by page: `{ "page": 110, "line": "<exact OCR line text>", "find": "<substring>", "replace": "<text>", "rubric": true, "note": "optional" }`. `line` must equal the `text` of exactly one content line of that page; `find` must occur exactly once in it. All pairs of one line are located in the line as read and applied together (replace right to left); the line is split into words again on spaces; a word keeps its box, colour and confidence when the word count is unchanged, otherwise new words inherit them from the first replaced word. An empty `replace` deletes. The optional `rubric` boolean (default: keep the colour) marks the replaced words red; it is how the book's own correction of page 86 („и" printed black, meant red) is applied. A missing line or `find` raises `OverrideError` with page, line and `find` in the message.

### C5. Cleaned book — `build/clean/book.json`

```
{ "pages": 170,
  "blocks": [
    { "kind": "paragraph",          // prayer text; lines joined, hyphens resolved
      "page_start": 110, "page_end": 111,
      "runs": [ { "text": "…", "rubric": false }, { "text": "(три пута)", "rubric": true } ] },
    { "kind": "rubric",             // a red line of its own: heading or instruction
      "page_start": 110, "page_end": 110, "text": "Песма 5." } ],
  "footnotes": [ { "page": 165, "book_page": 168, "text": "непријатељи моји." } ],
  "kept_hyphens": [ { "page": 110, "word": "Бого-Јавље" } ],
  "warnings": [ "…" ] }
```

Blocks are in reading order, across pages. A paragraph that continues over a page break is one block (`page_start` ≠ `page_end`). Rubric runs inside a paragraph are red words inside a line of black text; a line that is red throughout is a `rubric` block of its own.

### C6. Curated structure — `data/structure.toml`

```toml
[book]
title = "Православни молитвеник"
publisher = "Штампарија Српске патријаршије"
place = "Београд"
year = 1998

[[footnotes]]
page = 165                      # PDF page
starts_with = "непријатељи моји"

[[sections]]
id = "jutarnje"
title = "Молитве јутарње"        # as printed on the section's title page
first_page = 8                  # PDF page of the title page
last_page = 30

  [[sections.units]]
  slug = "pocetak"              # unit id = "<section id>__<slug>", ASCII
  title = "Почетак јутарњих молитава"
  heading = ""                  # red heading as printed, when the unit has one
  starts_with = "У име Оца"     # opening words of the first paragraph, when it has none
  part = ""                     # "Кондак 1", "Икос 7", "Песма 5" for parts, else ""
  author = ""                   # as the heading states it, e.g. "св. Макарије Велики"
  tags = ["u-svako-doba"]
  addressees = ["presveta-trojica"]
```

Exactly one of `heading` and `starts_with` is non-empty. A `heading` matches the first rubric block of the section after the previous unit whose text contains it; `starts_with` matches the first paragraph block whose text starts with it. Each anchor must match exactly once in its section and units must be in book order. Tags and addressees come from the vocabularies in the spec, section 4.

### C7. `data/prayers.json`

Shape is fixed by `tests/fixtures/site/prayers.sample.json`: `book`, `sections[]`, `units[]` with `id, section, order, title, bookHeading, part, author, pages, addressees, tags, words, length, blocks, footnotes`.

### C8. Python module interfaces

Every step module exposes `add_parser(subparsers)` and `run(args, root: pathlib.Path) -> int`, and can be run alone with `uv run python -m molitvenik_tools.<step> …`. Steps and arguments:

| Step | Arguments | Output |
|---|---|---|
| `fetch` | `--first 8 --last 177 --jobs 4` or `--pdf PATH` | `build/pages/` |
| `ocr` | `--first --last --jobs 8`, `--tessdata DIR` | `build/ocr/`, `build/review/img/` |
| `ia-ocr` | `--xml PATH` (download to `build/ia/djvu.xml` when omitted) | `build/ia-ocr/` |
| `clean` | — | `build/clean/book.json` |
| `assemble` | — | `data/prayers.json` |
| `check` | — | exit status |
| `review` | sub-commands `hints`, `strips`, `diff`, `collect` (package 4) | `build/review/` |

Functions other packages may import:

```python
# images.py
def red_share(box: dict, rgb: numpy.ndarray) -> float
def load_rgb(path) -> numpy.ndarray
def to_greyscale(rgb: numpy.ndarray) -> numpy.ndarray        # float 0..255, luma
def resize(rgb: numpy.ndarray, scale: float) -> numpy.ndarray  # LANCZOS

# ocr.py
def read_page(page: int, image_path, second_image_path, tessdata: str | None) -> dict   # C2 shape
def classify_line(line: dict, height: int) -> str
def group_lines(words: list[dict]) -> list[dict]

# overrides.py
class OverrideError(ValueError)
def apply_overrides(page: dict, overrides: list[dict]) -> dict     # returns a corrected copy
def apply_spans(line: dict, spans: list[tuple[int, int, str]]) -> None

# clean.py
def clean_book(pages: list[dict], footnotes: list[dict]) -> dict   # C5 shape
def join_hyphen(left: str, right: str) -> tuple[str, bool]         # joined word, kept_hyphen

# assemble.py
class StructureError(ValueError)
def load_structure(paths: list[pathlib.Path]) -> dict
def assemble(book: dict, structure: dict) -> dict                  # C7 shape
def length_of(words: int) -> str

# checks.py
def run_checks(prayers: dict, book: dict) -> list[str]             # empty list = clean
def latin_inside_words(text: str) -> list[str]

# review.py
def write_hints(root, allowlist: set[str], hunspell: str | None) -> list[pathlib.Path]
def marked_lines(page: dict, second: list[str], hints: set[int]) -> list[int]
def write_strips(root, pages: list[int]) -> list[pathlib.Path]
def diff_against(page: dict, lines: list[str]) -> list[dict]
def collect(root, corrections_dir: pathlib.Path) -> dict           # {"valid": [...], "invalid": [...]}
```

### C9. Browser module interfaces

```js
// text.js
export function toLatin(text)        // Serbian Cyrillic → Latin (љ→lj, њ→nj, џ→dž, …)
export function foldAscii(text)      // Latin with diacritics → plain ASCII (č ć→c, š→s, ž→z, đ→dj, dž→dz)
export function hasCyrillic(text)
export function searchKey(text)      // lowercase → toLatin when Cyrillic → foldAscii → NFKC
export function foldMap(text)        // { folded, starts }: starts[i] = index in `folded` where character i of `text` begins

// search.js
export function buildIndex(units)    // [{ id, title, author, section, titleKey, authorKey, bodyKey, snippet }]
export function search(index, key)   // key = searchKey(query); [] when key is ""; [{ id, field, position }]
export function highlight(text, key) // [{ text, match }] segments of the original text

// filters.js
export const FACETS                  // [{ id, label, values: [{ id, label }] }] for odeljak, povod, kome, duzina
export function lengthOf(words)
export function applyFilters(units, state)
export function randomPool(units, state)   // passing units; without a duzina chip, also drops "duga"
export function parseFilterState(query)    // "povod=pokajanje&duzina=kratka" → state
export function formatFilterState(state)   // state → "povod=pokajanje&duzina=kratka" or ""

// random.js
export function pickRandom(pool, excludeId, rng = Math.random)

// router.js
export function parseHash(hash)      // { view: "home" | "prayer" | "section", id, query, state }
export function buildHash(route)
export function onRouteChange(callback)
```

`state` is `{ odeljak: [], povod: [], kome: [], duzina: [] }` of value ids; chips inside a facet are *or*, facets are *and*. `formatFilterState(parseFilterState(s)) === s` for every canonical string.

---

## Package 1 — tools-ocr

**Files:** create `tools/molitvenik_tools/images.py`, `fetch.py`, `ocr.py`, `iaocr.py`; tests `tests/test_images.py`, `tests/test_ocr.py`, `tests/test_iaocr.py`, `tests/test_fetch.py`.
**Consumes:** C1, C2, C3, C8. **Produces:** C2 and C3 files; `images.red_share` for package 4.
**Reference:** `/Users/aleksandarilic/ZCodeProject/scratch-prayer-book-scripts/ocr_pages_ia.py`, `fetch_ia_pages.sh`, `ia_ocr_lines.py` are working prototypes. Port them; do not copy blindly: they use ImageMagick through `subprocess` — do the image work with Pillow instead.

Requirements:

- [ ] `fetch`: Archive item `pravoslavni-molitvenik`, URL `https://archive.org/download/pravoslavni-molitvenik/page/n{leaf}_w2000.jpg`, leaf = page − 1; skip files that exist and are not empty; retry three times; parallel downloads; write the source into `build/pages/SOURCE.txt` (`archive` or the PDF path). With `--pdf PATH`, render the pages with `pdftoppm -r 150 -png` into `build/pages/p-NNN.png` instead; when `pdftoppm` is not installed, exit with a message that names the missing program.
- [ ] `ocr`: base reading = half resolution of the Archive image (scale 0.5), greyscale, `-l srp --psm 3 -c tessedit_load_sublangs= -c tessedit_create_tsv=1`; second reading at 0.4; third at 0.5 with `--psm 6`. When `build/pages/SOURCE.txt` names a PDF (the fallback source), the 150 DPI page is upscaled 2× instead and there is no second scale: the second reading then uses `--psm 6` only. If `--tessdata` is given, also pass `--tessdata-dir`; the model file `srp.traineddata` is looked up there first, else Tesseract's default path is used.
- [ ] Colour, flags, line kinds and merging exactly as C2. Lines are sorted by `cy`.
- [ ] `source_width` and `source_height` are the full-resolution image's size. The half-resolution page is also written to `build/review/img/p-NNN.png`.
- [ ] `iaocr`: parse DjVu XML with `xml.etree.ElementTree.iterparse`; the n-th `OBJECT` (from 0) is leaf n; keep lines with a Cyrillic letter; drop the line when it consists only of the running title. Missing `--xml` downloads `https://archive.org/download/pravoslavni-molitvenik/Pravoslavni%20molitvenik_djvu.xml` to `build/ia/djvu.xml`.
- [ ] All three steps are parallel across pages (Processes, default `--jobs 8`) and idempotent.

Tests (write first; use synthetic data, no network, no Tesseract):

- [ ] `test_images.py`: `red_share` returns 0.0 for a black word on white, 1.0 for a red word (R=190, G=B=40), about 0.5 for a box half red half black, 0.0 for an empty box; `to_greyscale` of pure red gives a value below 110.
- [ ] `test_ocr.py`: `group_lines` keeps Tesseract's lines and merges two lines whose centres differ by less than half the smaller median height, sorting the merged words by `left`; it does not merge two lines one line-pitch apart even when one word has a tall box. `classify_line` on the fixtures: page 127 has one `header` and no `footer`; page 165 ends with an `ornament` line (`• . •,`). For every fixture page: every line has `text` equal to its words joined by one space, `kind` in the four allowed values, and content lines contain a Cyrillic letter.
- [ ] `test_iaocr.py`: on a small DjVu XML written in the test (two `OBJECT`s, each with a `LINE` of `WORD`s), files `p-001.json` and `p-002.json` are produced with the right lines; a line without Cyrillic is dropped; the result equals `tests/fixtures/ia-ocr/p-110.json` for a synthetic input shaped like it.
- [ ] `test_fetch.py`: the URL for page 9 is `…/page/n8_w2000.jpg`; an existing non-empty file is not downloaded again (monkeypatch the downloader); a failed download is retried three times and then raises.

Run: `uv run pytest tests/test_images.py tests/test_ocr.py tests/test_iaocr.py tests/test_fetch.py -q`, `uv run ruff check tools tests`. Real run by the coordinator on the book.

## Package 2 — tools-clean

**Files:** create `tools/molitvenik_tools/overrides.py`, `clean.py`; tests `tests/test_overrides.py`, `tests/test_clean.py`.
**Consumes:** C2, C4, C5, C6 (only `[[footnotes]]`), C8. **Produces:** `build/clean/book.json`; `apply_overrides` for package 4.
**Reference:** `/Users/aleksandarilic/ZCodeProject/scratch-prayer-book-scripts/apply_corrections.py`.

Requirements:

- [ ] `overrides.apply_overrides(page, overrides)` per C4, raising `OverrideError`. The `line` step command `clean` reads `data/ocr-overrides.json` and fails on the first error.
- [ ] Cleaning works on the whole book in page order and emits one `book.json`:
  - Header, footer and ornament lines are dropped.
  - The footnote line (page and `starts_with` from structure) is moved to `footnotes`.
  - Tokens without a letter or digit that stand alone (`·`, `~`, `|`, `=`, `–`, `—`, `_`) are removed.
  - A line whose words are all red is a `rubric` block. Otherwise the line's words form runs: consecutive words of the same colour, joined with one space.
  - A new paragraph starts at the first content line of a page when the previous page's last line does not end with a hyphen, and at a line whose first word starts at least 45 px (half-resolution pixels) right of the page's leftmost content word. Indent is measured per page: `left_of_first_word − page_min_left ≥ 45`.
  - Lines of one paragraph are joined: a token ending in `-` followed by a lowercase continuation loses the hyphen; a hyphen followed by an uppercase continuation is kept and recorded in `kept_hyphens`; a hyphen at the end of a paragraph is removed. Continuation across a page break works the same way.
  - The two corrections of the corrections page are applied by data, not by code: they are entries of `data/ocr-overrides.json` (page 22: delete the struck-through tokens; page 83: mark „и" as a rubric). For the second, an override may carry `"rubric": true` to turn the replaced words red: extend C4 with an optional boolean field `rubric` (absent = keep colour).
  - Small-caps lines: words flagged `has-inner-caps` are reported in `warnings`; they are corrected through overrides, not automatically.
- [ ] `kept_hyphens` and `warnings` are lists of strings/dicts, deterministic order.

Tests:

- [ ] `test_overrides.py`: one replacement keeps box and colour; two pairs on one line are both applied (the fixture case: `{"line": "ђао, jep „eBO једем Твоје", "find": "ђао,", …}` and `"jep"` and `"„eBO"`); a missing word is inserted (`"си"` → `"си обе-"`) and inherits the colour; deletion with empty `replace` removes the word; `OverrideError` when the line does not exist, exists twice, or `find` is absent or occurs twice; `"rubric": true` turns the word red.
- [ ] `test_clean.py`: hyphen before lowercase is removed, before uppercase is kept and recorded, at a paragraph end removed; a paragraph continuing over a page break is one block with the right `page_start` and `page_end`; artefact tokens are removed; a fully red line becomes a `rubric` block; a line with an inline red passage gives two runs with `rubric` true and false; the header of page 127 is not in the output; the footnote of page 165 is in `footnotes` and not in `blocks`; an indented line starts a paragraph.

Run: `uv run pytest tests/test_overrides.py tests/test_clean.py -q`, `uv run ruff check tools tests`.

## Package 3 — tools-assemble

**Files:** create `tools/molitvenik_tools/assemble.py`, `checks.py`; tests `tests/test_assemble.py`, `tests/test_checks.py`.
**Consumes:** C5, C6, C7, C8. **Produces:** `data/prayers.json`; `StructureError`; `run_checks`.

Requirements:

- [ ] `load_structure(paths)` merges one or more structure TOML files, read with the standard library's `tomllib`. Validate: unique section ids, unique unit ids, ASCII slugs, tags and addressees from the spec's vocabularies, exactly one of `heading` / `starts_with`.
- [ ] `assemble(book, structure)`: for each section take the blocks with `page_start` between `first_page` and `last_page`; drop the section's title line (the rubric block equal to the section title, with punctuation normalised); cut units at their anchors as C6; the unit's anchor rubric block is removed from the blocks and becomes `bookHeading` (full rubric text) when `heading` is set; `title`, `part`, `author`, `tags`, `addressees` come from the structure; `pages` = [first block's `page_start` + 3, last block's `page_end` + 3]; `words` counts letters-and-digits tokens of the prayer runs only (rubric blocks excluded, rubric runs included); `length` by `length_of`. Raise `StructureError` naming the section and anchor when an anchor matches zero or several times, when units are out of order, or when a section has blocks before its first unit other than the title.
- [ ] Every block of every section must belong to exactly one unit (no text lost, none duplicated): assert it.
- [ ] `checks.run_checks(prayers, book)` returns a list of problems; empty when clean: no Latin letters inside a word that has Cyrillic letters; no token that is only a spacing artefact; no word ending in `-` at the end of a block; no `has-inner-caps` left (the cleaner's warnings are passed in as `book["warnings"]` and count); every unit has a title, a section, at least one tag and at least one paragraph or rubric block; total `words` within 5 % of the letter-digit tokens of the cleaned book; balanced parentheses and „ " per unit.

Tests:

- [ ] `test_assemble.py`: a small synthetic book with two sections and three units: titles dropped, anchors cut, `bookHeading` taken from the rubric, `pages` and `words` right, `length` right; `StructureError` for an anchor matching twice; an anchor matching zero; blocks before the first unit.
- [ ] `test_assemble.py`: `length_of(149) == "kratka"`, `150 → "srednja"`, `450 → "srednja"`, `451 → "duga"`.
- [ ] `test_checks.py`: each check fires on a crafted bad input and stays silent on `tests/fixtures/site/prayers.sample.json` with a matching clean book.

Run: `uv run pytest tests/test_assemble.py tests/test_checks.py -q`, `uv run ruff check tools tests`.

## Package 4 — tools-review

**Files:** create `tools/molitvenik_tools/review.py`; tests `tests/test_review.py`.
**Consumes:** C2, C3, C8, `images.py` from package 1 (import it; if it does not exist yet, write your tests against the documented `red_share` and keep your own private copy of the strip-cutting code inside `review.py`). **Produces:** reviewer material under `build/review/`.
**Reference:** `/Users/aleksandarilic/ZCodeProject/scratch-prayer-book-scripts/`: `make_hints.py`, `prepare_adjudication.py`, `collect_corrections.py`.

Requirements:

- [ ] `review hints`: per page `build/review/hints/p-NNN.txt`: first line `PDF page N (book page N+3). K content lines.`, then `NN| line text` for every content line, then `Suspected words:` with at most 45 entries `NN "word" (reason)`, ordered by priority: Latin letters; a token both other readings disagree with; unknown to the dictionary and not in `data/lexicon-allowlist.txt`; a digit inside a word; a capital inside the word; one reading differs; a rare mid-sentence capital. Tokens with fewer than two letters are never listed. Continuations of a hyphenated word are not looked up. Hunspell is called once per run with `-d <base> -l -i UTF-8`; when the binary is missing, dictionary reasons are skipped and the fact is printed.
- [ ] `review marked`: writes `build/review/marked.json`: `{ "NNN": [line indexes] }` — content lines that carry a hint other than `low-confidence`, or on which the second reading (C3) disagrees in words, letter case or punctuation. Comparison: tokens normalised (punctuation stripped from both ends, Latin look-alikes mapped to Cyrillic, lowercased) are aligned with `difflib.SequenceMatcher`; a disagreement counts when it spans at most two tokens on either side.
- [ ] `review strips --pages 110,127`: for each page one image `build/review/strips/p-NNN.png` and one text `build/review/strips/p-NNN.txt`. Each numbered strip shows the marked line tinted yellow and its neighbours whole, cut from the full-resolution image (`source_width × source_height`) at 0.72 zoom, the full text column wide; the text file lists `NN| A: <OCR line>` and `differs: A [tokens] / B [tokens]`.
- [ ] `review diff --transcriptions DIR`: the same comparison against reviewer transcriptions `{ "page": N, "lines": [...] }`; writes `build/review/diff.json`.
- [ ] `review collect --corrections DIR`: validates per-page correction files `{ "page": N, "corrections": [{ "line", "find", "replace", "note" }] }` as C4 (line exists once, `find` once inside it, change small: one word to one or two words or edit distance ≤ a third of `find`), writes `build/review/corrections.json` (valid, sorted) and prints every invalid entry with the reason.

Tests (synthetic pages and images made in the test; real fixtures where useful):

- [ ] Hints: `review2` fixture page 127 yields `Beuepe`-like Latin tokens first (use a synthetic page), a word in the allowlist is not reported as unknown, a hyphen tail is not looked up, at most 45 hints.
- [ ] Marked lines: a second reading with one changed word marks that line; a reading with an extra line before the text marks nothing on its own; a difference of letter case or of `!` vs `.` marks the line; a run of five different tokens marks nothing.
- [ ] Strips: on a synthetic 400×600 image with three lines, the output image exists, has the tinted band at the marked line, and the text file has one `NN|` entry per marked line.
- [ ] Collect: the three invalid cases and the two-corrections-one-line case; output sorted by page.

Run: `uv run pytest tests/test_review.py -q`, `uv run ruff check tools tests`.

## Package 5 — app-text-search

**Files:** create `app/text.js`, `app/search.js`; tests `tests/site/text.test.js`, `tests/site/search.test.js`.
**Consumes:** C7 (unit shape), C9. **Produces:** `searchKey`, `buildIndex`, `search`, `highlight`.

Requirements:

- [ ] `toLatin`: љ lj, њ nj, џ dž, ђ đ, ћ ć, ч č, ш š, ж ž, and the single-letter pairs (а a, б b, в v, г g, д d, е e, ј j, з z, и i, к k, л l, м m, н n, о o, п p, р r, с s, т t, у u, ф f, х h, ц c, а а); uppercase maps to uppercase. Digraphs are replaced before single letters.
- [ ] `foldAscii`: č ć → c, š → s, ž → z, đ → dj, dž → dz; uppercase folded after lowercasing.
- [ ] `searchKey`: lower-case, strip combining marks, NFKC; Cyrillic input goes through `toLatin` first. `searchKey("помилуј") === searchKey("pomiluj") === "pomiluj"`; `searchKey("оче наш") === "oce nas"`; `searchKey("Oče naš") === "oce nas"`; `searchKey("човек") === searchKey("čovek") === "covek"`; `searchKey("ђаво") === "djavo"`; `searchKey("џабе") === "dzabe"`; `searchKey("љубав") === "ljubav"`.
- [ ] `foldMap(text)`: `starts` has one entry per code point of `text` and `starts[0] === 0`.
- [ ] `buildIndex(units)`: `titleKey = searchKey(title)`, `authorKey`, `bodyKey = searchKey(title + " " + author + " " + all block and footnote texts)`, `snippet` = first 120 characters of the prayer text.
- [ ] `search(index, key)`: all units where `key` is a substring of `titleKey`, `authorKey` or `bodyKey`; result sorted by field (title, author, body) then by the unit's order; empty key returns `[]`.
- [ ] `highlight(text, key)`: splits the original text into `{ text, match }` segments; with key `"pomiluj"` on `"Господе помилуј нас"` the match covers exactly `помилуј`; with no match returns one segment.

Tests: all of the above, each as its own test, plus a test that every exported function works when `globalThis.document` is undefined.

Run: `npm test`, `npm run check`.

## Package 6 — app-filters-random

**Files:** create `app/filters.js`, `app/random.js`; tests `tests/site/filters.test.js`, `tests/site/random.test.js`.
**Consumes:** C7, C9. **Produces:** `FACETS`, `lengthOf`, `applyFilters`, `randomPool`, `parseFilterState`, `formatFilterState`, `pickRandom`.

Requirements:

- [ ] `FACETS` in this order with these labels: `odeljak` „Одељак" (values from the sections, labels = section titles), `povod` „Повод", `kome` „Кому је упућена", `duzina` „Дужина". Value labels: pokajanje „покајање", zahvalnost „захвалност", zastita „заштита", miran-san „миран сан", za-pokojne „за покојне", uz-obrok „уз оброк", u-nevolji „у невољи", u-svako-doba „у свако доба"; gospod-isus-hrist „Господу Исусу Христу", bog-otac „Богу Оцу", presveti-duh „Пресветом Духу", presveta-trojica „Пресветој Тројици", presveta-bogorodica „Пресветој Богородици", andjeo-cuvar „Анђелу чувару", casni-krst „Часном крсту"; kratka „кратка (до 1 мин)", srednja „средња (1–3 мин)", duga „дуга (преко 3 мин)". `makeFacets(sections)` returns `FACETS` with the `odeljak` values filled from `sections`.
- [ ] `applyFilters`: chips *or* within a facet, *and* across facets; empty state returns all units.
- [ ] `randomPool`: units passing the filters; when the state selects no `duzina`, units of length `duga` are left out.
- [ ] `parseFilterState` / `formatFilterState`: unknown facet or value ids are dropped; order of facets follows `FACETS`; within a facet values are sorted; empty state formats to `""`.
- [ ] `pickRandom(pool, excludeId, rng)`: never returns `excludeId` when the pool has another unit; with a one-unit pool returns it; returns `null` for an empty pool; uses `rng()` once.

Tests: one test per requirement; `lengthOf` at 149, 150, 450, 451.

Run: `npm test`, `npm run check`.

## Package 7 — app-ui

**Files:** create `index.html`, `style.css`, `app/router.js`, `app/views.js`, `app/main.js`; test `tests/site/router.test.js`.
**Consumes:** C7, C9 (import the pure modules; while they are being written by other agents, code against the signatures — do not create those files). Local data for development: `tests/fixtures/site/prayers.sample.json`.
**Load first:** the `frontend-design:frontend-design` skill, and follow it for the look.
**Produces:** the site.

Requirements:

- [ ] Routes `#/`, `#/molitva/<id>`, `#/odeljak/<id>`, with filter state in the query of the home route (`#/?povod=pokajanje`). `parseHash` and `buildHash` are pure and tested; `onRouteChange` calls back on `hashchange` and once at start.
- [ ] Home: „Случајна молитва" button (draws from `randomPool(units, state)` excluding the unit on screen, then navigates to it), search field, filter chips for the four facets (toggle; „Поништи филтере" link), result count, and a list: the twelve sections by default, matching units otherwise. Search input is debounced by 150 ms and stored in the address as `q`.
- [ ] Prayer view: title, section link, author line when present, blocks (rubric in red, as in the book), footnote at the end, previous and next links within the section, a „Копирај линк" button (uses `navigator.clipboard`, falls back to a temporary `textarea`), word count and reading time.
- [ ] Section view: table of contents of its units, then every unit in order.
- [ ] Search results use `search` and show the snippet with `highlight`.
- [ ] Font size control with three steps, persisted under `molitvenik.font` in `localStorage`; colour scheme follows `prefers-color-scheme` with no flash; every interactive element is reachable by keyboard; `lang="sr"`; one `<h1>`; focus styles visible.
- [ ] All text inserted into the DOM goes through one escaping helper.
- [ ] `index.html` loads `app/main.js` as a module and has a `<noscript>` message. `data/prayers.json` is fetched with a relative URL.

Test: `tests/site/router.test.js` for `parseHash` / `buildHash` (home, home with query, prayer, section, unknown route falls back to home, round trip).

Run: `npm test`, `npm run check`; then serve the folder with `python3 -m http.server` (module imports do not work from `file://`) and look at it in a browser at 390 px and 1280 px width.

## Package 8 — structure-1

**Files:** create `data/structure-1.toml`. Nothing else.
**Consumes:** C6; the page texts: `/Users/aleksandarilic/ZCodeProject/scratch-prayer-book/review2/txt/p-NNN.txt` (OCR lines, numbered; ignore the `Suspected words` part) for PDF pages 8–154; the list of red headings in `…/review2/adj-ia/diff.json` is **not** needed — use the page texts.
**Produces:** `[book]`, `[[footnotes]]`, and sections 1–6 of C6 with every unit.

Requirements:

- [ ] Sections, ids, titles and page ranges exactly as in the spec, section 2. The file starts with the `[book]` table; footnotes belong to package 9's file.
- [ ] One unit per red heading, and one per kontakion, ikos and song in the akathists and the canon. Untitled short prayers inside a rule get their own unit with `starts_with` (for example „Царе небески", „Свети Боже", „Оче наш" in the morning rule).
- [ ] `heading` is a short, exact substring of the printed red heading, long enough to be unique in its section: `Молитва прва`, `Кондак 7`, `Песма 5`, `Псалам 50`, `Символ вере`. Copy the words from the OCR text; where the OCR of a heading is visibly garbled, use the shortest correct leading words.
- [ ] `title`: for titled units the part of the heading before the comma or colon (`Молитва прва`, `Кондак 7`, `Песма 5`, `Пре ручка`); for untitled units the first words of the prayer (`Царе небески`). `part`: `Кондак N`, `Икос N`, `Песма N` for those units, else "". `author`: exactly as the heading states (`св. Макарије Велики`, `св. Јован Златоуст`, `св. Василије Велики`, `св. Јован Дамаскин`, `св. Симеон Метафраст`, `св. Симеон Нови Богослов`, `св. Антиох`, `св. Анђео чувар`), else "".
- [ ] `tags` and `addressees`: read each prayer and assign from the vocabularies only. Every unit has at least one tag. `tags` describe the occasion: pokajanje (repentance, confession of sin), zahvalnost (thanksgiving, praise), zastita (protection from evil thoughts, temptation, defilement), miran-san (said before sleep), za-pokojne (for the departed), uz-obrok (before or after a meal), u-nevolji (in sorrow, trouble, sickness), u-svako-doba (any time; also for parts of akathists and canons). `addressees`: who the prayer is addressed to; `casni-krst` for the prayer to the Cross in the evening rule.
- [ ] Units in book order; slugs short ASCII (`molitva-1`, `kondak-1`, `ikos-7`, `pesma-5`, `psalam-50`, `simvol-vere`, `care-nebeski`).

Check before reporting: every `heading` occurs in exactly one line of the section's page texts and in order; every `starts_with` is the beginning of a line.

## Package 9 — structure-2

**Files:** create `data/structure-2.toml`. Same rules as package 8, for sections 7–12 (PDF pages 155–177), **plus** `[[footnotes]]` with `page = 165`, `starts_with = "непријатељи моји"`, and `[book]` is **not** repeated.

## Package 10 — tools-cli

**Files:** create `tools/molitvenik_tools/cli.py`; tests `tests/test_cli.py`.
**Consumes:** C8. The step modules are written by other agents in parallel; write `cli.py` against the contract (`add_parser`, `run(args, root)`), importing lazily inside each dispatch so that `--help` works while a module is still missing.
**Produces:** `uv run molitvenik <step>`.

Requirements:

- [ ] `molitvenik --help` lists the steps of C8 with one line each; `molitvenik <step> --help` shows the step's arguments.
- [ ] `--root PATH` (default: the directory containing `pyproject.toml`, found by walking up from the current directory) is added to every step and passed as `root`.
- [ ] Exit status is the step's return value; `KeyboardInterrupt` exits 130; a step raising `OverrideError` or `StructureError` prints the message and exits 2.
- [ ] Missing module → message `step "<name>" is not available yet` and exit 3.

Tests: `main(["--help"])` returns 0 and prints the steps; `--root` resolves; a fake step module registered in a table returns its value; a missing module gives 3.

Run: `uv run pytest tests/test_cli.py -q`, `uv run ruff check tools tests`.

---

## Coordinator tasks (not delegated)

- [ ] Create `tests/fixtures/site/prayers.sample.json` before launching package 7.
- [ ] Reconcile this plan with the blueprint of the code architect when it arrives.
- [ ] Launch the ten packages in parallel; review each result (`uv run pytest`, `uv run ruff check tools tests`, `npm test`, `npm run check`); commit per package with conventional commits.
- [ ] Run the real pipeline: `fetch`, `ocr`, `ia-ocr`, then the verification rounds: marked lines → strips → adjudication by reviewers → `review collect` → `data/ocr-overrides.json` → `clean` → comparison again → second round on what remains.
- [ ] Measurement: the blind transcriptions of the 31-page sample against the final text; adjudicate; write the numbers into the README.
- [ ] Merge `data/structure-1.toml` and `data/structure-2.toml` into `data/structure.toml`; `assemble`; `check`; fix anchors that no longer match after corrections.
- [ ] Verify the site in a browser at 390 px and 1280 px: every view, every facet, search in Cyrillic, in Latin, without diacritics, random draw, shared addresses.
- [ ] Independent code review of the whole diff; fix; re-run everything.
- [ ] Publish: create the public repository, push `main` and `feat/v1`, open and merge the pull request, enable Pages from the root of `main`, check the live site and its headers, write the measured numbers into the README.

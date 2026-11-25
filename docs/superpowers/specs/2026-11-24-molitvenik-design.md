# Molitvenik — design

Date: 2026-11-24 (first version approved the same day; revised after research and measurement —
see section 10 for every change and its reason)

## 1. Goal

A public, static web site where anyone can get a prayer from *Православни молитвеник*
(Serbian Orthodox prayer book, Belgrade 1998) in one of three ways:

1. a random prayer,
2. a prayer chosen through filters,
3. a prayer found through search.

The text of the prayers is the product. A wrong or garbled word is a visible defect,
so the quality of the transcription and its verification are part of the design, not an
afterthought.

## 2. Source

| | |
|---|---|
| Title | Православни молитвеник |
| Publisher | Штампарија Српске патријаршије — Београд |
| Year | 1998 (the title page reads „хиљаду деветсто деведесет осме") |
| Blessing | with the blessing of Patriarch Pavle and the Holy Synod of bishops |
| Maintainer's file | scanned PDF, 180 pages, 150 DPI, Cyrillic, no text layer |

Neither the PDF nor page images are committed or linked from the repository, apart from the
address the fetch tool needs (section 5).

### A better scan of the same book

The maintainer's PDF is byte-identical (same MD5 and SHA-1) to the source PDF of the Internet
Archive item `pravoslavni-molitvenik`. The Archive also holds a 600 ppi scan of the same copy
(2019 × 3301 pixels per page) and its own automatic OCR of it. Measured on four pages, OCR on
the Archive's pages at half resolution (about 300 ppi) made **no word error at all**, where
the 150 DPI pages had about one wrong word in a hundred. The transcription is therefore made
from the Archive's page images. The 150 DPI PDF stays supported as a fallback source.

### Typographic conventions

* Prayer text is printed in black; headings and instructions (rubrics) in red, sometimes
  inside the same line.
* Some responses are printed in bold capitals and small capitals (ГОСПОДЕ ПОМИЛУЈ!). They are
  reproduced in ordinary sentence case (Господе помилуј!); bold is not modelled.
* One word carries a printed stress mark (Сȃм, page 172). Stress marks are not reproduced.
* The book has one footnote (page 168: „непријатељи моји."). It is kept with its prayer.
* The leading is tight: a band around one printed line always shows parts of its neighbours.
* The 600 ppi scan shows faint print of the reverse side of each leaf. OCR sometimes turns it
  into phantom letters; the pipeline must expect that.
* Section title pages carry a decorative header; some sections end with an ornament.

### What is published

The twelve prayer sections (PDF pages 8–177, book pages 11–180).

Not published: the introductory essay „О молитви" with its glossary (book pages 5–10), the
table of contents (181–182) and the corrections page (183). Book page = PDF page + 3.

The corrections page is applied to the text:

* Book page 25 (in „Молитва пета, светога Василија Великог"): delete the struck-through
  repeated passage — the last word of one line, the whole next line and the first word of
  the following line — so that the sentence reads „…они који празнују и неисказана сладост
  оних који гледају неизрециву лепоту лица Твога." A blue pen mark in the scanned copy
  covers the deleted words; the mark itself is not part of the printed text.
* Book page 86, line 7 of the text block: the word „и" in „Свети Боже; **и** по Оче наш:"
  is printed black and must be treated as a rubric (red).

### Sections

| # | id | Title as printed | Book pages | PDF pages |
|---|---|---|---|---|
| 1 | `jutarnje` | Молитве јутарње | 11–33 | 8–30 |
| 2 | `akatist-gospodu` | Акатист Преслатком Господу нашем Исусу Христу | 34–54 | 31–51 |
| 3 | `akatist-bogorodici` | Акатист Пресветој Владичици нашој Богородици | 55–74 | 52–71 |
| 4 | `kanon-bogorodici` | Молебни канон Пресветој Богородици | 75–85 | 72–82 |
| 5 | `pre-spavanja` | Молитве пре спавања | 86–108 | 83–105 |
| 6 | `pred-pricesce` | Молитвено правило пред Свето причешће | 109–157 | 106–154 |
| 7 | `posle-pricesca` | Молитве после Светог Причешћа | 158–164 | 155–161 |
| 8 | `jela` | Молитве пре и после јела | 165–168 | 162–165 |
| 9 | `svako-doba` | Молитва у свако доба | 169–170 | 166–167 |
| 10 | `ruzne-pomisli` | Молитва против ружних помисли | 171–172 | 168–169 |
| 11 | `oskvrnjenje` | Молитва против оскврњења | 173–178 | 170–175 |
| 12 | `pokojni` | Молитва за покојне | 179–180 | 176–177 |

About 17,000 words on 170 pages, 3,681 printed lines.

## 3. Scope

In scope for version 1:

* transcription of the twelve sections with the black/red distinction preserved,
* random prayer, filters, search (typed in Serbian Cyrillic or Latin), prayer view,
  section view, shareable addresses, font size control, automatic dark mode,
* the transcription pipeline and its verification tools, kept in the repository so that the
  text can be regenerated and re-checked.

Deliberately out of scope (can be added later if asked): prayer of the day, a
Cyrillic/Latin display toggle, favourites, offline use (PWA), analytics, comments, audio,
a build step or any server.

## 4. Content model

Two levels.

**Section** — one of the twelve parts of the book. It is a *rule*: an ordered sequence meant
to be read in book order.

**Unit** — one prayer: the text under one red heading („Молитва прва, светога Макарија
Великог", „Кондак 7", „Песма 5", „Псалам 50", „Символ вере", „Пре ручка"…). In the akathists
and the canon each kontakion, ikos and song is its own unit. Short untitled prayers that
follow one another inside a rule (e.g. „Царе небески", „Свети Боже") are separate units whose
boundaries are set by hand. Expected size: about 75 titled prayers plus 59 parts of the
akathists and the canon.

Unit boundaries are curated, not inferred: `data/structure-1.toml` and `data/structure-2.toml` list, for every section,
the units in order with the heading or the opening words that start each one. The assembler
starts a new unit when it meets that anchor. An anchor that does not match exactly once is
an error.

### Data file: `data/prayers.json` (generated, committed)

```
book       { title, publisher, place, year }
sections[] { id, order, title, pages: [first, last], units: [unitId…] }
units[]    { id, section, order,
             title,                 // display title, Cyrillic
             bookHeading,           // red heading as printed, or null
             part,                  // "Кондак 7" / "Икос 7" / "Песма 5", or null
             author,                // "св. Макарије Велики" when the book states it, or null
             pages: [first, last],  // book pages
             addressees[], tags[],  // curated
             words, length,         // "kratka" | "srednja" | "duga"
             blocks[],              // ordered content, see below
             footnotes[] }          // [{ marker, text }], almost always empty
```

A block is one of:

* `{ "kind": "rubric", "text": "Затим:" }` — a red instruction on its own line,
* `{ "kind": "paragraph", "runs": [{ "text": "…", "rubric": true? }] }` — prayer text, with
  inline red passages marked as rubric runs.

Idioms: ids are ASCII slugs (`[a-z0-9-]`); a unit id is `<section-id>__<unit-slug>` and never
changes once published, because addresses depend on it.

### Curated metadata

| Facet | Values |
|---|---|
| `tags` (povod) | `pokajanje`, `zahvalnost`, `zastita`, `miran-san`, `za-pokojne`, `uz-obrok`, `u-nevolji`, `u-svako-doba` |
| `addressees` (kome je upućena) | `gospod-isus-hrist`, `bog-otac`, `presveti-duh`, `presveta-trojica`, `presveta-bogorodica`, `andjeo-cuvar`, `casni-krst` |
| `length` (dužina) | derived from `words`: `kratka` under 150, `srednja` 150–450, `duga` over 450 (about 150 words a minute) |

The tag vocabulary is initial. It may gain or lose values while the units are being tagged,
which happens once, by reading the text. Every unit gets at least one tag.

## 5. Text pipeline

Tooling in `tools/`, Python run through `uv`. Everything downstream of the page images is
reproducible: the same images and the same curated files give the same `data/prayers.json`.

1. **Fetch.** Download the page images of the Archive item at width 2000 into `build/pages/`
   (Archive leaf = PDF page − 1). With `--pdf`, render the maintainer's PDF instead.
2. **OCR.** Each page at half resolution, greyscale; Tesseract 5, model `srp` from
   `tessdata_best`, page segmentation mode 3, and **the model's Serbian Latin sub-language
   switched off** (`-c tessedit_load_sublangs=`). Words with boxes and confidences.
3. **Second reading.** The Archive's own OCR of the same pages (DjVu XML), reduced to lines.
4. **Colour.** Each word is black or red according to the share of red ink pixels inside its
   box (red when at least half of the ink is red), done per word because red and black share
   a line („Онда: **Господе помилуј!** 40 пута").
5. **Lines.** Lines as Tesseract grouped them; neighbours that share a visual line are
   merged. The running title, the page number and ornament marks are set aside by position
   and content. The footnote of page 168 is recognised as such (small type after a large gap
   below a short rule).
6. **Corrections.** Apply `data/ocr-overrides.json`: per page, exact `find` / `replace` pairs
   that name the line they belong to. All pairs of one line are located in the line as it was
   read and applied together; the line is then split into words again and each word keeps its
   box and colour. A pair whose line or `find` cannot be found stops the pipeline. Every
   correction stays visible in git history.
7. **Clean.** Join the lines of a paragraph, including across a page break (the running
   title and page number sit between the two halves of a word). A hyphen at the end of a line
   is removed when the next line continues with a lowercase letter or when the paragraph ends
   there; it is kept when the next line starts with a capital letter, and every kept hyphen
   is listed for review. Remove the spacing artefacts of justified setting (`·`, `~`, `|`,
   `=` standing between words). A dash between words is print and stays; the dashes the OCR
   puts into the wide gaps of justified lines are removed one by one, by explicit corrections
   checked on the scan. Start a paragraph at a first-line indent; a centred
   line is a rubric block. Apply the two corrections of the book's corrections page.
8. **Assemble** units along the anchors in `data/structure-{1,2}.toml`, attach the curated
   metadata, and write `data/prayers.json`.

Intermediate files go to `build/`, which is ignored by git.

### Choices made by measurement

* **Half resolution.** Six scales were ranked over the whole book by their distance from the
  Archive's OCR, an independent reading of the same pages: 40 % 386 differing tokens,
  50 % 427, 66 % 476, 33 % 519, 100 % 538, 150 % 693 (of about 17,000). Half resolution is the
  base; 40 % is read as well and any word the two disagree about is flagged.
* **Sub-language off.** The `srp` model cannot emit a Latin letter, but its config loads the
  Serbian Latin model, and Tesseract retries doubtful words with it. With it on, 93 of 16,840
  words contained Latin letters; with it off, none.
* **No binarisation, no sharpening, no contrast stretch.** On the 150 DPI pages fifteen
  variants were tried and none beat plain 2× greyscale (binarisation was clearly worse). On
  the 600 ppi pages a contrast stretch does remove the phantom letters but damages red text
  („Богородичан" became „богороличан"), so it is not used.

### Known residual patterns of the OCR

They are expected, flagged, and settled in verification (section 6): a phantom „њ" or „љ"
before a word that follows a wide gap („њудостој", „љбо-"); „о" read as the digit „0"
(„ч0-"); a question mark read as „7" („утробе7"); a bold Ђ read as „Ђђ" („Ђђаволе"); mixed
case in small-caps lines.

## 6. Verification of the text

The text is checked by comparing independent readings, not by asking one reviewer to approve
it.

1. **Several readings of every line.** Our OCR (the base), the Archive's OCR of the same page,
   and a second pass of our OCR at 40 % scale. Our OCR and the Archive's OCR agree on 3,570 of
   the 3,681 lines of the book before any correction.
2. **Flags.** A line is marked when any two readings disagree or when one of its words carries
   a flag: unknown to the Serbian hunspell dictionary and not in `data/lexicon-allowlist.txt`,
   a digit inside a word, a capital letter inside a word, Latin letters.
3. **Adjudication.** For the marked lines only, the script cuts enlarged strips from the
   full-resolution page (the line tinted, its neighbours whole). A reviewer decides what the
   print shows and writes corrections as exact `find` / `replace` pairs against the OCR line.
   Strips at full resolution are easier to read than a whole page: on the first nine checked
   disagreements they settled every case.
4. **Apply and compare again.** Whatever still disagrees gets a second adjudication.
5. **Measurement by blind transcription.** Reviewers transcribe, from the 300 ppi image alone
   and never seeing the OCR text, a stratified random sample of 31 pages (fixed seed, two to
   seven pages per section). Their transcription is compared with the final text. Remaining
   disagreements are adjudicated and counted, separately for lines that had been marked before
   and lines that had not: the second count measures what the flags miss.

Acceptance: on lines that had not been marked, no more than one remaining word-level error per
1,000 words in the sample; letter case and punctuation differences are counted and reported
separately. If the sample shows more, the blind transcription is extended to the whole book.
The measured numbers are published in the README as they are.

Why not transcribe the whole book: a text-anchored review was tried first and found every
error on its two pilot pages, but took about a quarter of an hour per page, and the blind
transcribers worked at a similar pace. Transcribing all 170 pages would take many hours of
machine time; the sample is there to show whether that time would buy anything.

The dictionary (LibreOffice `sr`, `sr.aff` + `sr.dic`, 2019) is only a filter: on this text
about three quarters of what it flags are valid church words, and it accepts errors that form
another valid word („добара" is a valid form). Its suggestions are never applied.

## 7. Site

Static: `index.html`, `style.css`, ES modules in `app/`, data in `data/prayers.json`.
No build step, no dependencies, no external requests (system fonts only).

### Views

| Address | View |
|---|---|
| `#/` | Home |
| `#/molitva/<id>` | One prayer |
| `#/odeljak/<id>` | One section, read in order |

Home: a „Случајна молитва" button, a search field, filter chips, and a list — the twelve
sections by default, the matching prayers when searching or filtering.

Prayer view: title, section, author when the book states one, the text (rubrics in red as in
the book), the footnote when there is one, links to the previous and the next unit of the
section, a button that copies the address.

Section view: the whole rule in book order with a table of contents at the top.

Footer: attribution to the edition, a note that the text is a transcription and may contain
errors, a link for reporting them.

### Random

Draws from the set that passes the current filters. With no filters that is every unit except
long ones (over 450 words), so that the result can be read in about three minutes. It never
returns the unit shown immediately before.

### Filters

Four facets, shown as chips. Chips inside one facet combine as *or*, facets combine as *and*:
section, povod, addressee, length. Filter state lives in the address
(`#/?povod=pokajanje&duzina=kratka`), so a filtered list can be shared.

### Search

Searches unit titles, authors and text. The text is stored in Cyrillic only. At load, every
unit gets a second search key: the Cyrillic transliterated to Latin and then folded to plain
ASCII (љ → lj, њ → nj, џ → dz, ћ → c, ч → c, ш → s, ж → z, ђ → dj). The query goes through the
same function when it is Cyrillic and through the same folding when it is Latin. Matching is
a substring match on the folded text, so „помилуј", „pomiluj", „Gospode" and „oce nas" (for
„оче наш") all work.

This follows the prayer index of svetosavlje.org, which stores Cyrillic once and searches two
keys. Its ordinary site search converts the query letter by letter into Cyrillic instead, and
there „oce nas" fails to find „оче наш". Known limit, accepted: a folded „lj" also matches a
„л" followed by a „ј".

Results rank title matches first, then author, then text; inside each they follow the order
of the book. Matches are highlighted. With about
17,000 words no search library is needed.

### Small conveniences

Font size control (three steps, remembered in `localStorage`). Colour scheme follows
`prefers-color-scheme`.

### Look

Modelled on the book: warm paper white, near-black text, a blue-and-gold frame used as a
quiet accent, red for rubrics and titles, a readable serif. One column, generous leading,
designed for the phone first.

## 8. Repository and publishing

| | |
|---|---|
| Repository | `acailic/molitvenik`, public |
| Site | https://acailic.github.io/molitvenik/ served from the root of `main` |
| Local path | `ZCodeProject/molitvenik` |
| Code licence | MIT |

`README.md` is written in Serbian (Cyrillic) with a short English summary. It names the
edition and states that the rights to the text belong to their right holders and that the
site is non-commercial. The source PDF, page images and `build/` are not committed. The
fetch tool names the Archive item it reads from.

Compression and caching headers of GitHub Pages are checked on the live site after the first
deployment and recorded in the README; they are not assumed in advance.

Work happens on branches and is merged into `main` once reviewed, in small steps:
pipeline, transcription and verification, site, publishing.

## 9. Verification of the code

| What | How |
|---|---|
| Pipeline rules | `uv run pytest` (line grouping, colour, overrides, line joining, anchors, checks) |
| Site logic | `npm test`, which runs `node --test` on the pure modules (folding, search ranking, filters, random draw) and on the HTML of every view |
| JavaScript syntax | `node --check` on every module |
| Python lint | `uv run ruff check` |
| Text quality | the measurement of section 6, reported with numbers |
| The site itself | opened in a browser at a phone width and a desktop width: every view, every filter, search in both scripts and without diacritics, random draw, shared addresses |
| Code review | independent review of the diff before anything is merged |

## 10. Changes since the first version, and why

| Change | Reason |
|---|---|
| Year of the edition: 1992 → **1998** | Read from the title page at full resolution; the first reading was made from a 150 DPI image and was wrong. The decision to publish the prayers only, with attribution, is unchanged. |
| Book page = PDF page **+** 3 (was − 3) | A slip in the first version; the page ranges of the sections were and are correct. |
| Page images come from the 600 ppi scan of the same book on the Internet Archive | The PDF is byte-identical to the Archive's source PDF; measured accuracy is far higher (section 2). |
| Tesseract's Serbian Latin sub-language switched off | It was the mechanical cause of every Latin letter in the output. |
| Second independent reading: the Archive's own OCR | Free, covers every page, and on the nine checked disagreements it was right each time where our OCR was wrong. |
| Verification: adjudication of every marked line on enlarged strips, then a blind transcription of a 31-page sample to measure what the flags miss | The text-anchored review was accurate but took about a quarter of an hour per page, far too slow to cover the book; strips at full resolution are easier to read than a whole page. |
| Search folds both sides to plain Latin instead of converting the query to Cyrillic | Converting fails when the query is typed without diacritics. |
| Footnote, stress mark and small-caps lines defined | Found while reading the pages; the first version did not know about them. |
| Section 9 separates checks of the code from the measurement of the text | They answer different questions and were mixed before. |
| A dash between words is print and stays in the text | The first version had the cleaner remove every dash between words as an artefact of justified setting. Checked on the scans, 21 of the 70 such dashes are printed (ordinary gaps, „Он – Господ“), so removing them changed the text. The 49 phantoms in wide gaps are removed by explicit corrections instead. |

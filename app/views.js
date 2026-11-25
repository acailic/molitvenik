// The HTML of every view. Pure functions of the data: nothing here touches the page or storage.

import { buildHash } from "./router.js";
import { highlight } from "./search.js";
import { foldMap } from "./text.js";

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** The one way any text reaches the page. */
export function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (character) => ESCAPES[character]);
}

const prayerPath = (id) => buildHash({ view: "prayer", id });
const sectionPath = (id) => buildHash({ view: "section", id });

// Serbian counts three ways: one, two to four, five and more.
function counted(count, one, few, many) {
  const ten = count % 10;
  const hundred = count % 100;
  let word = many;
  if (ten === 1 && hundred !== 11) word = one;
  else if (ten >= 2 && ten <= 4 && (hundred < 12 || hundred > 14)) word = few;
  return `${count} ${word}`;
}

const prayers = (count) => counted(count, "молитва", "молитве", "молитава");
const sections = (count) => counted(count, "одељак", "одељка", "одељака");
const words = (count) => counted(count, "реч", "речи", "речи");
const minutes = (count) => counted(count, "минут", "минута", "минута");

const line = (parts) => parts.filter(Boolean).join(" · ");

// About 150 words a minute, never less than a minute.
const readingTime = (count) => `око ${minutes(Math.max(1, Math.round(count / 150)))}`;

function pagesLabel(pages) {
  if (!Array.isArray(pages) || pages.length !== 2) return "";
  return pages[0] === pages[1] ? `стр. ${pages[0]}` : `стр. ${pages[0]}–${pages[1]}`;
}

// "Штампарија Српске патријаршије, Београд 1998"
function imprint(book) {
  const place = [book?.place, book?.year].filter(Boolean).join(" ");
  return [book?.publisher, place].filter(Boolean).join(", ");
}

// A chip says how long a tier takes; the line of a result only needs the tier.
function lengthLabel(length, facets) {
  const tier = facets
    .find((facet) => facet.id === "duzina")
    ?.values.find((value) => value.id === length);
  return tier ? tier.label.replace(/\s*\(.*\)\s*$/, "") : "";
}

// "Песма 5." and "Песма 5" name the same thing.
function alike(first, second) {
  const plain = (text) => String(text ?? "").trim().replace(/[.\s]+$/, "").toLowerCase();
  return plain(first) === plain(second);
}

// Text with the found word marked.
function marked(text, key) {
  return highlight(String(text ?? ""), key)
    .map((segment) => (segment.match ? `<mark>${escapeHtml(segment.text)}</mark>` : escapeHtml(segment.text)))
    .join("");
}

// The stretch of the prayer around the found word, cut at word ends. The opening of the
// prayer stands in when the word is only in the title or the author.
function passageAround(unit, key, opening) {
  if (!key) return opening;

  const stretches = [];
  for (const block of unit.blocks ?? []) {
    const stretch =
      block.kind === "rubric" ? block.text ?? "" : (block.runs ?? []).map((run) => run.text ?? "").join(" ");
    stretches.push(stretch);
  }
  for (const note of unit.footnotes ?? []) stretches.push(note.text ?? "");

  for (const stretch of stretches) {
    const { folded, starts } = foldMap(stretch);
    const at = folded.indexOf(key);
    if (at === -1) continue;

    // The character holding the found position; a match can begin inside a letter that folds to two.
    const chars = Array.from(stretch);
    let first = chars.length - 1;
    while (first > 0 && starts[first] > at) first -= 1;

    const start = Math.max(0, first - 50);
    const before = chars.slice(start, first).join("");
    // The opening word is dropped only where the cut left it incomplete; the ellipsis says
    // that something was cut, wherever the cut fell.
    const cutLead = start > 0 && chars[start - 1] !== " " ? before.indexOf(" ") + 1 : 0;
    const after = chars.slice(first, first + 120).join("");
    const cutTail = after.indexOf(" ", 100);
    const lead = start > 0 ? "…" : "";
    const tail = cutTail === -1 ? "" : "…";
    return `${lead}${before.slice(cutLead)}${cutTail === -1 ? after : after.slice(0, cutTail)}${tail}`;
  }
  return opening;
}

const hasChips = (state) => Object.values(state ?? {}).some((values) => values.length > 0);

// Nothing typed and no chip pressed: the home is the contents of the book.
const isContents = (home) => !home.q && !hasChips(home.state);

/** Home: the title plate, the random draw, the search, the filters and the list. */
export function renderHome(home) {
  const { book, typed } = home;
  const [over, ...rest] = String(book?.title ?? "").split(/\s+/).filter(Boolean);
  const made = imprint(book);
  const lead = `${prayers(home.units.length)} у ${sections(home.sections.length)}. Потражите молитву по речи, изаберите према поводу и коме је упућена, или отворите књигу на случајном месту.`;
  return `
    <div class="home page">
      <div class="home-tools">
        <header class="plate framed">
          <h1 class="plate-title">
            <span class="plate-over">${escapeHtml(over)}</span>
            <span class="plate-name">${escapeHtml(rest.join(" ") || over)}</span>
          </h1>
          <span class="plate-rule" aria-hidden="true"></span>
          <p class="plate-sub">${escapeHtml(made)}${made ? "." : ""}</p>
        </header>
        <p class="lead">${escapeHtml(lead)}</p>
        <button type="button" class="draw framed" data-action="random"${home.drawDisabled ? " disabled" : ""}>
          <span class="draw-title">Случајна молитва</span>
          <span class="draw-note">отвори књигу на случајном месту</span>
        </button>
        <form class="search" role="search" data-role="search">
          <label class="label" for="pretraga">Претрага</label>
          <div class="search-field">
            <input id="pretraga" type="search" value="${escapeHtml(typed)}" placeholder="нпр. помилуј, Gospode, oce nas" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="search">
            <button type="button" class="search-clear" data-action="clear-search" aria-label="Обриши претрагу"${typed ? "" : " hidden"}>×</button>
          </div>
        </form>
        <div id="filteri">${renderFilters(home)}</div>
      </div>
      <section class="results" aria-labelledby="broj">
        <p class="count" id="broj" role="status">${renderCount(home)}</p>
        <div id="rezultati">${renderList(home)}</div>
      </section>
    </div>`;
}

/** The four facets as chips, behind a summary that opens them. */
export function renderFilters(home) {
  const active = home.facets.reduce((sum, facet) => sum + (home.state[facet.id]?.length ?? 0), 0);
  const reset = buildHash({ view: "home", id: null, query: home.query, state: {} });

  const facets = home.facets.map((facet) => {
    const chips = facet.values.map((value) => {
      const pressed = (home.state[facet.id] ?? []).includes(value.id);
      const name = `data-facet="${escapeHtml(facet.id)}" data-value="${escapeHtml(value.id)}"`;
      return `<button type="button" class="chip" data-action="chip" ${name} aria-pressed="${pressed}">${escapeHtml(value.label)}</button>`;
    });
    return `
          <fieldset class="facet">
            <legend class="label">${escapeHtml(facet.label)}</legend>
            <div class="chips">${chips.join("")}</div>
          </fieldset>`;
  });

  return `
    <details class="filters"${active ? " open" : ""}>
      <summary class="filters-summary">Филтрирај${active ? ` <span class="badge">${active}</span>` : ""}</summary>
      <div class="filters-body">${facets.join("")}
        ${active ? `<a class="reset" href="${escapeHtml(reset)}">Поништи филтере</a>` : ""}
      </div>
    </details>`;
}

/** How many sections, or prayers, the list holds. */
export function renderCount(home) {
  if (isContents(home)) return escapeHtml(sections(home.sections.length));
  const found = prayers(home.hits.length);
  if (!home.q) return escapeHtml(found);
  return escapeHtml(`${found} ${home.q.includes(" ") ? "са речима" : "са речју"} „${home.q}“`);
}

/** The contents of the book by default; the matching prayers otherwise. */
export function renderList(home) {
  if (isContents(home)) {
    const rows = home.sections.map((section) => {
      const meta = line([prayers((section.units ?? []).length), pagesLabel(section.pages)]);
      return `
        <li>
          <a class="entry" href="${sectionPath(section.id)}">
            <span class="entry-title">${escapeHtml(section.title)}</span>
            <span class="entry-meta">${escapeHtml(meta)}</span>
          </a>
        </li>`;
    });
    return `<ul class="contents">${rows.join("")}</ul>`;
  }
  if (home.hits.length === 0) return emptyList(home);

  const byId = new Map(home.sections.map((section) => [section.id, section]));
  return `<ol class="hits">${home.hits.map((unit) => hitHtml(unit, home, byId)).join("")}</ol>`;
}

function hitHtml(unit, home, sectionsById) {
  const section = sectionsById.get(unit.section);
  const opening = home.entries.get(unit.id)?.snippet ?? "";
  const meta = [
    section ? `<a href="${sectionPath(section.id)}">${escapeHtml(section.title)}</a>` : "",
    escapeHtml(lengthLabel(unit.length, home.facets)),
    escapeHtml(words(unit.words)),
  ]
    .filter(Boolean)
    .join(" · ");
  return `
      <li class="hit">
        <a class="hit-title" href="${prayerPath(unit.id)}">${marked(unit.title, home.key)}</a>
        ${unit.author ? `<p class="hit-author">${marked(unit.author, home.key)}</p>` : ""}
        <p class="hit-text">${marked(passageAround(unit, home.key, opening), home.key)}</p>
        <p class="hit-meta">${meta}</p>
      </li>`;
}

// An empty list says what narrowed it and offers the way back.
function emptyList(home) {
  const filtered = hasChips(home.state);
  const text = home.q
    ? `Ни једна молитва ${filtered ? "која пролази филтере " : ""}не садржи „${home.q}“.`
    : "Ни једна молитва не пролази те филтере.";
  const reset = buildHash({ view: "home", id: null, query: home.query, state: {} });
  return `
    <div class="empty">
      <p>${escapeHtml(text)}</p>
      <p class="empty-help">
        ${home.q ? `<button type="button" class="link-button" data-action="clear-search">Обриши претрагу</button>` : ""}
        ${filtered ? `<a class="reset" href="${escapeHtml(reset)}">Поништи филтере</a>` : ""}
      </p>
    </div>`;
}

// One side of the line under a prayer: the neighbour, or the news that there is none.
function neighbour(unit, side, label, edge) {
  if (!unit) {
    return `<span class="pager-link pager-${side}"><span class="pager-label">${edge}</span></span>`;
  }
  return `
        <a class="pager-link pager-${side}" rel="${side}" href="${prayerPath(unit.id)}">
          <span class="pager-label">${label}</span>
          <span class="pager-title">${escapeHtml(unit.title)}</span>
        </a>`;
}

/** One prayer. */
export function renderPrayer({ unit, section, place, of, prev, next, drawDisabled }) {
  const title = String(unit.title ?? "");
  // The heading of the book is repeated only when it says more than the title.
  const heading = String(unit.bookHeading ?? "").trim();
  const part = String(unit.part ?? "").trim();
  const where = [
    part && !alike(part, title) ? escapeHtml(part) : "",
    section ? `<a href="${sectionPath(section.id)}">${escapeHtml(section.title)}</a>` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const meta = line([words(unit.words), readingTime(unit.words), pagesLabel(unit.pages)]);
  const again = `<button type="button" class="link-button" data-action="random"${drawDisabled ? " disabled" : ""}>Још једна случајна молитва</button>`;

  return `
    <article class="page prayer">
      <header class="head">
        <p class="eyebrow">
          <span>${where}</span>
          ${of > 1 ? `<span class="eyebrow-place">${place} / ${of}</span>` : ""}
        </p>
        <h1 class="title">${escapeHtml(title)}</h1>
        ${heading && !alike(heading, title) ? `<p class="book-heading">${escapeHtml(heading)}</p>` : ""}
        ${unit.author ? `<p class="author">${escapeHtml(unit.author)}</p>` : ""}
        <p class="meta">${escapeHtml(meta)}</p>
      </header>
      ${textHtml(unit)}
      ${notesHtml(unit)}
      <div class="share">
        <button type="button" class="button" data-action="copy">Копирај линк</button>
        <p class="status" role="status"></p>
      </div>
      <nav class="pager" aria-label="Претходна и следећа молитва у одељку">
        ${neighbour(prev, "prev", "← Претходна", "Прва у одељку")}
        ${neighbour(next, "next", "Следећа →", "Последња у одељку")}
      </nav>
      <p class="again">${again}</p>
    </article>`;
}

/** One section: its table of contents, then every unit in book order. */
export function renderSection({ section, units }) {
  const meta = line([prayers(units.length), pagesLabel(section.pages)]);
  const contents = units.map((unit, at) => {
    const id = escapeHtml(unit.id);
    return `
          <li>
            <a href="${prayerPath(unit.id)}" data-scroll="${id}">
              <span class="toc-n">${at + 1}.</span><span>${escapeHtml(unit.title)}</span>
            </a>
          </li>`;
  });
  const whole = units.map((unit) => {
    const id = escapeHtml(unit.id);
    return `
        <section class="unit" id="${id}" tabindex="-1" aria-labelledby="naslov-${id}">
          <h2 class="unit-title" id="naslov-${id}">${escapeHtml(unit.title)}</h2>
          ${unit.author ? `<p class="author">${escapeHtml(unit.author)}</p>` : ""}
          ${textHtml(unit)}
          ${notesHtml(unit)}
        </section>`;
  });

  return `
    <article class="page rule">
      <header class="head">
        <p class="eyebrow"><span>Одељак ${escapeHtml(section.order)}</span></p>
        <h1 class="title">${escapeHtml(section.title)}</h1>
        <p class="meta">${escapeHtml(meta)}</p>
      </header>
      <nav class="rule-toc" aria-labelledby="sadrzaj-odeljka">
        <h2 class="label" id="sadrzaj-odeljka">У овом одељку</h2>
        <ol>${contents.join("")}</ol>
      </nav>${whole.join("")}
    </article>`;
}

// The text as the book prints it: rubrics in red, on their own line or inside a sentence.
function textHtml(unit) {
  const blocks = (unit.blocks ?? []).map((block) => {
    if (block.kind === "rubric") return `<p class="rubric">${escapeHtml(block.text)}</p>`;
    const runs = (block.runs ?? []).map((run) =>
      run.rubric ? `<span class="rubric">${escapeHtml(run.text)}</span>` : escapeHtml(run.text),
    );
    return `<p>${runs.join(" ")}</p>`;
  });
  return `<div class="text">${blocks.join("")}</div>`;
}

function notesHtml(unit) {
  if (!unit.footnotes?.length) return "";
  const notes = unit.footnotes.map(
    (note) =>
      `<p class="note">${note.marker ? `<sup class="note-mark">${escapeHtml(note.marker)}</sup>` : ""}${escapeHtml(note.text)}</p>`,
  );
  return `<section class="notes" aria-label="Напомене">${notes.join("")}</section>`;
}

/** An address that names no prayer and no section. */
export function renderNotFound(kind) {
  const [what, title] = kind === "section" ? ["одељка", "Нема тог одељка"] : ["молитве", "Нема те молитве"];
  return `
    <article class="page missing">
      <h1 class="title">${title}</h1>
      <p>На овој адреси нема ${what}. Проверите да ли је адреса тачна.</p>
      <p><a href="${buildHash({ view: "home" })}">На све молитве</a></p>
    </article>`;
}

/** The book could not be read. */
export function renderError() {
  return `
    <article class="page missing">
      <h1 class="title">Молитвеник није учитан</h1>
      <p>Текст молитава није стигао до прегледача. Проверите везу и покушајте поново.</p>
      <p><button type="button" class="button" data-action="reload">Покушај поново</button></p>
    </article>`;
}

/** Who made the book, and that this is a transcription. */
export function renderFooter(book) {
  const made = imprint(book);
  return `
    <p>Текст је пренет из књиге „${escapeHtml(book?.title)}“${made ? `, ${escapeHtml(made)}` : ""}. Права на текст припадају носиоцима права; сајт је непрофитан.</p>
    <p>Ово је транскрипција и може да садржи грешке. Ако сте приметили неку, <a href="https://github.com/acailic/molitvenik/issues">пријавите је</a>.</p>`;
}

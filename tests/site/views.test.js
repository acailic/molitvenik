import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import * as view from "../../app/views.js";
import { emptyState, makeFacets } from "../../app/filters.js";
import { buildIndex, search, unitText } from "../../app/search.js";
import { searchKey } from "../../app/text.js";

const sample = JSON.parse(
  readFileSync(new URL("../fixtures/site/prayers.sample.json", import.meta.url), "utf8"),
);
const unit = (id) => sample.units.find((item) => item.id === id);
const section = (id) => sample.sections.find((item) => item.id === id);

/** What a visitor reads in a piece of HTML. */
const shown = (html) =>
  html
    .replace(/<[^>]+>/g, "")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&amp;", "&")
    .replace(/\s+/g, " ");

function home(changes = {}) {
  const units = changes.units ?? sample.units;
  return {
    book: sample.book,
    units,
    sections: sample.sections,
    facets: makeFacets(sample.sections),
    entries: new Map(buildIndex(units).map((entry) => [entry.id, entry])),
    state: emptyState(),
    query: "",
    typed: "",
    q: "",
    key: "",
    hits: units,
    drawDisabled: false,
    ...changes,
  };
}

/** The home of a search: the list is what the search returns, unless the test gives one. */
function searched(typed, changes = {}) {
  const model = home(changes);
  const q = typed.trim();
  const key = q ? searchKey(q) : "";
  const hits =
    changes.hits ?? search(buildIndex(model.units), key).map((found) => model.units.find((item) => item.id === found.id));
  return { ...model, typed, q, key, hits };
}

const prayer = (id, changes = {}, around = {}) =>
  view.renderPrayer({
    unit: { ...unit(id), ...changes },
    section: section(unit(id).section),
    place: 1,
    of: section(unit(id).section).units.length,
    prev: null,
    next: null,
    drawDisabled: false,
    ...around,
  });

const passages = (html) => html.match(/<p class="hit-text">.*?<\/p>/g).map(shown);

// ---- escaping ---------------------------------------------------------------------------------------


test("escapeHtml escapes every character that could open a tag or end an attribute", () => {
  assert.equal(
    view.escapeHtml(`<a href="x" title='y'>&</a>`),
    "&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;",
  );
  assert.equal(view.escapeHtml("Господе помилуј"), "Господе помилуј");
  assert.equal(view.escapeHtml(null), "");
  assert.equal(view.escapeHtml(undefined), "");
});


test("a search query reaches the page escaped, in the field, in the count and in the empty list", () => {
  const typed = `<script>alert("x")`;
  const html = view.renderHome(searched(typed));
  assert.ok(html.includes(`value="&lt;script&gt;alert(&quot;x&quot;)"`));
  assert.ok(!html.includes("<script>"));
  assert.equal(shown(view.renderCount(searched(typed))), `0 молитава са речју „${typed}“`);
  assert.ok(!view.renderList(searched(typed)).includes("<script>"));
  assert.ok(shown(view.renderList(searched(typed))).includes(`Ни једна молитва не садржи „${typed}“.`));
});


test("a title, an author and a text with markup in them are shown as text", () => {
  const named = { ...unit("jutarnje__sveti-boze"), title: "<b>Свети</b> Боже", author: "<i>автор</i>" };
  const page = prayer(named.id, named);
  assert.ok(page.includes("<h1 class=\"title\">&lt;b&gt;Свети&lt;/b&gt; Боже</h1>"));
  assert.ok(page.includes("<p class=\"author\">&lt;i&gt;автор&lt;/i&gt;</p>"));
  assert.ok(!page.includes("<b>Свети</b>") && !page.includes("<i>автор</i>"));

  const list = view.renderList(
    searched("sveti", { units: sample.units.map((item) => (item.id === named.id ? named : item)) }),
  );
  assert.ok(list.includes("&lt;b&gt;<mark>Свети</mark>&lt;/b&gt; Боже"));
  assert.ok(list.includes('<p class="hit-author">&lt;i&gt;автор&lt;/i&gt;</p>'));
  assert.ok(!list.includes("<b>Свети</b>"));

  const text = prayer("jutarnje__pocetak", {
    blocks: [
      { kind: "rubric", text: "<script>" },
      { kind: "paragraph", runs: [{ text: "a & b", rubric: false }, { text: "<u>c</u>", rubric: true }] },
    ],
  });
  assert.ok(text.includes('<p class="rubric">&lt;script&gt;</p>'));
  assert.ok(text.includes("<p>a &amp; b <span class=\"rubric\">&lt;u&gt;c&lt;/u&gt;</span></p>"));
});

// ---- the home ---------------------------------------------------------------------------------------


test("the home shows the book, how many prayers it holds, the draw and the search field", () => {
  const html = view.renderHome(home());
  assert.ok(html.includes('<span class="plate-over">Православни</span>'));
  assert.ok(html.includes('<span class="plate-name">молитвеник</span>'));
  assert.ok(html.includes("<p class=\"plate-sub\">Штампарија Српске патријаршије, Београд 1998.</p>"));
  assert.ok(shown(html).includes("8 молитава у 3 одељка."));
  assert.ok(html.includes('<button type="button" class="draw framed" data-action="random">'));
  assert.ok(html.includes('<input id="pretraga" type="search" value=""'));
  assert.ok(html.includes('data-action="clear-search" aria-label="Обриши претрагу" hidden>'));
  assert.ok(view.renderHome(home({ drawDisabled: true })).includes('class="draw framed" data-action="random" disabled>'));
  // a typed query keeps its text in the field and gets its clear button
  const typed = view.renderHome(searched(" помилуј "));
  assert.ok(typed.includes('value=" помилуј "'));
  assert.ok(typed.includes('data-action="clear-search" aria-label="Обриши претрагу">'));
  // a book that did not load leaves no trace of its absence
  assert.ok(!/undefined|null/.test(view.renderHome(home({ book: null }))));
});


test("the filters open when a chip is pressed, count the pressed chips and offer the way back", () => {
  const shut = view.renderHome(home());
  assert.ok(shut.includes("<details class=\"filters\">"));
  assert.equal((shut.match(/class="chip"/g) || []).length, 3 + 8 + 7 + 3);
  assert.ok(shut.includes('data-facet="povod" data-value="pokajanje" aria-pressed="false"'));
  assert.ok(!shut.includes("Поништи филтере"));

  const pressed = view.renderHome(
    home({ state: { ...emptyState(), povod: ["pokajanje"], kome: ["presveti-duh"] } }),
  );
  assert.ok(pressed.includes('<details class="filters" open>'));
  assert.ok(pressed.includes('Филтрирај <span class="badge">2</span>'));
  assert.ok(pressed.includes('data-facet="povod" data-value="pokajanje" aria-pressed="true"'));
  assert.ok(pressed.includes('data-facet="povod" data-value="zahvalnost" aria-pressed="false"'));
  assert.ok(pressed.includes('data-facet="kome" data-value="presveti-duh" aria-pressed="true"'));
  assert.ok(pressed.includes('<a class="reset" href="#/">Поништи филтере</a>'));
  // the way back keeps what was searched for
  const both = home({ query: "q=Gospode", state: { ...emptyState(), povod: ["pokajanje"] } });
  assert.ok(view.renderHome(both).includes('<a class="reset" href="#/?q=Gospode">'));
});

// ---- counts -----------------------------------------------------------------------------------------


test("Serbian counts: one молитва, two to four молитве, five and more молитава", () => {
  const count = (hits) => shown(view.renderCount(searched("реч", { hits })));
  assert.equal(count(sample.units.slice(0, 1)), "1 молитва са речју „реч“");
  assert.equal(count(sample.units.slice(0, 4)), "4 молитве са речју „реч“");
  assert.equal(count(Array(5).fill(sample.units[0])), "5 молитава са речју „реч“");
  assert.equal(count(Array(11).fill(sample.units[0])), "11 молитава са речју „реч“");
  assert.equal(count(Array(21).fill(sample.units[0])), "21 молитва са речју „реч“");
  assert.equal(count(Array(22).fill(sample.units[0])), "22 молитве са речју „реч“");
  assert.equal(count(Array(25).fill(sample.units[0])), "25 молитава са речју „реч“");
  assert.equal(count([]), "0 молитава са речју „реч“");
  // nothing typed and no chip pressed: the home is the contents of the book
  assert.equal(shown(view.renderCount(home())), "3 одељка");
  // a chip pressed and nothing typed: only a filter narrows the list
  const filtered = home({ state: { ...emptyState(), povod: ["pokajanje"] }, hits: sample.units.slice(6, 8) });
  assert.equal(shown(view.renderCount(filtered)), "2 молитве");
  assert.equal(shown(view.renderCount({ ...filtered, hits: sample.units.slice(6, 7) })), "1 молитва");
  assert.equal(shown(view.renderCount({ ...filtered, hits: Array(5).fill(sample.units[0]) })), "5 молитава");
});


test("the count names what was searched for, with one word or with several", () => {
  assert.equal(
    shown(view.renderCount(searched("oce nas", { hits: sample.units.slice(0, 2) }))),
    "2 молитве са речима „oce nas“",
  );
  assert.equal(
    shown(view.renderCount(searched("  Господе  ", { hits: sample.units.slice(0, 1) }))),
    "1 молитва са речју „Господе“",
  );
});

// ---- lists ------------------------------------------------------------------------------------------


test("the home lists the sections with how many prayers and which pages", () => {
  const html = view.renderList(home());
  assert.equal((html.match(/<a class="entry" href="#\/odeljak\//g) || []).length, 3);
  assert.ok(shown(html).includes("Молитве јутарње 4 молитве · стр. 11–33"));
  assert.ok(shown(html).includes("Молитвено правило пред Свето причешће 3 молитве · стр. 109–157"));
  assert.ok(shown(html).includes("Молитве пре и после јела 1 молитва · стр. 165–168"));
  // in the order of the book
  assert.ok(html.indexOf('href="#/odeljak/jutarnje"') < html.indexOf('href="#/odeljak/jela"'));
  // a section id is encoded on its way into an address
  const odd = view.renderList(home({ sections: [{ ...section("jela"), id: "pre i posle", title: "<b>јела</b>" }] }));
  assert.ok(odd.includes('href="#/odeljak/pre%20i%20posle">'));
  assert.ok(odd.includes("&lt;b&gt;јела&lt;/b&gt;"));
});


test("a search result marks the found words in the title, in the author and in the passage", () => {
  const html = view.renderList(searched("pomiluj"));
  assert.ok(html.includes('<a class="hit-title" href="#/molitva/jutarnje__pocetak">Почетак јутарњих молитава</a>'));
  // fifty characters before the word the cut falls on a space: the first word stays whole, and
  // the ellipsis says that something was cut; the rubric that follows is part of the passage
  assert.ok(html.includes(
    '<p class="hit-text">…ради молитава пречисте Твоје Матере и свих светих <mark>помилуј</mark> нас. Амин. Затим Слава Теби Боже наш, слава Теби.</p>',
  ));
  // the word stands near the opening of „Свети Боже": nothing is cut before it
  assert.ok(html.includes(
    '<p class="hit-text">Свети Боже, свети Крепки, свети Бесмртни, <mark>помилуј</mark> нас (три пута).</p>',
  ));
  // the capitals of the print are kept
  assert.ok(html.includes("<mark>ПОМИЛУЈ</mark>! 40 пута и поклона"));
  // under every passage: the section, the length and the number of words
  assert.ok(shown(html).includes("Молитвено правило пред Свето причешће · дуга · 477 речи"));
  assert.ok(shown(html).includes("Молитве јутарње · кратка · 23 речи"));
  assert.equal((html.match(/<li class="hit"/g) || []).length, 4);

  // in the title
  const title = view.renderList(searched("nebeski"));
  assert.ok(title.includes('<a class="hit-title" href="#/molitva/jutarnje__care-nebeski">Царе <mark>небески</mark></a>'));

  // in the author: the word is not in the text, so the passage is the opening of the prayer
  const named = { ...unit("jutarnje__pocetak"), author: "св. Макарије Велики" };
  const author = view.renderList(
    searched("makarije", { units: sample.units.map((item) => (item.id === named.id ? named : item)) }),
  );
  assert.equal((author.match(/<li class="hit"/g) || []).length, 1);
  assert.ok(author.includes('<p class="hit-author">св. <mark>Макарије</mark> Велики</p>'));
  assert.ok(author.includes(`<p class="hit-text">${view.escapeHtml(unitText(named).slice(0, 120))}</p>`));
  assert.equal((author.match(/<mark>/g) || []).length, 1);
});


test("the passage around a found word starts and ends at word ends", () => {
  const found = passages(view.renderList(searched("istine")));
  assert.equal(found.length, 2);
  const words = unitText(unit("pred-pricesce__primer-duga")).split(" ");
  for (const passage of found) {
    assert.ok(passage.includes("Душе истине, који си свуда и све испуњаваш"));
    // every word of the passage is a whole word of the prayer: neither end cuts into a word
    for (const word of passage.replaceAll("…", " ").split(" ").filter(Boolean)) assert.ok(words.includes(word), word);
    assert.ok(passage.endsWith("…"));
    assert.ok(passage.length > 100 && passage.length < 180, passage);
  }
  // the word stands forty characters into the short prayer: nothing is cut before it
  assert.ok(found[0].startsWith("Царе небески, Утешитељу, Душе истине"), found[0]);
  assert.ok(!found[0].includes("…Душе"), "no ellipsis where nothing was cut");
  // deep in the long prayer: some fifty characters before it, and an ellipsis where the cut fell
  assert.ok(found[1].startsWith("…и пијем Твоју Крв. Царе небески, Утешитељу, Душе истине"), found[1]);
});


test("an empty result says what narrowed the list and offers the way back", () => {
  const word = view.renderList(searched("<zzz>"));
  assert.ok(shown(word).includes("Ни једна молитва не садржи „<zzz>“."));
  assert.ok(word.includes('data-action="clear-search">Обриши претрагу</button>'));
  assert.ok(!word.includes("Поништи филтере") && !word.includes("<zzz>"));

  const chip = view.renderList(home({ state: { ...emptyState(), povod: ["za-pokojne"] }, hits: [] }));
  assert.ok(shown(chip).includes("Ни једна молитва не пролази те филтере."));
  assert.ok(chip.includes('<a class="reset" href="#/">Поништи филтере</a>'));
  assert.ok(!chip.includes("Обриши претрагу"));

  // both: the word is named, the filters are admitted, and the way back keeps the word
  const both = view.renderList({
    ...searched("<zzz>"),
    query: "q=%3Czzz%3E",
    state: { ...emptyState(), povod: ["za-pokojne"] },
  });
  assert.ok(shown(both).includes("Ни једна молитва која пролази филтере не садржи „<zzz>“."));
  assert.ok(both.includes('data-action="clear-search"'));
  assert.ok(both.includes('<a class="reset" href="#/?q=%3Czzz%3E">'));
});

// ---- one prayer -------------------------------------------------------------------------------------


test("a prayer shows rubrics in red, on their own line and inside a sentence", () => {
  const html = prayer("jutarnje__pocetak", {}, { place: 1, of: 4, next: unit("jutarnje__care-nebeski") });
  assert.ok(html.includes('<span><a href="#/odeljak/jutarnje">Молитве јутарње</a></span>'));
  assert.ok(html.includes('<span class="eyebrow-place">1 / 4</span>'));
  assert.equal((html.match(/<h1/g) || []).length, 1);
  assert.ok(html.includes("<h1 class=\"title\">Почетак јутарњих молитава</h1>"));
  assert.ok(html.includes('<div class="text"><p class="rubric">Ако није свештеник, почиње овако:</p>'));
  assert.ok(html.includes("Амин. <span class=\"rubric\">Затим</span> Слава Теби Боже наш, слава Теби.</p></div>"));
  assert.ok(html.includes("<p class=\"meta\">23 речи · око 1 минут · стр. 12</p>"));
  assert.ok(html.includes('<span class="pager-label">Прва у одељку</span>'));
  assert.ok(html.includes('<span class="pager-label">Следећа →</span>'));
  assert.ok(html.includes('<span class="pager-title">Царе небески</span>'));
  assert.ok(html.includes('<a class="pager-link pager-next" rel="next" href="#/molitva/jutarnje__care-nebeski">'));
  assert.ok(html.includes('<button type="button" class="link-button" data-action="random">'));
  // no author, no heading, no note
  assert.ok(!html.includes("book-heading") && !html.includes('class="author"') && !html.includes('class="notes"'));

  // the last of its section
  const last = prayer("jutarnje__slava-ocu", {}, { place: 4, of: 4, prev: unit("jutarnje__sveti-boze") });
  assert.ok(last.includes('<span class="pager-label">Последња у одељку</span>'));
  assert.ok(last.includes('<a class="pager-link pager-prev" rel="prev" href="#/molitva/jutarnje__sveti-boze">'));

  // a reading of several minutes
  assert.ok(prayer("pred-pricesce__primer-duga").includes("<p class=\"meta\">477 речи · око 3 минута · стр. 113–140</p>"));
  // nothing left to draw
  assert.ok(prayer("jutarnje__pocetak", {}, { drawDisabled: true }).includes('data-action="random" disabled>'));
});


test("a footnote is shown with its mark, or without one when the book prints none", () => {
  assert.ok(
    prayer("jela__kraj").includes('<section class="notes" aria-label="Напомене"><p class="note">непријатељи моји.</p></section>'),
  );
  const starred = prayer("jela__kraj", { footnotes: [{ marker: "*", text: "непријатељи моји." }] });
  assert.ok(starred.includes('<p class="note"><sup class="note-mark">*</sup>непријатељи моји.</p>'));
  const whole = view.renderSection({ section: section("jela"), units: [unit("jela__kraj")] });
  assert.ok(whole.includes('<p class="note">непријатељи моји.</p>'));
  assert.ok(!prayer("jutarnje__pocetak").includes('class="note"'));
});


test("the heading of the book and the part are shown only when they say more than the title", () => {
  const page = (changes) => prayer("pred-pricesce__pesma-5", changes, { place: 1, of: 3 });
  const plain = page({});
  assert.ok(!plain.includes("book-heading"), "the book prints „Песма 5.“ over the prayer „Песма 5“");
  assert.ok(plain.includes('<span><a href="#/odeljak/pred-pricesce">'));
  assert.ok(page({ bookHeading: "Песма 5, глас 2:" }).includes('<p class="book-heading">Песма 5, глас 2:</p>'));
  assert.ok(page({ bookHeading: "<b>" }).includes('<p class="book-heading">&lt;b&gt;</p>'));
  assert.ok(page({ part: "Причастан канон" }).includes('<span>Причастан канон · <a href="#/odeljak/pred-pricesce">'));
  // the heading stands between the title and the author
  assert.ok(shown(page({ bookHeading: "Песма 5, глас 2:", author: "автор" })).includes("Песма 5, глас 2: автор"));
});

// ---- a section, a missing page, the footer ------------------------------------------------------------


test("a section lists its units and then shows them in order", () => {
  const jutarnje = section("jutarnje");
  const html = view.renderSection({ section: jutarnje, units: jutarnje.units.map(unit) });
  assert.ok(html.includes('<p class="eyebrow"><span>Одељак 1</span></p>'));
  assert.ok(html.includes("<h1 class=\"title\">Молитве јутарње</h1>"));
  assert.ok(html.includes("<p class=\"meta\">4 молитве · стр. 11–33</p>"));
  assert.ok(html.includes('<a href="#/molitva/jutarnje__care-nebeski" data-scroll="jutarnje__care-nebeski">'));
  assert.ok(html.includes('<span class="toc-n">2.</span><span>Царе небески</span>'));
  assert.equal((html.match(/<h1/g) || []).length, 1);
  assert.equal((html.match(/<h2 class="unit-title"/g) || []).length, 4);
  assert.equal((html.match(/class="unit" id="/g) || []).length, 4);
  const places = jutarnje.units.map((id) => html.indexOf(`<section class="unit" id="${id}"`));
  assert.ok(places.every((at, index) => index === 0 || at > places[index - 1]));
  // the rubrics are red here too, and each unit is named for the screen reader
  assert.ok(html.includes('<span class="rubric">Затим</span>'));
  assert.ok(html.includes('aria-labelledby="naslov-jutarnje__pocetak">'));
  assert.ok(html.includes('<h2 class="unit-title" id="naslov-jutarnje__pocetak">'));
});


test("an id is encoded on its way into an address and escaped on its way into the page", () => {
  const odd = { ...unit("jutarnje__sveti-boze"), id: 'a"b' };
  const html = view.renderSection({ section: section("jutarnje"), units: [odd] });
  assert.ok(html.includes('<section class="unit" id="a&quot;b"'));
  assert.ok(html.includes('id="naslov-a&quot;b"'));
  assert.ok(html.includes('href="#/molitva/a%22b"'));
  assert.ok(!html.includes('id="a"b"'));
  assert.ok(prayer("jutarnje__sveti-boze", {}, { next: odd }).includes('href="#/molitva/a%22b"'));
});


test("an address that names nothing, a book that did not load, and the footer", () => {
  const prayerPage = view.renderNotFound("prayer");
  assert.ok(prayerPage.includes("<h1 class=\"title\">Нема те молитве</h1>"));
  assert.ok(prayerPage.includes("На овој адреси нема молитве."));
  assert.ok(prayerPage.includes('<a href="#/">На све молитве</a>'));

  const sectionPage = view.renderNotFound("section");
  assert.ok(sectionPage.includes("Нема тог одељка") && sectionPage.includes("нема одељка."));
  assert.ok(!sectionPage.includes("Нема те молитве"));

  assert.ok(view.renderError().includes("<h1 class=\"title\">Молитвеник није учитан</h1>"));
  assert.ok(
    view.renderError().includes('<button type="button" class="button" data-action="reload">Покушај поново</button>'),
  );

  const footer = view.renderFooter(sample.book);
  assert.ok(footer.includes("„Православни молитвеник“, Штампарија Српске патријаршије, Београд 1998."));
  assert.ok(footer.includes("пријавите је</a>"));
  assert.ok(!footer.includes("undefined"));
  // a book without an imprint makes no dangling comma
  assert.ok(view.renderFooter({ title: "Књига" }).includes("из књиге „Књига“. Права"));
});

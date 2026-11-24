import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { buildIndex, highlight, search, unitText } from "../../app/search.js";
import { searchKey } from "../../app/text.js";

const sample = JSON.parse(
  readFileSync(new URL("../fixtures/site/prayers.sample.json", import.meta.url), "utf8"),
);
const units = sample.units;
const index = buildIndex(units);
const ids = (found) => found.map((hit) => hit.id);

test("unitText joins the blocks and the footnotes with a space", () => {
  const text = unitText(units[0]);
  assert.ok(text.startsWith("Ако није свештеник, почиње овако: Господе Исусе Христе"));
  assert.ok(unitText(units[7]).endsWith("непријатељи моји."));
});

test("buildIndex makes one entry per unit with folded keys and a snippet", () => {
  assert.equal(index.length, units.length);
  const care = index.find((entry) => entry.id === "jutarnje__care-nebeski");
  assert.equal(care.titleKey, "care nebeski");
  assert.equal(care.authorKey, "");
  assert.ok(care.bodyKey.includes("duse istine"));
  assert.equal(care.snippet.length, 120);
});

test("search finds nothing for an empty key", () => {
  assert.deepEqual(search(index, ""), []);
  assert.deepEqual(search(index, undefined), []);
});

test("search matches a query typed in Cyrillic, in Latin, and without diacritics", () => {
  for (const typed of ["помилуј", "pomiluj", "Pomiluj"]) {
    assert.ok(ids(search(index, searchKey(typed))).includes("jutarnje__sveti-boze"), typed);
  }
  // "duše" typed without the diacritic is "duse"; the folded key is the same.
  const withoutDiacritics = ids(search(index, searchKey("duse istine")));
  assert.equal(withoutDiacritics[0], "jutarnje__care-nebeski");
  assert.deepEqual(ids(search(index, searchKey("duše istine"))), withoutDiacritics);
  assert.deepEqual(ids(search(index, searchKey("Душе истине"))), withoutDiacritics);
});

test("search ranks a title match first, then author, then body", () => {
  const withAuthor = units.map((unit) =>
    unit.id === "jutarnje__pocetak" ? { ...unit, author: "св. Макарије Велики" } : unit,
  );
  const mixed = buildIndex(withAuthor);
  // "небески" is in a title; "великог" only in an author; "прими" only in bodies.
  const title = search(mixed, searchKey("nebeski"));
  assert.equal(title[0].field, "title");
  assert.equal(title[0].id, "jutarnje__care-nebeski");
  assert.ok(title.length > 1, "the long unit repeats the same prayer in its body");
  const author = search(mixed, searchKey("makarije"));
  assert.deepEqual(
    author.map((hit) => [hit.id, hit.field]),
    [["jutarnje__pocetak", "author"]],
  );
  for (const hit of search(mixed, searchKey("прими"))) assert.equal(hit.field, "body");
});

test("search keeps the order of the units inside a field and reports the position", () => {
  const found = search(index, searchKey("istine"));
  assert.deepEqual(ids(found), ["jutarnje__care-nebeski", "pred-pricesce__primer-duga"]);
  const care = index.find((entry) => entry.id === "jutarnje__care-nebeski");
  assert.equal(found[0].position, care.bodyKey.indexOf("istine"));
  for (const hit of found) assert.equal(hit.field, "body");
});

test("search lists each unit once, with its best field", () => {
  // "царе" is the title of care-nebeski and also the first word of its text.
  const found = search(index, searchKey("царе"));
  assert.deepEqual(found[0], { id: "jutarnje__care-nebeski", field: "title", position: 0 });
  assert.equal(found.filter((hit) => hit.id === "jutarnje__care-nebeski").length, 1);
  for (const hit of found.slice(1)) assert.equal(hit.field, "body");
});

test("highlight marks exactly the matching characters of the original text", () => {
  assert.deepEqual(highlight("Господе помилуј нас", searchKey("pomiluj")), [
    { text: "Господе ", match: false },
    { text: "помилуј", match: true },
    { text: " нас", match: false },
  ]);
});

test("highlight works for a query typed without diacritics", () => {
  assert.deepEqual(highlight("Душе истине", searchKey("istine")), [
    { text: "Душе ", match: false },
    { text: "истине", match: true },
  ]);
});

test("highlight marks every occurrence and keeps the text whole", () => {
  const segments = highlight("помилуј нас, помилуј", searchKey("pomiluj"));
  assert.equal(segments.map((part) => part.text).join(""), "помилуј нас, помилуј");
  assert.deepEqual(segments.map((part) => part.match), [true, false, true]);
});

test("highlight returns one plain segment when nothing matches or the key is empty", () => {
  for (const key of ["zzz", ""]) {
    assert.deepEqual(highlight("Господе", key), [{ text: "Господе", match: false }]);
  }
});

test("the module loads and works without a document", () => {
  assert.equal(typeof globalThis.document, "undefined");
  assert.ok(ids(search(index, "care")).includes("jutarnje__care-nebeski"));
});

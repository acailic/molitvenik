import test from "node:test";
import assert from "node:assert/strict";

import { foldAscii, foldMap, hasCyrillic, searchKey, toLatin } from "../../app/text.js";

test("toLatin maps the digraph letters first and the others one to one", () => {
  assert.equal(toLatin("љубав"), "ljubav");
  assert.equal(toLatin("њих"), "njih");
  assert.equal(toLatin("џабе"), "džabe");
  assert.equal(toLatin("ђаво"), "đavo");
  assert.equal(toLatin("човек"), "čovek");
  assert.equal(toLatin("ћути"), "ćuti");
  assert.equal(toLatin("шиша"), "šiša");
  assert.equal(toLatin("живот"), "život");
  assert.equal(toLatin("црква"), "crkva");
  assert.equal(toLatin("православни молитвеник"), "pravoslavni molitvenik");
});

test("toLatin maps capital letters, with the digraphs as Lj, Nj, Dž", () => {
  assert.equal(toLatin("Љубав"), "Ljubav");
  assert.equal(toLatin("Њега"), "Njega");
  assert.equal(toLatin("Џабе"), "Džabe");
  assert.equal(toLatin("Ђаво"), "Đavo");
  assert.equal(toLatin("Човек"), "Čovek");
  assert.equal(toLatin("Бог"), "Bog");
  assert.equal(toLatin("ЋУТИ"), "ĆUTI");
});

test("toLatin leaves everything that is not Cyrillic as it is", () => {
  assert.equal(toLatin("abc Č 123 .,!?"), "abc Č 123 .,!?");
});

test("hasCyrillic", () => {
  assert.equal(hasCyrillic("оче"), true);
  assert.equal(hasCyrillic("oce"), false);
  assert.equal(hasCyrillic(""), false);
  assert.equal(hasCyrillic("123 ,."), false);
});

test("foldAscii removes the diacritics and lower-cases", () => {
  assert.equal(foldAscii("č ć š ž đ"), "c c s z dj");
  assert.equal(foldAscii("dž Dž DŽ"), "dz dz dz");
  assert.equal(foldAscii("Čovek ŠUM"), "covek sum");
  assert.equal(foldAscii("lj nj"), "lj nj");
});

test("searchKey gives the same key for a word typed in either script", () => {
  const pairs = [
    ["помилуј", "pomiluj"],
    ["оче наш", "oce nas"],
    ["Oče naš", "oce nas"],
    ["човек", "covek"],
    ["čovek", "covek"],
    ["ђаво", "djavo"],
    ["џабе", "dzabe"],
    ["љубав", "ljubav"],
    ["Господе помилуј нас", "gospode pomiluj nas"],
  ];
  for (const [typed, key] of pairs) assert.equal(searchKey(typed), key, typed);
  assert.equal(searchKey("човек"), searchKey("čovek"));
  assert.equal(searchKey("помилуј"), searchKey("POMILUJ"));
});

test("searchKey ignores diacritics typed in the Cyrillic query and combining marks", () => {
  assert.equal(searchKey("помилуј" + "\u0300"), "pomiluj");
  assert.equal(searchKey(String.fromCharCode(0x045d)), "i"); // ѝ, the stressed и
});

test("searchKey of nothing is an empty key", () => {
  assert.equal(searchKey(""), "");
  assert.equal(searchKey(null), "");
  assert.equal(searchKey(undefined), "");
});

test("foldMap: one start per code point, the first at zero, the key equals searchKey", () => {
  for (const text of ["Господе помилуј нас", "Љубав, џабе!", "ace"]) {
    const { folded, starts } = foldMap(text);
    assert.equal(starts.length, Array.from(text).length, text);
    assert.equal(starts[0], 0);
    assert.equal(folded, searchKey(text));
  }
});

test("foldMap: a letter that folds to two characters shifts the following starts by two", () => {
  const { folded, starts } = foldMap("љу");
  assert.equal(folded, "lju");
  assert.deepEqual(starts, [0, 2]);
});

test("the module loads and works without a document", () => {
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(searchKey("океј"), "okej");
});

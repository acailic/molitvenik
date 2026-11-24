// Search over the units of the prayer book.
//
// Pure functions: no DOM, no storage. The index holds folded search keys (see
// text.js), so one folded query matches text typed in either script.

import { foldMap, searchKey } from "./text.js";

const FIELDS = [
  { name: "title", key: "titleKey" },
  { name: "author", key: "authorKey" },
  { name: "body", key: "bodyKey" },
];
const FIELD_RANK = { title: 0, author: 1, body: 2 };

/** The text of a unit as one string: blocks and footnotes. */
export function unitText(unit) {
  const parts = [];
  for (const block of unit.blocks ?? []) {
    if (block.kind === "rubric") {
      parts.push(block.text);
    } else {
      for (const run of block.runs ?? []) parts.push(run.text);
    }
  }
  for (const note of unit.footnotes ?? []) parts.push(note.text);
  return parts.join(" ");
}

/** One index entry per unit, in the order of the units. */
export function buildIndex(units) {
  return units.map((unit) => {
    const title = unit.title ?? "";
    const author = unit.author ?? "";
    const body = unitText(unit);
    return {
      id: unit.id,
      titleKey: searchKey(title),
      authorKey: searchKey(author),
      bodyKey: searchKey(`${title} ${author} ${body}`),
      snippet: body.slice(0, 120),
    };
  });
}

/**
 * Units whose folded text contains the key. Each unit appears once, with its
 * best field. Sorted by field (title, author, body), then by the unit's place
 * in the book. `position` is where the key stands in the field's folded text.
 * An empty key finds nothing.
 */
export function search(index, key) {
  if (!key) return [];
  const found = [];
  index.forEach((entry, place) => {
    for (const field of FIELDS) {
      const at = entry[field.key].indexOf(key);
      if (at !== -1) {
        found.push({ id: entry.id, field: field.name, position: at, rank: FIELD_RANK[field.name], place });
        return;
      }
    }
  });
  return found
    .sort((a, b) => a.rank - b.rank || a.place - b.place)
    .map(({ id, field, position }) => ({ id, field, position }));
}

/**
 * Split the original text into segments, marking the parts covered by the key.
 * The key must be a search key; the text is folded here and the match positions
 * are mapped back onto its characters.
 */
export function highlight(text, key) {
  const { folded, starts } = foldMap(text);
  const chars = Array.from(text);
  const count = chars.length;
  const beginOf = (i) => (i < count ? starts[i] : folded.length);
  const segments = [];
  let placed = 0;
  let from = 0;
  while (key) {
    const at = folded.indexOf(key, from);
    if (at === -1) break;
    const end = at + key.length;
    let first = placed;
    while (first < count && beginOf(first + 1) <= at) first += 1;
    let last = first;
    while (last + 1 < count && starts[last + 1] < end) last += 1;
    if (first > placed) segments.push({ text: chars.slice(placed, first).join(""), match: false });
    segments.push({ text: chars.slice(first, last + 1).join(""), match: true });
    placed = last + 1;
    from = end;
  }
  if (placed < count || segments.length === 0) {
    segments.push({ text: chars.slice(placed).join(""), match: false });
  }
  return segments;
}

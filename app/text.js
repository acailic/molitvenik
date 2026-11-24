// Serbian script folding for search.
//
// The prayer text is stored in Cyrillic only. Search must work for a query typed
// in Cyrillic, in Serbian Latin, or in Latin without diacritics ("oce nas" must
// find "оче наш"). Converting the query into Cyrillic fails in the last case, so
// both sides are folded instead: Cyrillic is transliterated to Latin and Latin is
// reduced to plain ASCII. What remains of both is the same string.

// Lower-case Serbian Cyrillic → Serbian Latin. љ, њ and џ are single letters
// that become two; the others map one to one.
const LOWER = new Map([
  ["а", "a"], ["б", "b"], ["в", "v"], ["г", "g"], ["д", "d"], ["ђ", "đ"], ["е", "e"],
  ["ж", "ž"], ["з", "z"], ["и", "i"], ["ј", "j"], ["к", "k"], ["л", "l"], ["љ", "lj"],
  ["м", "m"], ["н", "n"], ["њ", "nj"], ["о", "o"], ["п", "p"], ["р", "r"], ["с", "s"],
  ["т", "t"], ["ћ", "ć"], ["у", "u"], ["ф", "f"], ["х", "h"], ["ц", "c"], ["ч", "č"],
  ["џ", "dž"], ["ш", "š"],
]);

const LETTERS = new Map(LOWER);
for (const [cyrillic, latin] of LOWER) {
  LETTERS.set(cyrillic.toUpperCase(), latin[0].toUpperCase() + latin.slice(1));
}

const CYRILLIC = /\p{Script=Cyrillic}/u;
const MARKS = /\p{M}/gu;

/** True when the text contains any Cyrillic letter. */
export function hasCyrillic(text) {
  return CYRILLIC.test(text);
}

/** Transliterate Serbian Cyrillic to Serbian Latin (љ → lj, џ → dž, ђ → đ). */
export function toLatin(text) {
  let out = "";
  for (const char of text) {
    out += LETTERS.get(char) ?? char;
  }
  return out;
}

/** Reduce Serbian Latin to plain ASCII: č ć → c, š → s, ž → z, đ → dj, dž → dz. */
export function foldAscii(text) {
  return text
    .toLowerCase()
    .replaceAll("dž", "dz")
    .replaceAll("đ", "dj")
    .normalize("NFKD")
    .replace(MARKS, "")
    .normalize("NFKC");
}

/** The search key of any text: lower-case, plain ASCII, the same for both scripts. */
export function searchKey(text) {
  const plain = String(text ?? "")
    .normalize("NFKD")
    .replace(MARKS, "");
  return foldAscii(hasCyrillic(plain) ? toLatin(plain) : plain);
}

/**
 * The search key of a text together with a map from the characters of the text
 * to the positions where they begin in the key. `starts` has one entry per code
 * point of the text: `starts[i]` is the index in `folded` where character `i`
 * begins, the same index as the character before it when it folds to nothing.
 */
export function foldMap(text) {
  const chars = Array.from(String(text ?? ""));
  const starts = new Array(chars.length);
  let folded = "";
  for (let i = 0; i < chars.length; i += 1) {
    starts[i] = folded.length;
    folded += searchKey(chars[i]);
  }
  return { folded, starts };
}

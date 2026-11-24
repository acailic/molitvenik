// Filters of the prayer list: facets, length tiers, and the filter state kept
// in the address so that a filtered list can be shared.
//
// Pure functions: no DOM, no storage.

// The three curated facets. Their values are the ids used in the data and in the
// address; the labels are what the visitor reads.
export const BASE_FACETS = [
  {
    id: "povod",
    label: "Повод",
    values: [
      { id: "pokajanje", label: "покајање" },
      { id: "zahvalnost", label: "захвалност" },
      { id: "zastita", label: "заштита" },
      { id: "miran-san", label: "миран сан" },
      { id: "za-pokojne", label: "за покојне" },
      { id: "uz-obrok", label: "уз оброк" },
      { id: "u-nevolji", label: "у невољи" },
      { id: "u-svako-doba", label: "у свако доба" },
    ],
  },
  {
    id: "kome",
    label: "Кому је упућена",
    values: [
      { id: "gospod-isus-hrist", label: "Господу Исусу Христу" },
      { id: "bog-otac", label: "Богу Оцу" },
      { id: "presveti-duh", label: "Пресветом Духу" },
      { id: "presveta-trojica", label: "Пресветој Тројици" },
      { id: "presveta-bogorodica", label: "Пресветој Богородици" },
      { id: "andjeo-cuvar", label: "Анђелу чувару" },
      { id: "casni-krst", label: "Часном крсту" },
    ],
  },
  {
    id: "duzina",
    label: "Дужина",
    values: [
      { id: "kratka", label: "кратка (до 1 мин)" },
      { id: "srednja", label: "средња (1–3 мин)" },
      { id: "duga", label: "дуга (преко 3 мин)" },
    ],
  },
];

// The facets before the sections are loaded: the section facet has no values yet.
export const FACETS = [{ id: "odeljak", label: "Одељак", values: [] }, ...BASE_FACETS];

// Which field of a unit each facet reads.
const FIELD = { odeljak: "section", povod: "tags", kome: "addressees", duzina: "length" };

/** A state with no chips: every facet empty. */
export function emptyState() {
  return { odeljak: [], povod: [], kome: [], duzina: [] };
}

/** The four facets, the section facet filled from the sections of the book. */
export function makeFacets(sections) {
  const odeljak = {
    id: "odeljak",
    label: "Одељак",
    values: sections.map((section) => ({ id: section.id, label: section.title })),
  };
  return [odeljak, ...BASE_FACETS];
}

/** The length tier of a unit with this many words (about 150 words a minute). */
export function lengthOf(words) {
  if (words < 150) return "kratka";
  if (words <= 450) return "srednja";
  return "duga";
}

/** The units that pass every facet: chips inside a facet are "or", facets are "and". */
export function applyFilters(units, state) {
  const chips = state ?? {};
  return units.filter((unit) =>
    Object.entries(FIELD).every(([facet, field]) => {
      const wanted = chips[facet];
      if (!wanted || wanted.length === 0) return true;
      const has = unit[field];
      return Array.isArray(has)
        ? wanted.some((value) => has.includes(value))
        : wanted.includes(has);
    }),
  );
}

/**
 * The units a random draw may pick from: those that pass the filters. When no
 * length chip is set, long units are left out, so that the result can be read
 * in about three minutes.
 */
export function randomPool(units, state) {
  const passing = applyFilters(units, state);
  const lengthChosen = Boolean(state?.duzina?.length);
  return lengthChosen ? passing : passing.filter((unit) => unit.length !== "duga");
}

// A value is accepted when the facet lists it, or when the facet lists nothing
// (the sections are not loaded): section ids come from the data, not from a
// fixed list.
const accepted = (facet, value, known) => value !== "" && (known.size === 0 || known.has(value));

/** The filter state encoded in the query of the address. */
export function parseFilterState(query, facets = FACETS) {
  const params = new URLSearchParams(query ?? "");
  const state = emptyState();
  for (const facet of facets) {
    const known = new Set(facet.values.map((value) => value.id));
    const values = params
      .getAll(facet.id)
      .filter((value) => accepted(facet, value, known))
      .sort();
    state[facet.id] = [...new Set(values)];
  }
  return state;
}

/** The query of the address for a filter state: facets in order, values sorted. */
export function formatFilterState(state, facets = FACETS) {
  const chips = state ?? {};
  const parts = [];
  for (const facet of facets) {
    const known = new Set(facet.values.map((value) => value.id));
    const values = [...new Set(chips[facet.id] ?? [])]
      .filter((value) => accepted(facet, value, known))
      .sort();
    for (const value of values) parts.push(`${facet.id}=${encodeURIComponent(value)}`);
  }
  return parts.join("&");
}

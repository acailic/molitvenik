import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  BASE_FACETS,
  FACETS,
  applyFilters,
  formatFilterState,
  lengthOf,
  makeFacets,
  parseFilterState,
  randomPool,
} from "../../app/filters.js";

const sample = JSON.parse(
  readFileSync(new URL("../fixtures/site/prayers.sample.json", import.meta.url), "utf8"),
);
const units = sample.units;
const facets = makeFacets(sample.sections);

const ids = (list) => list.map((unit) => unit.id);
// A filter state with the given chips; the facets not named have none.
const state = (chips = {}) => ({ odeljak: [], povod: [], kome: [], duzina: [], ...chips });

const ALL = ids(units);
const WITHOUT_LONG = ALL.filter((id) => id !== "pred-pricesce__primer-duga");

// ---- Facets ------------------------------------------------------------------------------------

test("BASE_FACETS holds the three curated facets with the labels of the plan", () => {
  assert.deepEqual(
    BASE_FACETS,
    [
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
    ],
  );
});

test("makeFacets puts odeljak, filled from the sections, before the curated facets", () => {
  assert.deepEqual(
    facets.map((facet) => facet.id),
    ["odeljak", "povod", "kome", "duzina"],
  );
  assert.deepEqual(facets[0], {
    id: "odeljak",
    label: "Одељак",
    values: [
      { id: "jutarnje", label: "Молитве јутарње" },
      { id: "pred-pricesce", label: "Молитвено правило пред Свето причешће" },
      { id: "jela", label: "Молитве пре и после јела" },
    ],
  });
  assert.deepEqual(facets.slice(1), BASE_FACETS);
});

test("FACETS has the four facets; its odeljak is empty until the sections are loaded", () => {
  assert.deepEqual(
    FACETS.map((facet) => facet.id),
    ["odeljak", "povod", "kome", "duzina"],
  );
  assert.deepEqual(FACETS[0], { id: "odeljak", label: "Одељак", values: [] });
  assert.deepEqual(FACETS.slice(1), BASE_FACETS);
});

test("facet ids and value ids are slugs, unique in their facet", () => {
  for (const facet of facets) {
    assert.match(facet.id, /^[a-z0-9-]+$/);
    const valueIds = facet.values.map((value) => value.id);
    assert.equal(new Set(valueIds).size, valueIds.length, facet.id);
    for (const id of valueIds) assert.match(id, /^[a-z0-9-]+$/);
  }
});

test("every tag and addressee of the sample has a chip", () => {
  const chips = Object.fromEntries(
    facets.map((facet) => [facet.id, new Set(facet.values.map((value) => value.id))]),
  );
  for (const unit of units) {
    for (const tag of unit.tags) assert.ok(chips.povod.has(tag), `${unit.id}: ${tag}`);
    for (const addressee of unit.addressees) {
      assert.ok(chips.kome.has(addressee), `${unit.id}: ${addressee}`);
    }
  }
});

// ---- Length ------------------------------------------------------------------------------------

test("lengthOf: under 150 words is kratka, 150 to 450 srednja, over 450 duga", () => {
  assert.equal(lengthOf(0), "kratka");
  assert.equal(lengthOf(149), "kratka");
  assert.equal(lengthOf(150), "srednja");
  assert.equal(lengthOf(450), "srednja");
  assert.equal(lengthOf(451), "duga");
});

test("lengthOf gives the length stored with every unit of the sample", () => {
  for (const unit of units) assert.equal(lengthOf(unit.words), unit.length, unit.id);
});

// ---- applyFilters ------------------------------------------------------------------------------

test("applyFilters: an empty state returns all units", () => {
  for (const empty of [state(), {}, undefined]) {
    assert.deepEqual(ids(applyFilters(units, empty)), ALL);
  }
});

test("applyFilters: chips inside a facet are or", () => {
  assert.deepEqual(ids(applyFilters(units, state({ odeljak: ["jela", "jutarnje"] }))), [
    "jutarnje__pocetak",
    "jutarnje__care-nebeski",
    "jutarnje__sveti-boze",
    "jutarnje__slava-ocu",
    "jela__kraj",
  ]);
  assert.deepEqual(ids(applyFilters(units, state({ povod: ["zahvalnost", "uz-obrok"] }))), [
    "jutarnje__slava-ocu",
    "pred-pricesce__kada-se-slavni",
    "jela__kraj",
  ]);
});

test("applyFilters: a unit with several values is found by each of them", () => {
  // pocetak has two addressees; kada-se-slavni has two tags.
  assert.deepEqual(ids(applyFilters(units, state({ povod: ["pokajanje"] }))), [
    "pred-pricesce__kada-se-slavni",
    "pred-pricesce__primer-duga",
  ]);
  assert.deepEqual(ids(applyFilters(units, state({ kome: ["presveta-trojica"] }))), [
    "jutarnje__pocetak",
    "jutarnje__sveti-boze",
    "jutarnje__slava-ocu",
  ]);
});

test("applyFilters: facets are and", () => {
  assert.deepEqual(
    ids(applyFilters(units, state({ povod: ["u-svako-doba"], kome: ["gospod-isus-hrist"] }))),
    ["jutarnje__pocetak"],
  );
  assert.deepEqual(
    applyFilters(units, state({ povod: ["pokajanje"], kome: ["presveta-bogorodica"] })),
    [],
  );
  assert.deepEqual(
    ids(
      applyFilters(
        units,
        state({
          odeljak: ["jutarnje", "pred-pricesce"],
          povod: ["pokajanje", "u-svako-doba"],
          kome: ["gospod-isus-hrist", "presveta-bogorodica"],
          duzina: ["kratka"],
        }),
      ),
    ),
    ["jutarnje__pocetak", "pred-pricesce__pesma-5", "pred-pricesce__kada-se-slavni"],
  );
});

test("applyFilters: a length chip selects by the length stored with the unit", () => {
  assert.deepEqual(ids(applyFilters(units, state({ duzina: ["duga"] }))), [
    "pred-pricesce__primer-duga",
  ]);
});

test("applyFilters: every chip selects the units that carry its value", () => {
  // The sample has no unit for most values of the vocabulary, so each one gets a carrier.
  const plain = { id: "plain", section: "jutarnje", tags: [], addressees: [], length: "kratka" };
  for (const facet of facets) {
    for (const value of facet.values) {
      const carrier = {
        ...plain,
        id: "carrier",
        section: value.id,
        tags: [value.id],
        addressees: [value.id],
        length: value.id,
      };
      assert.deepEqual(
        applyFilters([plain, carrier], state({ [facet.id]: [value.id] })),
        [carrier],
        `${facet.id}=${value.id}`,
      );
    }
  }
});

test("applyFilters leaves the units and the state as they were", () => {
  const chips = state({ povod: ["uz-obrok", "zahvalnost"], duzina: ["kratka"] });
  const before = JSON.stringify({ units, chips });
  applyFilters(units, chips);
  assert.equal(JSON.stringify({ units, chips }), before);
});

// ---- randomPool --------------------------------------------------------------------------------

test("randomPool: without a length chip the long units are left out", () => {
  assert.deepEqual(ids(randomPool(units, state())), WITHOUT_LONG);
  assert.deepEqual(ids(randomPool(units, state({ povod: ["pokajanje"] }))), [
    "pred-pricesce__kada-se-slavni",
  ]);
});

test("randomPool: the other filters narrow the pool", () => {
  assert.deepEqual(ids(randomPool(units, state({ odeljak: ["pred-pricesce"] }))), [
    "pred-pricesce__pesma-5",
    "pred-pricesce__kada-se-slavni",
  ]);
  assert.deepEqual(ids(randomPool(units, state({ odeljak: ["jela"] }))), ["jela__kraj"]);
});

test("randomPool: a length chip decides, so a long unit can be drawn", () => {
  assert.deepEqual(ids(randomPool(units, state({ duzina: ["duga"] }))), [
    "pred-pricesce__primer-duga",
  ]);
  assert.deepEqual(ids(randomPool(units, state({ povod: ["pokajanje"], duzina: ["duga"] }))), [
    "pred-pricesce__primer-duga",
  ]);

  const medium = { ...units[0], id: "probe__srednja", words: 300, length: lengthOf(300) };
  assert.deepEqual(ids(randomPool([...units, medium], state({ duzina: ["srednja"] }))), [
    "probe__srednja",
  ]);
  assert.deepEqual(ids(randomPool([...units, medium], state())), [...WITHOUT_LONG, "probe__srednja"]);
});

// ---- Address -----------------------------------------------------------------------------------

test("parseFilterState reads the filter state of an address", () => {
  assert.deepEqual(
    parseFilterState("povod=pokajanje&duzina=kratka"),
    state({ povod: ["pokajanje"], duzina: ["kratka"] }),
  );
});

test("parseFilterState: an empty or missing query is the empty state", () => {
  for (const query of ["", undefined]) assert.deepEqual(parseFilterState(query), state());
});

test("parseFilterState drops unknown facets and unknown values", () => {
  assert.deepEqual(
    parseFilterState("q=oce&foo=bar&povod=nepostoji&duzina=KRATKA&povod=&kome=bog-otac"),
    state({ kome: ["bog-otac"] }),
  );
});

test("parseFilterState keeps section ids: they come from the data, not from a fixed list", () => {
  assert.deepEqual(parseFilterState("odeljak=jela"), state({ odeljak: ["jela"] }));
  // With the sections loaded, a section that does not exist is dropped like any unknown value.
  assert.deepEqual(
    parseFilterState("odeljak=jela&odeljak=nema-ga", facets),
    state({ odeljak: ["jela"] }),
  );
});

test("parseFilterState decodes the address before it checks the ids", () => {
  assert.deepEqual(parseFilterState("povod=pokaja%6Eanje"), state({ povod: ["pokajanje"] }));
  assert.deepEqual(parseFilterState("povod=pokajanje%26duzina%3Dduga"), state());
});

test("formatFilterState: the empty state is an empty string", () => {
  for (const empty of [state(), {}, undefined]) assert.equal(formatFilterState(empty), "");
});

test("formatFilterState orders the facets as FACETS do and sorts the values", () => {
  assert.equal(
    formatFilterState({
      duzina: ["srednja", "kratka"],
      kome: [],
      povod: ["zahvalnost"],
      odeljak: ["jela"],
    }),
    "odeljak=jela&povod=zahvalnost&duzina=kratka&duzina=srednja",
  );
});

test("formatFilterState leaves out unknown facets and unknown values", () => {
  assert.equal(
    formatFilterState({ povod: ["nepostoji"], duzina: ["duga"], foo: ["bar"] }),
    "duzina=duga",
  );
  assert.equal(
    formatFilterState({ odeljak: ["nema-ga"], duzina: ["duga"] }, facets),
    "duzina=duga",
  );
});

test("formatFilterState undoes parseFilterState for every canonical address", () => {
  const addresses = [
    "povod=pokajanje",
    "povod=pokajanje&duzina=kratka",
    "odeljak=jela&odeljak=jutarnje&povod=pokajanje&povod=zahvalnost&kome=bog-otac&duzina=duga",
    "duzina=kratka&duzina=srednja",
  ];
  for (const address of addresses) {
    assert.equal(formatFilterState(parseFilterState(address)), address);
  }
});

test("parseFilterState reads back what formatFilterState wrote", () => {
  const written = formatFilterState(state({ odeljak: ["jela"], povod: ["zahvalnost"] }));
  assert.equal(written, "odeljak=jela&povod=zahvalnost");
  assert.deepEqual(
    parseFilterState(written),
    state({ odeljak: ["jela"], povod: ["zahvalnost"] }),
  );
});

test("a repeated value is kept once", () => {
  assert.deepEqual(
    parseFilterState("povod=zahvalnost&povod=pokajanje&povod=zahvalnost"),
    state({ povod: ["pokajanje", "zahvalnost"] }),
  );
  assert.equal(formatFilterState(state({ povod: ["zahvalnost", "pokajanje", "zahvalnost"] })), "povod=pokajanje&povod=zahvalnost");
});

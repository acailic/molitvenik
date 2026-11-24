import test from "node:test";
import assert from "node:assert/strict";

import { parseHash, buildHash, onRouteChange } from "../../app/router.js";

const NO_FILTERS = { odeljak: [], povod: [], kome: [], duzina: [] };

test("parseHash: home, with and without the hash mark", () => {
  const expected = { view: "home", id: null, query: "", state: NO_FILTERS };
  assert.deepEqual(parseHash("#/"), expected);
  assert.deepEqual(parseHash(""), expected);
});

test("parseHash: home with filter state and a search word", () => {
  assert.deepEqual(parseHash("#/?povod=pokajanje&duzina=kratka&q=pomiluj"), {
    view: "home",
    id: null,
    query: "q=pomiluj",
    state: { odeljak: [], povod: ["pokajanje"], kome: [], duzina: ["kratka"] },
  });
});

test("parseHash: two chips of one facet come as a repeated key", () => {
  const { state } = parseHash("#/?povod=pokajanje&povod=zahvalnost");
  assert.deepEqual(state.povod, ["pokajanje", "zahvalnost"]);
});

test("parseHash: a prayer", () => {
  assert.deepEqual(parseHash("#/molitva/jutarnje__pocetak"), {
    view: "prayer",
    id: "jutarnje__pocetak",
    query: "",
    state: NO_FILTERS,
  });
});

test("parseHash: a section", () => {
  assert.deepEqual(parseHash("#/odeljak/jutarnje"), {
    view: "section",
    id: "jutarnje",
    query: "",
    state: NO_FILTERS,
  });
});

test("parseHash: an unknown route falls back to home", () => {
  for (const hash of ["#/nesto", "#/molitva", "#/molitva/a/b", "#/odeljak/", "#sadrzaj"]) {
    assert.equal(parseHash(hash).view, "home", hash);
  }
  // names every object has: they must not pass for a view
  for (const hash of ["#/constructor/x", "#/__proto__/x", "#/valueOf/x", "#/toString/x", "#/hasOwn/x"]) {
    assert.deepEqual(parseHash(hash), { view: "home", id: null, query: "", state: NO_FILTERS }, hash);
  }
  assert.deepEqual(parseHash("#/nesto?q=x"), { view: "home", id: null, query: "q=x", state: NO_FILTERS });
});

test("parseHash: parameters that are not facets stay in the query as written", () => {
  assert.equal(parseHash("#/?q=%D0%BF%D0%BE&odeljak=jutarnje&vrsta=x").query, "q=%D0%BF%D0%BE&vrsta=x");
});

test("buildHash: home, prayer and section", () => {
  assert.equal(buildHash({ view: "home", id: null, query: "", state: NO_FILTERS }), "#/");
  assert.equal(buildHash({ view: "prayer", id: "jutarnje__pocetak" }), "#/molitva/jutarnje__pocetak");
  assert.equal(buildHash({ view: "section", id: "jutarnje" }), "#/odeljak/jutarnje");
});

test("buildHash: facets keep their order, values are sorted, the query comes last", () => {
  const state = { odeljak: [], povod: ["zastita", "pokajanje"], kome: [], duzina: ["kratka"] };
  assert.equal(
    buildHash({ view: "home", id: null, query: "q=pomiluj", state }),
    "#/?povod=pokajanje&povod=zastita&duzina=kratka&q=pomiluj",
  );
});

test("round trip: a canonical address survives parsing and building", () => {
  const addresses = [
    "#/",
    "#/?povod=pokajanje&duzina=kratka",
    "#/?povod=pokajanje&povod=zahvalnost&q=pomiluj",
    "#/?q=%D0%BF%D0%BE%D0%BC%D0%B8%D0%BB%D1%83%D1%98",
    "#/molitva/jutarnje__pocetak",
    "#/odeljak/jutarnje",
  ];
  for (const hash of addresses) {
    assert.equal(buildHash(parseHash(hash)), hash);
  }
});

test("round trip: a route survives building and parsing", () => {
  const route = {
    view: "home",
    id: null,
    query: "q=pomiluj",
    state: { odeljak: ["jutarnje"], povod: ["pokajanje"], kome: [], duzina: [] },
  };
  assert.deepEqual(parseHash(buildHash(route)), route);
});

test("onRouteChange: calls back once at start, then on hashchange, until stopped", () => {
  const listeners = new Map();
  const location = { hash: "#/odeljak/jutarnje" };
  const previous = globalThis.window;
  globalThis.window = {
    location,
    addEventListener: (type, handler) => listeners.set(type, handler),
    removeEventListener: (type, handler) => {
      if (listeners.get(type) === handler) listeners.delete(type);
    },
  };
  try {
    const seen = [];
    const stop = onRouteChange((route) => seen.push(route));

    assert.deepEqual(seen, [{ view: "section", id: "jutarnje", query: "", state: NO_FILTERS }]);

    location.hash = "#/molitva/jutarnje__pocetak";
    listeners.get("hashchange")();
    assert.equal(seen.length, 2);
    assert.equal(seen[1].view, "prayer");

    stop();
    assert.equal(listeners.has("hashchange"), false);
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});

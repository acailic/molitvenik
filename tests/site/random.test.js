import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { pickRandom } from "../../app/random.js";
import { randomPool } from "../../app/filters.js";

const sample = JSON.parse(
  readFileSync(new URL("../fixtures/site/prayers.sample.json", import.meta.url), "utf8"),
);
const units = sample.units;

const ids = (list) => list.map((unit) => unit.id);

test("pickRandom never returns the excluded unit while the pool holds another", () => {
  for (const excluded of units) {
    const others = ids(units).filter((id) => id !== excluded.id).sort();
    // A sweep over the rng: only the other units come out, and each of them is reachable.
    const drawn = new Set();
    for (let step = 0; step < 100; step += 1) {
      drawn.add(pickRandom(units, excluded.id, () => step / 100).id);
    }
    assert.deepEqual([...drawn].sort(), others, excluded.id);
  }
});

test("pickRandom follows the rng: 0 is the first unit, just under 1 the last", () => {
  assert.equal(pickRandom(units, null, () => 0), units[0]);
  assert.equal(pickRandom(units, null, () => 0.999), units.at(-1));
  assert.equal(pickRandom(units, units[0].id, () => 0), units[1]);
});

test("pickRandom stays inside the pool when the rng returns 1", () => {
  assert.equal(pickRandom(units, null, () => 1), units.at(-1));
});

test("pickRandom returns the only unit of a one-unit pool, also when it is the excluded one", () => {
  assert.equal(pickRandom([units[0]], units[0].id, () => 0), units[0]);
  assert.equal(pickRandom([units[0]], null, () => 0), units[0]);
});

test("pickRandom returns null for an empty pool", () => {
  assert.equal(pickRandom([], null, () => 0), null);
  assert.equal(pickRandom([], units[0].id, () => 0), null);
});

test("pickRandom calls rng once", () => {
  for (const pool of [units, [units[0]]]) {
    let calls = 0;
    const rng = () => {
      calls += 1;
      return 0.5;
    };
    pickRandom(pool, null, rng);
    assert.equal(calls, 1);
  }
});

test("pickRandom draws from the whole pool with Math.random when no rng is given", () => {
  const drawn = new Set();
  for (let turn = 0; turn < 100; turn += 1) drawn.add(pickRandom(units).id);
  for (const id of drawn) assert.ok(ids(units).includes(id));
  assert.ok(drawn.size > 1);
});

test("the random draw never shows the unit on screen twice", () => {
  // What the home view does: draw from the filtered pool, leaving out the unit on screen.
  const noFilters = { odeljak: [], povod: [], kome: [], duzina: [] };
  const pool = randomPool(units, noFilters);
  for (const shown of units) {
    const drawn = pickRandom(pool, shown.id, () => 0.5);
    assert.ok(ids(pool).includes(drawn.id), drawn.id);
    assert.notEqual(drawn.id, shown.id);
  }
});

test("when the filters leave only the unit on screen, it is drawn again", () => {
  const pool = randomPool(units, { odeljak: ["jela"], povod: [], kome: [], duzina: [] });
  assert.deepEqual(ids(pool), ["jela__kraj"]);
  assert.equal(pickRandom(pool, "jela__kraj", () => 0.5), pool[0]);
});

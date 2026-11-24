// Wires the address, the views and the page. The only module that touches the page and storage.

import { searchKey } from "./text.js";
import { buildIndex, search } from "./search.js";
import { applyFilters, emptyState, makeFacets, randomPool } from "./filters.js";
import { pickRandom } from "./random.js";
import { buildHash, onRouteChange, parseHash } from "./router.js";
import * as view from "./views.js";

const FONT_STEPS = ["s", "m", "l"];
const FONT_KEY = "molitvenik.font";
const SEARCH_DELAY = 150;

const main = document.getElementById("sadrzaj");

// What the page holds between two changes of the address.
const site = {
  data: null,
  units: new Map(),
  sections: new Map(),
  entries: new Map(),
  index: [], // what the search reads
  facets: [],
  route: null,
  filters: emptyState(), // the chips on screen
  page: "", // view and id of the page on screen
  shown: null, // the prayer shown last
  timer: null, // a typed word on its way to the address
};

async function start() {
  syncFontButtons(document.documentElement.dataset.font);

  const data = await load();
  if (!data) {
    main.innerHTML = view.renderError();
    return;
  }

  site.data = data;
  site.facets = makeFacets(data.sections);
  for (const unit of data.units) site.units.set(unit.id, unit);
  for (const section of data.sections) site.sections.set(section.id, section);
  site.index = buildIndex(data.units);
  for (const entry of site.index) site.entries.set(entry.id, entry);
  document.querySelector(".footer").innerHTML = view.renderFooter(data.book);

  onRouteChange(show);
}

async function load() {
  try {
    const response = await fetch("data/prayers.json");
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function show(route) {
  const page = `${route.view}:${route.id ?? ""}`;
  const arrived = page !== site.page;
  const first = site.page === "";
  site.route = route;
  site.page = page;
  document.body.dataset.view = route.view;

  if (route.view === "prayer") showPrayer(route);
  else if (route.view === "section") showSection(route);
  else showHome(route, arrived);

  // A new page starts at its top, also for whoever reads with the keyboard.
  if (arrived && !first) {
    window.scrollTo(0, 0);
    main.focus({ preventScroll: true });
  }
}

// A shared address may name a value this book does not have. It gets no chip,
// so it must not narrow the list either.
function knownState(state) {
  const clean = emptyState();
  for (const facet of site.facets) {
    const known = new Set(facet.values.map((value) => value.id));
    clean[facet.id] = (state[facet.id] ?? []).filter((value) => known.has(value));
  }
  return clean;
}

function homeModel(route) {
  const { data, filters } = site;
  const typed = new URLSearchParams(route.query).get("q") ?? "";
  const q = typed.trim();
  const key = q ? searchKey(q) : "";
  const passing = applyFilters(data.units, filters);
  const hits = key
    ? search(site.index, key).map((found) => site.units.get(found.id)).filter((unit) => passing.includes(unit))
    : passing;
  return {
    book: data.book,
    units: data.units,
    sections: data.sections,
    facets: site.facets,
    entries: site.entries,
    state: filters,
    query: route.query,
    typed,
    q,
    key,
    hits,
    drawDisabled: randomPool(data.units, filters).length === 0,
  };
}

function showHome(route, arrived) {
  site.filters = knownState(route.state);
  const home = homeModel(route);
  document.title = site.data.book.title;

  if (arrived) {
    main.innerHTML = view.renderHome(home);
  } else {
    refineList(home);
  }
  syncSearchField(home.typed);
}

// The list changes under the visitor's hands: the search field must keep its focus.
function refineList(home) {
  const filters = document.getElementById("filteri");
  const held = document.activeElement;
  const focused = filters.contains(held) ? held : null;
  const open = filters.querySelector("details").open;

  filters.innerHTML = view.renderFilters(home);
  filters.querySelector("details").open = open;
  refocus(filters, focused);

  document.getElementById("broj").innerHTML = view.renderCount(home);
  document.getElementById("rezultati").innerHTML = view.renderList(home);
}

// The chips were drawn again; the one under the keyboard must not vanish from under it.
function refocus(filters, focused) {
  if (!focused) return;
  const chip = [...filters.querySelectorAll(".chip")].find(
    (candidate) =>
      candidate.dataset.facet === focused.dataset.facet && candidate.dataset.value === focused.dataset.value,
  );
  (chip ?? filters.querySelector("summary")).focus();
}

function showPrayer(route) {
  const unit = site.units.get(route.id);
  if (!unit) return missing("prayer");

  const section = site.sections.get(unit.section);
  const siblings = section ? section.units.map((id) => site.units.get(id)).filter(Boolean) : [unit];
  const at = siblings.indexOf(unit);
  site.shown = unit;

  // Nothing else to draw when the pool is empty or holds only the prayer on screen.
  const pool = randomPool(site.data.units, site.filters);
  main.innerHTML = view.renderPrayer({
    unit,
    section,
    place: at + 1,
    of: siblings.length,
    prev: siblings[at - 1] ?? null,
    next: siblings[at + 1] ?? null,
    drawDisabled: pool.length === 0 || (pool.length === 1 && pool[0].id === unit.id),
  });
  document.title = `${unit.title} — ${site.data.book.title}`;
}

function showSection(route) {
  const section = site.sections.get(route.id);
  if (!section) return missing("section");

  const units = (section.units ?? []).map((id) => site.units.get(id)).filter(Boolean);
  main.innerHTML = view.renderSection({ section, units });
  document.title = `${section.title} — ${site.data.book.title}`;
}

function missing(kind) {
  main.innerHTML = view.renderNotFound(kind);
  document.title = site.data.book.title;
}

// The random draw. The filters of the list the visitor came from still decide
// what a random prayer may be, and the prayer shown last is never drawn again.
function drawRandom() {
  const pool = randomPool(site.data.units, site.filters);
  const unit = pickRandom(pool, site.shown?.id ?? null);
  if (unit) window.location.hash = buildHash({ view: "prayer", id: unit.id });
}

function toggleChip(chip) {
  const { facet, value } = chip.dataset;
  const values = site.filters[facet];
  const next = values.includes(value) ? values.filter((other) => other !== value) : [...values, value];
  const state = { ...site.filters, [facet]: next };
  window.location.hash = buildHash({ view: "home", id: null, query: site.route.query, state });
}

// The field follows the address, unless a typed word is still on its way there.
function syncSearchField(typed) {
  const input = document.getElementById("pretraga");
  if (!input) return;
  if (site.timer === null && input.value !== typed) input.value = typed;
  const clear = main.querySelector("[data-action='clear-search']");
  if (clear) clear.hidden = !typed.trim();
}

function commitSearch(typed) {
  clearTimeout(site.timer);
  site.timer = null;
  if (site.route.view !== "home") return;

  const query = typed.trim() ? `q=${encodeURIComponent(typed)}` : "";
  if (query === site.route.query) {
    syncSearchField(typed);
    return;
  }
  // Typing refines the list on screen; it must not add a step to the history for every word.
  history.replaceState(null, "", buildHash({ view: "home", id: null, query, state: site.filters }));
  show(parseHash(window.location.hash));
}

function setFont(step) {
  if (!FONT_STEPS.includes(step)) return;
  document.documentElement.dataset.font = step;
  syncFontButtons(step);
  try {
    localStorage.setItem(FONT_KEY, step);
  } catch {
    // The size is kept for this page only.
  }
}

function syncFontButtons(step) {
  for (const button of document.querySelectorAll("[data-font-step]")) {
    button.setAttribute("aria-pressed", String(button.dataset.fontStep === step));
  }
}

async function copyAddress() {
  const address = window.location.href;
  let copied;
  try {
    await navigator.clipboard.writeText(address);
    copied = true;
  } catch {
    copied = copyByHand(address);
  }
  const status = main.querySelector(".share .status");
  if (status) status.textContent = copied ? "Линк је копиран." : "Линк није копиран. Копирајте адресу из адресне траке.";
}

// Without the clipboard interface (an insecure page, an old browser) the address
// goes through a field that is selected and copied the old way.
function copyByHand(address) {
  const field = document.createElement("textarea");
  field.value = address;
  field.setAttribute("readonly", "");
  field.className = "clipboard-helper";
  document.body.appendChild(field);
  field.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  field.remove();
  return copied;
}

// The link opens the prayer on its own page. A plain click stays here and scrolls to it,
// because the address belongs to the router and cannot hold the place in the page.
function jump(event, id) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const unit = document.getElementById(id);
  if (!unit) return;
  event.preventDefault();
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  unit.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
  unit.focus({ preventScroll: true });
}

function skip(event) {
  // The target is named in the address, and the address belongs to the router.
  event.preventDefault();
  main.focus();
  window.scrollTo(0, 0);
}

document.addEventListener("click", (event) => {
  const target = event.target.closest?.("button, a");
  if (!target) return;
  const { action, fontStep, scroll } = target.dataset;

  if (fontStep) setFont(fontStep);
  else if (action === "random") drawRandom();
  else if (action === "chip") toggleChip(target);
  else if (action === "clear-search") {
    commitSearch("");
    // The button that was pressed is gone with the word; the hand stays on the search.
    document.getElementById("pretraga")?.focus();
  }
  else if (action === "copy") copyAddress();
  else if (action === "reload") window.location.reload();
  else if (scroll) jump(event, scroll);
  else if (target.classList.contains("skip")) skip(event);
});

main.addEventListener("input", (event) => {
  if (event.target.id !== "pretraga") return;
  clearTimeout(site.timer);
  site.timer = setTimeout(() => commitSearch(event.target.value), SEARCH_DELAY);
});

document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-role='search']");
  if (!form) return;
  event.preventDefault();
  commitSearch(form.querySelector("input").value);
});

start().catch(() => {
  main.innerHTML = view.renderError();
});

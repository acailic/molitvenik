// Addresses of the site. Parsing and building are pure; only onRouteChange looks at the window.

const FACET_IDS = ["odeljak", "povod", "kome", "duzina"];

// First path segment → view. Anything else is not a route.
const VIEWS = { molitva: "prayer", odeljak: "section" };
const SEGMENTS = { prayer: "molitva", section: "odeljak" };

export function emptyState() {
  return { odeljak: [], povod: [], kome: [], duzina: [] };
}

// A malformed escape must not turn a typed or pasted address into an exception.
function decode(value) {
  try {
    return decodeURIComponent(value.replace(/\+/g, " "));
  } catch {
    return value;
  }
}

// Facet parameters become `state`; every other parameter stays in `query` as written,
// so the address of a search can be put back unchanged.
export function parseHash(hash) {
  const route = { view: "home", id: null, query: "", state: emptyState() };

  let path = String(hash ?? "");
  if (path.startsWith("#")) path = path.slice(1);

  const mark = path.indexOf("?");
  const rawQuery = mark === -1 ? "" : path.slice(mark + 1);
  if (mark !== -1) path = path.slice(0, mark);
  if (!path.startsWith("/")) path = `/${path}`;

  const [head, id, extra] = path.split("/").filter(Boolean);
  // Only the views themselves: a plain lookup would also find „constructor" and the like.
  const view = Object.hasOwn(VIEWS, head) ? VIEWS[head] : undefined;
  if (view && id !== undefined && extra === undefined) {
    route.view = view;
    route.id = decode(id);
  }

  const rest = [];
  for (const pair of rawQuery.split("&")) {
    if (!pair) continue;
    const equal = pair.indexOf("=");
    const key = equal === -1 ? pair : pair.slice(0, equal);
    const rawValue = equal === -1 ? "" : pair.slice(equal + 1);
    if (FACET_IDS.includes(key)) {
      const value = decode(rawValue);
      const values = route.state[key];
      if (value && !values.includes(value)) values.push(value);
    } else {
      rest.push(pair);
    }
  }
  route.query = rest.join("&");

  return route;
}

// Facets come in their fixed order with sorted values, so one filter state has one address.
export function buildHash(route = {}) {
  const segment = SEGMENTS[route.view];
  let hash = "#/";
  if (segment && route.id) hash = `#/${segment}/${encodeURIComponent(route.id)}`;

  const params = [];
  const state = route.state ?? {};
  for (const facet of FACET_IDS) {
    for (const value of [...(state[facet] ?? [])].sort()) {
      params.push(`${facet}=${encodeURIComponent(value)}`);
    }
  }
  if (route.query) params.push(route.query);

  return params.length ? `${hash}?${params.join("&")}` : hash;
}

// Calls back with the parsed route now and after every change of the address.
// Returns a function that stops the calls.
export function onRouteChange(callback) {
  const handler = () => callback(parseHash(window.location.hash));
  window.addEventListener("hashchange", handler);
  handler();
  return () => window.removeEventListener("hashchange", handler);
}

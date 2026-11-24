// The random draw.
//
// Pure function: no DOM, no storage.

/**
 * Draw one unit from the pool. The unit on screen (`excludeId`) is never drawn
 * again while the pool holds another unit; `rng` is called exactly once, so
 * that a draw can be replayed in tests. Returns null for an empty pool.
 */
export function pickRandom(pool, excludeId = null, rng = Math.random) {
  if (pool.length === 0) return null;
  let candidates = pool;
  if (excludeId !== null && pool.length > 1) {
    candidates = pool.filter((unit) => unit.id !== excludeId);
    if (candidates.length === 0) candidates = pool;
  }
  const value = rng();
  const index = Math.min(candidates.length - 1, Math.floor(value * candidates.length));
  return candidates[index];
}

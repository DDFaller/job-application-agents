export function selectCandidatesAcrossSources(prepared, limit) {
  if (limit <= 0 || !prepared.length) return [];

  const ranked = [...prepared].sort(
    (left, right) => right.decision.score - left.decision.score
  );
  const byPortal = new Map();
  for (const item of ranked) {
    const portal = item.candidate.source_portal;
    if (!byPortal.has(portal)) byPortal.set(portal, []);
    byPortal.get(portal).push(item);
  }

  const portalCount = byPortal.size;
  const reservedPerPortal = Math.max(1, Math.floor(limit / (portalCount * 2)));
  const selected = [];
  const selectedUrls = new Set();
  const add = (item) => {
    if (!item || selected.length >= limit) return;
    const url = item.candidate.source_url;
    if (selectedUrls.has(url)) return;
    selected.push(item);
    selectedUrls.add(url);
  };

  for (const jobs of byPortal.values()) {
    for (const item of jobs.slice(0, reservedPerPortal)) add(item);
  }
  for (const item of ranked) add(item);

  return selected.sort((left, right) => right.decision.score - left.decision.score);
}

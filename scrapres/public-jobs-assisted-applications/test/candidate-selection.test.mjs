import assert from "node:assert/strict";
import test from "node:test";
import { selectCandidatesAcrossSources } from "../lib/candidate-selection.mjs";

function candidate(source_portal, score, reference) {
  return {
    candidate: {
      source_portal,
      source_url: `https://example.test/${reference}`,
      reference
    },
    decision: { score }
  };
}

test("reserva espaço para cada fonte aceita sem abandonar a ordem de score", () => {
  const prepared = [
    ...Array.from({ length: 20 }, (_, index) =>
      candidate("france-travail", 100 - index, `ft-${index}`)
    ),
    candidate("emploi-territorial", 70, "et-1"),
    candidate("emploi-territorial", 69, "et-2"),
    candidate("emploi-territorial", 68, "et-3")
  ];
  const selected = selectCandidatesAcrossSources(prepared, 15);
  const territorial = selected.filter(
    (item) => item.candidate.source_portal === "emploi-territorial"
  );

  assert.equal(selected.length, 15);
  assert.equal(territorial.length, 3);
  assert.deepEqual(
    territorial.map((item) => item.candidate.reference),
    ["et-1", "et-2", "et-3"]
  );
});

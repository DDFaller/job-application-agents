import assert from "node:assert/strict";
import test from "node:test";
import { notionItemFromJob } from "../notion-outbox.mjs";

test("gera payload revisável compatível com Job Applications", () => {
  const item = notionItemFromJob(
    {
      source_portal: "emploi-territorial",
      source_url: "https://www.emploi-territorial.fr/offre/o001-test",
      reference: "O001",
      title: "Agent administratif",
      employer: "Mairie test",
      location: "Ville test",
      remote_work: "Oui",
      summary: "Gestion administrative.",
      requirements: ["Rigueur"],
      match_reasons: ["accueil des usagers"],
      gaps: [],
      match_score: 85,
      potential: "Fort",
      rank: 1,
      profile_version: "v001",
      filter_version: "v001-csv-compatible",
      application_deadline: "2026-09-30"
    },
    "2026-08-24T12:00:00.000Z"
  );

  assert.equal(item.properties.Status, "TO_APPLY");
  assert.equal(item.properties["Work Model"], "Hybrid");
  assert.equal(item.properties["Source Job ID"], "O001");
  assert.equal(item.properties["date:Next Action At:start"], "2026-09-30");
  assert.match(item.content_markdown, /# Match Analysis/);
});

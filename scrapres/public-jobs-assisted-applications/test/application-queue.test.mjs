import assert from "node:assert/strict";
import test from "node:test";
import {
  APPLICATION_STATUS,
  attachApplicationBundle,
  createApplicationHandoff,
  createEmptyApplicationQueue,
  linkApplicationUrl,
  markApplicationApplied,
  markApplicationOpened,
  upsertApplication
} from "../lib/application-queue.mjs";

const NOW = "2026-08-25T10:00:00.000Z";

function sampleQueue() {
  const queue = createEmptyApplicationQueue(NOW);
  upsertApplication(
    queue,
    {
      reference: "O001",
      title: "Agent administratif",
      employer: "Mairie test",
      source_url: "https://www.emploi-territorial.fr/offre/o001-test",
      match_score: 82
    },
    NOW
  );
  return queue;
}

test("importa vaga ranqueada e permite ligar uma URL do LinkedIn", () => {
  const queue = sampleQueue();
  const item = linkApplicationUrl(
    queue,
    "O001",
    "https://www.linkedin.com/jobs/view/987654",
    NOW
  );
  assert.equal(item.platform, "linkedin");
  assert.equal(item.platform_job_id, "987654");
  assert.equal(item.status, APPLICATION_STATUS.TO_PREPARE);
});

test("handoff pede preparação sem envio", () => {
  const queue = sampleQueue();
  const handoff = createApplicationHandoff(queue.items[0], NOW);
  assert.equal(handoff.skill, "prepare-job-application");
  assert.match(handoff.suggested_prompt, /sem enviá-la/);
  assert.ok(handoff.instructions.some((value) => value.includes("Não envie")));
});

test("exige bundle antes de abrir e confirmação antes de marcar APPLIED", () => {
  const queue = sampleQueue();
  assert.throws(() => markApplicationOpened(queue, "O001", NOW), /Anexe primeiro/);
  attachApplicationBundle(queue, "O001", "/private/bundle", NOW);
  const opened = markApplicationOpened(queue, "O001", NOW);
  assert.equal(opened.status, APPLICATION_STATUS.OPENED);
  assert.throws(() => markApplicationApplied(queue, "O001"), /--confirmed/);
  const applied = markApplicationApplied(queue, "O001", { confirmed: true, now: NOW });
  assert.equal(applied.status, APPLICATION_STATUS.APPLIED);
  assert.equal(applied.applied_at, NOW);
});

test("deduplica a mesma URL de candidatura", () => {
  const queue = createEmptyApplicationQueue(NOW);
  const job = {
    title: "Support",
    employer: "Example",
    source_url: "https://fr.indeed.com/viewjob?jk=abc"
  };
  upsertApplication(queue, job, NOW);
  upsertApplication(queue, { ...job, title: "Support informatique" }, NOW);
  assert.equal(queue.items.length, 1);
  assert.equal(queue.items[0].title, "Support informatique");
});

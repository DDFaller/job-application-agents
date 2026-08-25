import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { parseCspListing } from "../discover-csp.mjs";
import { parseTerritorialListing } from "../discover-emploi-territorial.mjs";
import { extractCspJsonLd, extractVisibleJobText } from "../extract-job.mjs";
import { identifyPortal, referenceFromUrl } from "../lib/utils.mjs";

const cspHtml = await readFile(new URL("./fixtures/csp.html", import.meta.url), "utf8");
const territorialHtml = await readFile(
  new URL("./fixtures/territorial.html", import.meta.url),
  "utf8"
);

test("descobre e deduplica vagas CSP", () => {
  const jobs = parseCspListing(cspHtml);
  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].reference, "2026-123");
});

test("lê o JobPosting JSON-LD do CSP", () => {
  assert.equal(extractCspJsonLd(cspHtml).title, "Agent administratif");
});

test("descobre vaga e referência do Emploi Territorial", () => {
  const jobs = parseTerritorialListing(territorialHtml);
  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].reference, "O075260824000001");
});

test("limpa o conteúdo visível da vaga", () => {
  const text = extractVisibleJobText(territorialHtml);
  assert.match(text, /Missions du poste/);
});

test("bloqueia domínios e caminhos não autorizados", () => {
  assert.equal(
    identifyPortal(
      "https://choisirleservicepublic.gouv.fr/offre-emploi/test-reference-123/"
    ),
    "choisir-service-public"
  );
  assert.throws(() => identifyPortal("https://example.com/offre/123"));
  assert.throws(() =>
    identifyPortal("https://www.emploi-territorial.fr/exportoffres/test")
  );
  assert.equal(
    identifyPortal(
      "https://candidat.francetravail.fr/offres/recherche/detail/190ABCD"
    ),
    "france-travail"
  );
  assert.equal(
    referenceFromUrl(
      "https://www.emploi-territorial.fr/offre/o075260824000001-agent-administratif"
    ),
    "O075260824000001"
  );
  assert.equal(
    referenceFromUrl(
      "https://candidat.francetravail.fr/offres/recherche/detail/190ABCD"
    ),
    "190ABCD"
  );
});

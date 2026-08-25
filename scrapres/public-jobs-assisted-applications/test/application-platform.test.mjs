import assert from "node:assert/strict";
import test from "node:test";
import {
  identifyApplicationPlatform,
  normalizeApplicationUrl
} from "../lib/application-queue.mjs";

test("identifica uma vaga específica do LinkedIn e remove rastreamento", () => {
  const result = identifyApplicationPlatform(
    "https://www.linkedin.com/jobs/view/123456/?trk=test&utm_source=x"
  );
  assert.equal(result.platform, "linkedin");
  assert.equal(result.platform_job_id, "123456");
  assert.equal(result.application_url, "https://www.linkedin.com/jobs/view/123456/");
});

test("identifica uma vaga específica do Indeed", () => {
  const result = identifyApplicationPlatform(
    "https://fr.indeed.com/viewjob?jk=abc123&utm_campaign=test"
  );
  assert.equal(result.platform, "indeed");
  assert.equal(result.platform_job_id, "abc123");
  assert.equal(result.application_url, "https://fr.indeed.com/viewjob?jk=abc123");
});

test("mantém ATS externo como aplicação manual", () => {
  const result = identifyApplicationPlatform("https://jobs.example.org/opening/42");
  assert.equal(result.platform, "employer-site");
});

test("rejeita HTTP e credenciais embutidas", () => {
  assert.throws(() => normalizeApplicationUrl("http://example.org/job"), /HTTPS/);
  assert.throws(
    () => normalizeApplicationUrl("https://user:secret@example.org/job"),
    /credenciais/
  );
});

test("rejeita páginas genéricas de LinkedIn e Indeed", () => {
  assert.throws(
    () => identifyApplicationPlatform("https://www.linkedin.com/jobs/"),
    /vaga específica/
  );
  assert.throws(
    () => identifyApplicationPlatform("https://fr.indeed.com/jobs?q=assistant"),
    /vaga específica/
  );
});

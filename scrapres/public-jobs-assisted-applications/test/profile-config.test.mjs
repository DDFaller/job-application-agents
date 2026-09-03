import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import {
  DEFAULT_PROFILE_PATH,
  PROJECT_ROOT,
  loadSearchProfile,
  validateSearchProfile
} from "../lib/search-profile.mjs";

test("carrega o preset administrativo sem dados pessoais", () => {
  const { profile, path } = loadSearchProfile({ profilePath: DEFAULT_PROFILE_PATH });
  assert.equal(profile.id, "administrative-fr");
  assert.equal(profile.career_profile_current, "");
  assert.deepEqual(Object.values(profile.evidence).flat(), []);
  assert.ok(profile.france_travail.keywords.includes("agent administratif"));
  assert.equal(path, DEFAULT_PROFILE_PATH);
});

test("permite selecionar o preset de suporte de TI", () => {
  const { profile } = loadSearchProfile({
    profilePath: "config/profiles/it-support-fr.json"
  });
  assert.equal(profile.id, "it-support-fr");
  assert.ok(profile.direct_match_rules.length > 0);
});

test("o preset de TI altera o pré-filtro em um processo isolado", () => {
  const script = `
    import { preFilterSource } from "./rank-jobs.mjs";
    const result = preFilterSource({
      format: "schema.org/JobPosting",
      content: JSON.stringify({
        title: "Technicien support informatique",
        description: "Support utilisateurs et gestion des incidents"
      })
    });
    process.stdout.write(JSON.stringify(result));
  `;
  const child = spawnSync(process.execPath, ["--input-type=module", "--eval", script], {
    cwd: PROJECT_ROOT,
    env: {
      ...process.env,
      JOB_SEARCH_PROFILE: "config/profiles/it-support-fr.json"
    },
    encoding: "utf8"
  });
  assert.equal(child.status, 0, child.stderr);
  const result = JSON.parse(child.stdout);
  assert.equal(result.accepted, true);
  assert.ok(result.score >= 42);
});

test("rejeita perfis incompletos antes do ranking", () => {
  assert.throws(
    () => validateSearchProfile({ schema_version: 1 }, "teste"),
    /id deve ser uma string não vazia/
  );
});

test("exige evidência para cada regra direta de um perfil ligado ao currículo", () => {
  const { profile } = loadSearchProfile({ profilePath: DEFAULT_PROFILE_PATH });
  profile.career_profile_current = "/tmp/current.json";
  assert.throws(
    () => validateSearchProfile(profile, "teste"),
    /exige ao menos um ID/
  );
});

test("rejeita mais de cinco departamentos na pesquisa France Travail", () => {
  const { profile } = loadSearchProfile({ profilePath: DEFAULT_PROFILE_PATH });
  profile.france_travail.departments = ["75", "77", "78", "91", "92", "93"];
  assert.throws(
    () => validateSearchProfile(profile, "teste"),
    /no máximo 5 departamentos/
  );
});

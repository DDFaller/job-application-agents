import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import "./env.mjs";

export const PROJECT_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  ".."
);

export const DEFAULT_PROFILE_PATH = path.join(
  PROJECT_ROOT,
  "config",
  "profiles",
  "administrative-fr.json"
);

export const LOCAL_PROFILE_PATH = path.join(
  PROJECT_ROOT,
  "config",
  "profile.local.json"
);

function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} deve ser um objeto.`);
  }
}

function requireStringArray(value, label) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${label} deve ser uma lista de strings.`);
  }
}

function requireNumber(value, label, { min = 0, max = 100 } = {}) {
  if (!Number.isFinite(value) || value < min || value > max) {
    throw new Error(`${label} deve ser um número entre ${min} e ${max}.`);
  }
}

function validateTermRules(rules, label, sources) {
  if (!Array.isArray(rules)) throw new Error(`${label} deve ser uma lista.`);
  for (const [index, rule] of rules.entries()) {
    requireObject(rule, `${label}[${index}]`);
    requireStringArray(rule.terms, `${label}[${index}].terms`);
    if (!rule.terms.length) throw new Error(`${label}[${index}].terms não pode ser vazio.`);
    if (rule.source !== undefined && !sources.includes(rule.source)) {
      throw new Error(`${label}[${index}].source inválido: ${rule.source}.`);
    }
    requireNumber(rule.points, `${label}[${index}].points`, { min: -100, max: 100 });
  }
}

export function validateSearchProfile(profile, source = "perfil") {
  requireObject(profile, source);
  if (profile.schema_version !== 1) {
    throw new Error(`${source}: schema_version deve ser 1.`);
  }
  for (const key of ["id", "display_name", "profile_version"]) {
    if (typeof profile[key] !== "string" || !profile[key].trim()) {
      throw new Error(`${source}: ${key} deve ser uma string não vazia.`);
    }
  }
  if (
    profile.career_profile_current !== undefined &&
    typeof profile.career_profile_current !== "string"
  ) {
    throw new Error(`${source}: career_profile_current deve ser uma string.`);
  }

  requireNumber(profile.top_count, `${source}.top_count`, { min: 1, max: 100 });
  requireNumber(profile.minimum_notion_score, `${source}.minimum_notion_score`);
  requireNumber(profile.preliminary_threshold, `${source}.preliminary_threshold`);
  if (profile.candidate_experience_years !== undefined) {
    requireNumber(
      profile.candidate_experience_years,
      `${source}.candidate_experience_years`,
      { min: 0, max: 60 }
    );
  }
  for (const field of ["required_departments", "required_regions"]) {
    if (profile[field] !== undefined) {
      requireStringArray(profile[field], `${source}.${field}`);
    }
  }
  for (const department of profile.required_departments ?? []) {
    if (!/^(?:2[AB]|\d{2,3})$/i.test(department.trim())) {
      throw new Error(`${source}.required_departments contém código inválido: ${department}.`);
    }
  }
  requireObject(profile.france_travail, `${source}.france_travail`);
  requireStringArray(
    profile.france_travail.keywords,
    `${source}.france_travail.keywords`
  );
  if (!profile.france_travail.keywords.length) {
    throw new Error(`${source}.france_travail.keywords não pode ser vazio.`);
  }
  requireStringArray(
    profile.france_travail.departments,
    `${source}.france_travail.departments`
  );
  if (profile.france_travail.departments.length > 5) {
    throw new Error(
      `${source}.france_travail.departments aceita no máximo 5 departamentos por consulta.`
    );
  }
  requireStringArray(profile.excluded_terms, `${source}.excluded_terms`);
  requireStringArray(profile.blocked_title_terms, `${source}.blocked_title_terms`);
  validateTermRules(
    profile.preliminary_title_rules,
    `${source}.preliminary_title_rules`,
    ["title"]
  );
  validateTermRules(
    profile.preliminary_bonus_rules,
    `${source}.preliminary_bonus_rules`,
    ["title", "combined"]
  );
  validateTermRules(
    profile.direct_match_rules,
    `${source}.direct_match_rules`,
    ["title", "all", "requirements"]
  );

  if (!Array.isArray(profile.gap_rules)) {
    throw new Error(`${source}.gap_rules deve ser uma lista.`);
  }
  for (const [index, rule] of profile.gap_rules.entries()) {
    requireObject(rule, `${source}.gap_rules[${index}]`);
    if (!["title", "all", "requirements"].includes(rule.source)) {
      throw new Error(`${source}.gap_rules[${index}].source inválido.`);
    }
    if (typeof rule.pattern !== "string" || typeof rule.label !== "string") {
      throw new Error(`${source}.gap_rules[${index}] exige pattern e label.`);
    }
    try {
      new RegExp(rule.pattern, rule.flags ?? "i");
    } catch (error) {
      throw new Error(`${source}.gap_rules[${index}] contém regex inválida: ${error.message}`);
    }
  }

  requireObject(profile.practical_locations, `${source}.practical_locations`);
  for (const tier of ["excellent", "strong", "acceptable"]) {
    requireStringArray(
      profile.practical_locations[tier],
      `${source}.practical_locations.${tier}`
    );
  }
  requireObject(profile.evidence, `${source}.evidence`);
  for (const [key, ids] of Object.entries(profile.evidence)) {
    requireStringArray(ids, `${source}.evidence.${key}`);
  }
  for (const [index, rule] of profile.direct_match_rules.entries()) {
    if (typeof rule.evidence_key !== "string" || !rule.evidence_key.trim()) {
      throw new Error(
        `${source}.direct_match_rules[${index}].evidence_key deve ser uma string não vazia.`
      );
    }
    if (!(rule.evidence_key in profile.evidence)) {
      throw new Error(
        `${source}.direct_match_rules[${index}] referencia evidence_key ausente: ${rule.evidence_key}.`
      );
    }
    if (profile.career_profile_current && !profile.evidence[rule.evidence_key].length) {
      throw new Error(
        `${source}.evidence.${rule.evidence_key} exige ao menos um ID quando o master curriculum está configurado.`
      );
    }
  }
  requireObject(profile.sector_signals, `${source}.sector_signals`);
  requireStringArray(
    profile.sector_signals.technology_terms,
    `${source}.sector_signals.technology_terms`
  );
  requireNumber(
    profile.sector_signals.technology_career_bonus,
    `${source}.sector_signals.technology_career_bonus`,
    { min: 0, max: 15 }
  );
  requireStringArray(profile.career_bonus_terms, `${source}.career_bonus_terms`);
  return profile;
}

export function resolveProjectPath(value) {
  if (!value) return "";
  return path.isAbsolute(value) ? value : path.resolve(PROJECT_ROOT, value);
}

function normalizeTerms(values) {
  return values.map((value) => value.toLocaleLowerCase("fr-FR"));
}

function normalizeSearchTerms(profile) {
  profile.excluded_terms = normalizeTerms(profile.excluded_terms);
  profile.blocked_title_terms = normalizeTerms(profile.blocked_title_terms);
  for (const rules of [
    profile.preliminary_title_rules,
    profile.preliminary_bonus_rules,
    profile.direct_match_rules
  ]) {
    for (const rule of rules) rule.terms = normalizeTerms(rule.terms);
  }
  profile.sector_signals.technology_terms = normalizeTerms(
    profile.sector_signals.technology_terms
  );
  profile.career_bonus_terms = normalizeTerms(profile.career_bonus_terms);
  profile.france_travail.keywords = profile.france_travail.keywords.map((value) =>
    value.trim()
  );
  profile.required_departments = (profile.required_departments ?? []).map((value) =>
    value.trim().toUpperCase()
  );
  profile.required_regions = normalizeTerms(profile.required_regions ?? []);
  for (const tier of ["excellent", "strong", "acceptable"]) {
    profile.practical_locations[tier] = normalizeTerms(
      profile.practical_locations[tier]
    );
  }
  return profile;
}

export function loadSearchProfile({ profilePath } = {}) {
  const configured = profilePath ?? process.env.JOB_SEARCH_PROFILE;
  const selectedPath = configured
    ? resolveProjectPath(configured)
    : existsSync(LOCAL_PROFILE_PATH)
      ? LOCAL_PROFILE_PATH
      : DEFAULT_PROFILE_PATH;
  if (!existsSync(selectedPath)) {
    throw new Error(`Perfil de busca não encontrado: ${selectedPath}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(selectedPath, "utf8"));
  } catch (error) {
    throw new Error(`Não foi possível ler o perfil ${selectedPath}: ${error.message}`);
  }
  return {
    path: selectedPath,
    profile: normalizeSearchTerms(validateSearchProfile(parsed, selectedPath))
  };
}

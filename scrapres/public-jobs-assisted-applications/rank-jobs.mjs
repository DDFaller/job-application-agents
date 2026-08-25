import { filterConfig, profileEvidence } from "./filter-config.mjs";

function normalize(value) {
  return String(value ?? "")
    .replace(/&[a-z]+;/gi, " ")
    .toLocaleLowerCase("fr-FR");
}

function normalizeLocation(value) {
  return normalize(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[-_]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function explicitDepartmentCode(value) {
  const match = String(value ?? "")
    .trim()
    .toUpperCase()
    .match(/(?:^|\b)(2[AB]|\d{2,3})(?:\b|$)/);
  return match?.[1] ?? "";
}

function departmentCodeFromLocation(value) {
  const text = String(value ?? "").toUpperCase();
  const postal = text.match(/\b((?:0[1-9]|[1-8]\d|9[0-8]))\d{3}\b/);
  if (postal) return postal[1];
  const prefixed = text.match(/(?:^|[\s,;(])(2[AB]|\d{2,3})\s*-\s*[A-ZÀ-ÖØ-Ý]/);
  return prefixed?.[1] ?? "";
}

export function locationDecision(
  { department = "", region = "", location = "" },
  { requiredDepartments = [], requiredRegions = [] } = {}
) {
  const departments = requiredDepartments.map((value) => String(value).toUpperCase());
  const regions = requiredRegions.map(normalizeLocation);
  const restricted = departments.length > 0 || regions.length > 0;
  if (!restricted) return { restricted: false, accepted: true, department: "" };

  const code = explicitDepartmentCode(department) || departmentCodeFromLocation(location);
  if (code && departments.length) {
    return { restricted: true, accepted: departments.includes(code), department: code };
  }

  const regionText = normalizeLocation(`${region} ${location}`);
  if (regions.some((value) => value && regionText.includes(value))) {
    return { restricted: true, accepted: true, department: code };
  }
  return { restricted: true, accepted: null, department: code };
}

function sourceLocation(source) {
  if (
    source.format === "schema.org/JobPosting" ||
    source.format === "France Travail API v2 JSON"
  ) {
    try {
      const parsed = JSON.parse(source.content);
      const jobLocation = parsed.jobLocation ?? parsed.location ?? "";
      const locationText = typeof jobLocation === "string"
        ? jobLocation
        : JSON.stringify(jobLocation);
      const address = Array.isArray(jobLocation)
        ? jobLocation[0]?.address
        : jobLocation?.address;
      return {
        department: parsed.department ?? "",
        region: parsed.region ?? address?.addressRegion ?? "",
        location: `${locationText} ${address?.postalCode ?? ""}`
      };
    } catch {
      return { department: "", region: "", location: "" };
    }
  }

  const locationLines = source.content
    .split("\n")
    .filter((line) =>
      /(?:lieu|localisation|département|departement|code postal|poste basé)/i.test(line)
    )
    .slice(0, 12)
    .join(" ");
  return { department: "", region: locationLines, location: locationLines };
}

function containsAny(text, terms) {
  return terms.some((term) => text.includes(term));
}

function unique(values) {
  return [...new Set(values)];
}

function sourceTitle(source) {
  if (
    source.format === "schema.org/JobPosting" ||
    source.format === "France Travail API v2 JSON"
  ) {
    try {
      return JSON.parse(source.content).title ?? "";
    } catch {
      return "";
    }
  }

  const lines = source.content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const offerIndex = lines.findIndex((line) => /^offre n[°ºo]/i.test(line));
  if (offerIndex > 0) return lines[offerIndex - 1];
  return lines.find((line) => !/^retour recherche$/i.test(line)) ?? "";
}

export function preFilterSource(
  source,
  {
    requiredDepartments = filterConfig.required_departments ?? [],
    requiredRegions = filterConfig.required_regions ?? []
  } = {}
) {
  const title = sourceTitle(source);
  const normalizedTitle = normalize(title);
  const normalizedContent = normalize(source.content.slice(0, 20000));
  const combined = `${normalizedTitle} ${normalizedContent}`;

  const location = locationDecision(sourceLocation(source), {
    requiredDepartments,
    requiredRegions
  });
  if (location.restricted && location.accepted === false) {
    return {
      accepted: false,
      score: 0,
      title,
      reasons: [],
      rejection_reason: "localização fora da região permitida"
    };
  }

  if (containsAny(combined, filterConfig.excluded_terms)) {
    return {
      accepted: false,
      score: 0,
      title,
      reasons: [],
      rejection_reason: "stage ou apprentissage"
    };
  }

  const matched = filterConfig.preliminary_title_rules.filter((rule) =>
    containsAny(normalizedTitle, rule.terms)
  );
  const hardSpecialistTitle = containsAny(
    normalizedTitle,
    filterConfig.blocked_title_terms
  );

  if (hardSpecialistTitle) {
    return {
      accepted: false,
      score: 0,
      title,
      reasons: [],
      rejection_reason: "intitulé especializado ou função de direção"
    };
  }

  if (filterConfig.preliminary_title_rules.length && matched.length === 0) {
    return {
      accepted: false,
      score: 0,
      title,
      reasons: [],
      rejection_reason: "intitulé fora dos alvos profissionais"
    };
  }

  let score = matched.length ? Math.max(...matched.map((rule) => rule.points)) : 0;
  const reasons = matched.map((rule) => {
    const term = rule.terms.find((value) => normalizedTitle.includes(value));
    return rule.reason ?? `intitulé: ${term}`;
  });
  const preliminaryScopes = { title: normalizedTitle, combined };
  for (const rule of filterConfig.preliminary_bonus_rules) {
    if (containsAny(preliminaryScopes[rule.source], rule.terms)) {
      score += rule.points;
      if (rule.reason) reasons.push(rule.reason);
    }
  }
  const accepted = score >= filterConfig.preliminary_threshold;
  return {
    accepted,
    score,
    title,
    reasons: unique(reasons),
    rejection_reason: accepted ? "" : "pontuação preliminar insuficiente"
  };
}

function combinedJobText(job) {
  return normalize(
    [
      job.title,
      job.summary,
      ...(job.responsibilities ?? []),
      ...(job.requirements ?? []),
      ...(job.preferred_qualifications ?? []),
      ...(job.skills ?? []),
      job.job_family,
      job.application_process
    ].join(" ")
  );
}

function parseDate(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return new Date(`${iso[1]}-${iso[2]}-${iso[3]}T12:00:00Z`);
  const french = text.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/);
  if (french) {
    return new Date(
      `${french[3]}-${french[2].padStart(2, "0")}-${french[1].padStart(2, "0")}T12:00:00Z`
    );
  }
  return null;
}

function isoDate(value) {
  const date = parseDate(value);
  return date ? date.toISOString().slice(0, 10) : String(value ?? "");
}

export function scoreJob(
  job,
  {
    today = new Date(),
    candidateExperienceYears = filterConfig.candidate_experience_years,
    requiredDepartments = filterConfig.required_departments ?? [],
    requiredRegions = filterConfig.required_regions ?? []
  } = {}
) {
  const title = normalize(job.title);
  const profileText = normalize(
    [...(job.requirements ?? []), ...(job.preferred_qualifications ?? [])].join(" ")
  );
  const allText = `${title} ${combinedJobText(job)}`;
  let direct = 0;
  const reasons = [];
  const evidence = [];

  const add = (points, reason, evidenceIds = []) => {
    direct += points;
    reasons.push(reason);
    evidence.push(...evidenceIds);
  };

  const directScopes = { title, all: allText, requirements: profileText };
  const exclusiveGroups = new Set();
  for (const rule of filterConfig.direct_match_rules) {
    if (rule.exclusive_group && exclusiveGroups.has(rule.exclusive_group)) continue;
    if (!containsAny(directScopes[rule.source], rule.terms)) continue;
    add(rule.points, rule.reason, profileEvidence[rule.evidence_key] ?? []);
    if (rule.exclusive_group) exclusiveGroups.add(rule.exclusive_group);
  }

  const isIt = containsAny(
    allText,
    filterConfig.sector_signals.technology_terms
  );
  direct = Math.min(direct, 50);

  // Ausência de metadados não significa inacessibilidade. O valor neutro evita
  // penalizar portais que não publicam categoria ou abertura a contratuais.
  let accessibility = 10;
  const gaps = [];
  const hardRejections = [];
  const locationEligibility = locationDecision(job, {
    requiredDepartments,
    requiredRegions
  });
  if (locationEligibility.restricted && locationEligibility.accepted === false) {
    hardRejections.push("localização fora da região permitida");
  } else if (locationEligibility.restricted && locationEligibility.accepted === null) {
    hardRejections.push("localização não confirmada na região permitida");
  }
  const category = normalize(job.category).toUpperCase();
  if (/\bC\b/.test(category)) accessibility += 8;
  else if (/\bB\b/.test(category)) accessibility += 5;
  else if (/\bA\b/.test(category)) accessibility += 1;
  if (normalize(job.open_to_contractors).startsWith("oui")) accessibility += 6;
  const experience = normalize(job.experience_level);
  if (experience.includes("débutant")) accessibility += 3;
  else if (experience.includes("confirmé")) accessibility += 1;
  else if (experience.includes("expert")) accessibility -= 3;
  const requiredYearsMatch = experience.match(/(\d+(?:[.,]\d+)?)\s*an(?:s|\(s\))?/);
  const requiredMonthsMatch = experience.match(/(\d+)\s*mois/);
  const requiredYears = requiredYearsMatch
    ? Number.parseFloat(requiredYearsMatch[1].replace(",", "."))
    : requiredMonthsMatch
      ? Number.parseInt(requiredMonthsMatch[1], 10) / 12
      : null;
  if (
    requiredYears !== null &&
    Number.isFinite(candidateExperienceYears)
  ) {
    if (requiredYears <= candidateExperienceYears) accessibility += 3;
    else gaps.push("experiência mínima a verificar");
  }
  for (const rule of filterConfig.gap_rules) {
    const pattern = new RegExp(rule.pattern, rule.flags ?? "i");
    if (pattern.test(directScopes[rule.source]) && !gaps.includes(rule.label)) {
      gaps.push(rule.label);
    }
  }
  if (
    /(?:titulaire|disposer|possession|posséder|permis)\s+(?:du\s+)?permis\s+b|permis\s+(?:de conduire\s+)?b?\s*(?:obligatoire|exigé|impératif)|véhicul[ée]/i.test(
      profileText
    )
  ) {
    gaps.push("permis B non documenté");
  }
  if (containsAny(allText, ["bac+3", "licence exigée", "master", "bac + 5", "bac+5"])) {
    gaps.push("niveau ou spécialité de diplôme à vérifier");
  }
  if (containsAny(title, ["responsable", "chef", "directeur", "directrice"]) && normalize(job.management) === "oui") {
    gaps.push("expérience de management non documentée");
  }
  if (isIt && containsAny(allText, ["expérience de 3 ans", "5 ans d'expérience", "expertise technique"])) {
    gaps.push("expérience informatique professionnelle non documentée");
  }
  accessibility -= Math.min(8, gaps.length * 2);
  accessibility = Math.max(0, Math.min(accessibility, 25));

  let career = 4;
  const employment = normalize(job.employment_type);
  if (employment.includes("emploi permanent")) career += 5;
  else if (/\bcdi\b/.test(employment)) career += 5;
  else if (/\bcdd\b/.test(employment)) career += 3;
  else if (employment.includes("intérim") || employment.includes("interim")) career += 1;
  else if (employment.includes("contrat de projet")) career += 3;
  else if (employment.includes("remplacement")) career += 2;
  if (isIt) career += filterConfig.sector_signals.technology_career_bonus;
  if (containsAny(allText, filterConfig.career_bonus_terms)) {
    career += 2;
  }
  career = Math.min(career, 15);

  const hasLocationPreferences = Object.values(
    filterConfig.practical_locations
  ).some((locations) => locations.length);
  let practical = hasLocationPreferences ? 4 : 5;
  const location = normalize(`${job.location} ${job.department} ${job.region}`);
  if (containsAny(location, filterConfig.practical_locations.excellent)) practical = 9;
  else if (containsAny(location, filterConfig.practical_locations.strong)) practical = 8;
  else if (containsAny(location, filterConfig.practical_locations.acceptable)) practical = 6;
  if (normalize(job.remote_work) === "oui") practical = Math.min(10, practical + 1);

  const deadline = parseDate(job.application_deadline);
  if (deadline) {
    const base = new Date(`${today.toISOString().slice(0, 10)}T12:00:00Z`);
    const daysLeft = Math.floor((deadline - base) / 86_400_000);
    if (daysLeft < 0) {
      gaps.push("offre expirée");
      practical = 0;
    } else if (daysLeft <= 2) {
      practical -= 4;
      gaps.push("échéance de candidature immédiate");
    } else if (daysLeft <= 7) {
      practical -= 2;
    }
  }
  practical = Math.max(0, practical);

  let score = Math.min(100, direct + accessibility + career + practical);
  if (gaps.length) score = Math.max(0, score - Math.min(8, gaps.length));
  const potential =
    score >= 88 ? "Très fort" : score >= 78 ? "Fort" : score >= 68 ? "Bon" : "Modéré";

  return {
    ...job,
    application_deadline: isoDate(job.application_deadline),
    match_score: score,
    potential,
    score_components: {
      direct_match_50: direct,
      accessibility_25: accessibility,
      career_potential_15: career,
      practical_fit_10: practical
    },
    match_reasons: unique(reasons).slice(0, 6),
    gaps: unique(gaps).slice(0, 4),
    hard_rejections: unique(hardRejections),
    profile_evidence_ids: unique(evidence),
    profile_version: filterConfig.profile_version,
    filter_version: filterConfig.version
  };
}

export function rankJobs(jobs, options = {}) {
  const scored = jobs.map((job) => scoreJob(job, options));
  scored.sort((left, right) => {
    if (right.match_score !== left.match_score) return right.match_score - left.match_score;
    return String(right.application_deadline).localeCompare(String(left.application_deadline));
  });

  const deduplicated = [];
  const seen = new Set();
  for (const job of scored) {
    const key = `${normalize(job.title)}|${normalize(job.employer)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduplicated.push(job);
  }

  const rejected = deduplicated.filter(
    (job) =>
      job.match_score < filterConfig.minimum_notion_score ||
      job.gaps.includes("offre expirée") ||
      job.hard_rejections.length > 0
  );
  const notionReady = deduplicated
    .filter(
      (job) =>
        job.match_score >= filterConfig.minimum_notion_score &&
        !job.gaps.includes("offre expirée") &&
        job.hard_rejections.length === 0
    )
    .slice(0, filterConfig.top_count)
    .map((job, index) => ({ ...job, rank: index + 1, review_status: "pending_user_review" }));

  return { all_scored: deduplicated, notion_ready: notionReady, rejected };
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function topJobsCsv(jobs) {
  const rows = [
    ["Rank", "Match Score", "Potential", "Position", "Employer", "Location", "Deadline", "URL"]
  ];
  for (const job of jobs) {
    rows.push([
      job.rank,
      job.match_score,
      job.potential,
      job.title,
      job.employer,
      job.location,
      job.application_deadline,
      job.source_url
    ]);
  }
  return `${rows.map((row) => row.map(csvCell).join(",")).join("\n")}\n`;
}

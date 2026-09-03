import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_PROFILE_PATH } from "../lib/search-profile.mjs";

process.env.JOB_SEARCH_PROFILE = DEFAULT_PROFILE_PATH;
const { preFilterSource, rankJobs, scoreJob, topJobsCsv } = await import("../rank-jobs.mjs");

const strongJob = {
  source_portal: "emploi-territorial",
  source_url: "https://www.emploi-territorial.fr/offre/o001-agent-administratif",
  reference: "O001",
  title: "Agent administratif (h/f)",
  employer: "Commune test",
  location: "Ville test",
  department: "Département test",
  region: "Île-de-France",
  category: "C",
  job_family: "Affaires administratives",
  employment_type: "Emploi permanent - vacance d'emploi",
  open_to_contractors: "Oui",
  grades: ["Adjoint administratif"],
  work_time: "Temps complet",
  management: "Non",
  experience_level: "Débutant accepté",
  remote_work: "Oui",
  start_date: "2026-10-01",
  publication_date: "2026-08-24",
  application_deadline: "2026-10-15",
  salary: "",
  summary: "Gestion administrative et accueil du public.",
  responsibilities: [
    "Accueil physique et téléphonique des usagers",
    "Gestion et suivi des dossiers administratifs",
    "Saisie et mise à jour d'une base de données",
    "Rédaction de courriers et classement des documents",
    "Mise à jour de tableaux de suivi Excel",
    "Organisation de réunions avec les services municipaux"
  ],
  requirements: ["Rigueur, discrétion et respect des procédures"],
  preferred_qualifications: [],
  skills: ["Travail en équipe"],
  languages: [],
  application_process: "Candidature en ligne",
  evidence: []
};

const strongFranceTravailJob = {
  ...strongJob,
  source_portal: "france-travail",
  source_url: "https://candidat.francetravail.fr/offres/recherche/detail/TEST123",
  reference: "TEST123",
  employer: "Employeur test",
  location: "Ville test",
  department: "Département test",
  region: "",
  category: "",
  employment_type: "CDD",
  open_to_contractors: "",
  grades: [],
  remote_work: "",
  experience_level: "6 mois"
};

test("pré-filtre une vaga administrativa e rejeita um estágio", () => {
  const accepted = preFilterSource({
    format: "schema.org/JobPosting",
    content: JSON.stringify({ title: "Agent administratif", Description: "Gestion de dossiers" })
  });
  const rejected = preFilterSource({
    format: "schema.org/JobPosting",
    content: JSON.stringify({ title: "Stage étudiant administratif" })
  });
  assert.equal(accepted.accepted, true);
  assert.equal(rejected.accepted, false);
});

test("pré-filtro rejeita localização conhecida fora dos departamentos permitidos", () => {
  const requiredDepartments = ["75", "77", "78", "91", "92", "93", "94", "95"];
  const outside = preFilterSource(
    {
      format: "France Travail API v2 JSON",
      content: JSON.stringify({
        title: "Agent administratif",
        description: "Gestion de dossiers",
        jobLocation: "57 - Yutz — 57970"
      })
    },
    { requiredDepartments, requiredRegions: ["île-de-france"] }
  );
  const inside = preFilterSource(
    {
      format: "France Travail API v2 JSON",
      content: JSON.stringify({
        title: "Agent administratif",
        description: "Gestion de dossiers",
        jobLocation: "93 - Noisy-le-Grand — 93160"
      })
    },
    { requiredDepartments, requiredRegions: ["île-de-france"] }
  );
  assert.equal(outside.accepted, false);
  assert.match(outside.rejection_reason, /localização/);
  assert.equal(inside.accepted, true);
});

test("pré-filtre rejeita título especializado mesmo com texto administrativo", () => {
  const result = preFilterSource({
    format: "texto HTML limpo",
    content:
      "Média-ludothécaire (h/f)\nOffre n° O001\nGestion de dossiers, accueil et emploi permanent catégorie C"
  });
  assert.equal(result.accepted, false);
  assert.match(result.rejection_reason, /intitulé/);
});

test("pontua uma correspondência administrativa forte com o preset público", () => {
  const scored = scoreJob(strongJob, { today: new Date("2026-08-24T12:00:00Z") });
  assert.ok(scored.match_score >= 83);
  assert.equal(scored.potential, "Très fort");
  assert.deepEqual(scored.profile_evidence_ids, []);
  assert.match(scored.profile_version, /^administrative-fr:/);
});

test("não promove automaticamente vaga France Travail sem sinais suficientes de acessibilidade", () => {
  const ranking = rankJobs([strongFranceTravailJob], {
    today: new Date("2026-08-24T12:00:00Z")
  });
  assert.ok(ranking.all_scored[0].match_score >= 60);
  assert.ok(ranking.all_scored[0].match_score < 78);
  assert.equal(ranking.all_scored[0].score_components.accessibility_25, 10);
  assert.equal(ranking.all_scored[0].score_components.practical_fit_10, 5);
  assert.equal(ranking.notion_ready.length, 0);
});

test("usa experiência comprovada para requisito numérico sem presumir equivalência de diploma", () => {
  const scored = scoreJob(strongFranceTravailJob, {
    today: new Date("2026-08-24T12:00:00Z"),
    candidateExperienceYears: 11
  });
  assert.equal(scored.score_components.accessibility_25, 13);
  assert.ok(!scored.gaps.includes("experiência mínima a verificar"));
});

test("ranking remove duplicatas e produz o CSV anterior", () => {
  const duplicate = { ...strongJob, source_url: `${strongJob.source_url}-duplicada` };
  const ranking = rankJobs([strongJob, duplicate], {
    today: new Date("2026-08-24T12:00:00Z")
  });
  assert.equal(ranking.notion_ready.length, 1);
  const csv = topJobsCsv(ranking.notion_ready);
  assert.match(csv, /^Rank,Match Score,Potential,Position,Employer,Location,Deadline,URL/m);
  assert.match(csv, /Très fort/);
});

test("ranking final mantém somente vagas confirmadas em Île-de-France", () => {
  const filters = {
    today: new Date("2026-08-24T12:00:00Z"),
    requiredDepartments: ["75", "77", "78", "91", "92", "93", "94", "95"],
    requiredRegions: ["île-de-france"]
  };
  const idf = {
    ...strongJob,
    reference: "IDF001",
    source_url: `${strongJob.source_url}-idf`,
    location: "Noisy-le-Grand — 93160",
    department: "93",
    region: "Île-de-France"
  };
  const yutz = {
    ...strongJob,
    reference: "YUTZ001",
    source_url: `${strongJob.source_url}-yutz`,
    employer: "Commune hors région",
    location: "Yutz — 57970",
    department: "57",
    region: "Grand Est"
  };
  const ranking = rankJobs([idf, yutz], filters);
  assert.deepEqual(ranking.notion_ready.map((job) => job.reference), ["IDF001"]);
  assert.deepEqual(ranking.rejected[0].hard_rejections, [
    "localização fora da região permitida"
  ]);
});

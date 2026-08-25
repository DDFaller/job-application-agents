import { franceTravailApiRequest } from "./lib/france-travail-client.mjs";
import { loadSearchProfile } from "./lib/search-profile.mjs";
import { isMainModule, parseArgs, positiveInteger } from "./lib/utils.mjs";

export const FRANCE_TRAVAIL_RESULTS_PER_PAGE = 20;

export function franceTravailPublicUrl(reference) {
  return `https://candidat.francetravail.fr/offres/recherche/detail/${encodeURIComponent(reference)}`;
}

function compact(values) {
  return values.filter((value) => value !== undefined && value !== null && value !== "");
}

export function normalizeFranceTravailOffer(offer) {
  if (!offer || typeof offer !== "object" || !String(offer.id ?? "").trim()) {
    throw new Error("Oferta France Travail sem identificador válido.");
  }
  const reference = String(offer.id).trim();
  const place = offer.lieuTravail ?? {};
  const company = offer.entreprise ?? {};
  const salary = offer.salaire ?? {};
  const origin = offer.origineOffre ?? {};
  const skills = (offer.competences ?? []).map((item) =>
    compact([item.libelle, item.exigence]).join(" — ")
  );
  const qualities = (offer.qualitesProfessionnelles ?? []).map((item) =>
    compact([item.libelle, item.description]).join(" — ")
  );
  const training = (offer.formations ?? []).map((item) =>
    compact([item.niveauLibelle, item.domaineLibelle, item.exigence]).join(" — ")
  );
  const permits = (offer.permis ?? []).map((item) =>
    compact([item.libelle, item.exigence]).join(" — ")
  );

  const content = {
    title: offer.intitule ?? "",
    description: offer.description ?? "",
    identifier: reference,
    hiringOrganization: company.nom ?? "",
    jobLocation: compact([place.libelle, place.codePostal]).join(" — "),
    employmentType: compact([
      offer.typeContratLibelle ?? offer.typeContrat,
      offer.natureContrat,
      offer.dureeTravailLibelleConverti ?? offer.dureeTravailLibelle
    ]).join(" — "),
    experienceRequirements: compact([
      offer.experienceLibelle,
      offer.experienceCommentaire
    ]).join(" — "),
    datePosted: offer.dateCreation ?? "",
    dateModified: offer.dateActualisation ?? "",
    salary: compact([
      salary.libelle,
      salary.commentaire,
      salary.complement1,
      salary.complement2
    ]).join(" — "),
    skills,
    professionalQualities: qualities,
    training,
    permits,
    numberOfPositions: offer.nombrePostes ?? "",
    accessibleToDisabledWorkers: offer.accessibleTH ?? "",
    remoteWork: offer.teletravail ?? "",
    applicationUrl: origin.urlOrigine ?? "",
    offerOrigin: origin.origine ?? "France Travail"
  };

  return {
    source_portal: "france-travail",
    source_url: franceTravailPublicUrl(reference),
    reference,
    prepared_source: {
      portal: "france-travail",
      url: franceTravailPublicUrl(reference),
      reference,
      format: "France Travail API v2 JSON",
      content: JSON.stringify(content)
    }
  };
}

export async function searchFranceTravailOffers({
  keywords,
  page = 1,
  departments = [],
  fetchImpl = fetch,
  env = process.env
}) {
  const start = (page - 1) * FRANCE_TRAVAIL_RESULTS_PER_PAGE;
  const end = start + FRANCE_TRAVAIL_RESULTS_PER_PAGE - 1;
  const payload = await franceTravailApiRequest("offres/search", {
    query: {
      motsCles: keywords,
      departement: departments.length ? departments.join(",") : undefined,
      range: `${start}-${end}`
    },
    fetchImpl,
    env
  });
  return Array.isArray(payload.resultats) ? payload.resultats : [];
}

export async function fetchFranceTravailOffer(
  reference,
  { fetchImpl = fetch, env = process.env } = {}
) {
  const offer = await franceTravailApiRequest(
    `offres/${encodeURIComponent(reference)}`,
    { fetchImpl, env }
  );
  return normalizeFranceTravailOffer(offer);
}

export async function discoverFranceTravail({
  pages = 1,
  profile,
  fetchImpl = fetch,
  env = process.env
} = {}) {
  const activeProfile = profile ?? loadSearchProfile().profile;
  const settings = activeProfile.france_travail;
  const jobs = new Map();

  for (const keywords of settings.keywords) {
    for (let page = 1; page <= pages; page += 1) {
      const offers = await searchFranceTravailOffers({
        keywords,
        page,
        departments: settings.departments,
        fetchImpl,
        env
      });
      for (const offer of offers) {
        const job = normalizeFranceTravailOffer(offer);
        jobs.set(job.source_url, job);
      }
      if (offers.length < FRANCE_TRAVAIL_RESULTS_PER_PAGE) break;
    }
  }
  return [...jobs.values()];
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const pages = positiveInteger(args.pages, 1, { max: 20 });
  const jobs = await discoverFranceTravail({ pages });
  const printable = jobs.map(({ prepared_source, ...job }) => job);
  process.stdout.write(`${JSON.stringify(printable, null, 2)}\n`);
}

if (isMainModule(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

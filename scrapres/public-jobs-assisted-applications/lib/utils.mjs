import path from "node:path";
import { pathToFileURL } from "node:url";

const ALLOWED_HOSTS = new Set([
  "choisirleservicepublic.gouv.fr",
  "www.choisirleservicepublic.gouv.fr",
  "emploi-territorial.fr",
  "www.emploi-territorial.fr",
  "candidat.francetravail.fr"
]);

export const SOURCE_PORTALS = [
  "choisir-service-public",
  "emploi-territorial",
  "france-travail"
];

export function normalizeJobUrl(value) {
  const url = new URL(value);
  url.hash = "";

  for (const key of [...url.searchParams.keys()]) {
    if (key.startsWith("utm_") || ["fbclid", "gclid"].includes(key)) {
      url.searchParams.delete(key);
    }
  }

  return url.toString();
}

export function identifyPortal(value) {
  const url = new URL(value);
  const host = url.hostname.toLowerCase();

  if (!ALLOWED_HOSTS.has(host)) {
    throw new Error(`Portal não autorizado: ${host}`);
  }

  if (
    host.includes("choisirleservicepublic") &&
    url.pathname.startsWith("/offre-emploi/")
  ) {
    return "choisir-service-public";
  }

  if (
    host.includes("emploi-territorial") &&
    url.pathname.startsWith("/offre/")
  ) {
    return "emploi-territorial";
  }

  if (
    host === "candidat.francetravail.fr" &&
    url.pathname.startsWith("/offres/recherche/detail/")
  ) {
    return "france-travail";
  }

  throw new Error("A URL não corresponde a uma página individual de vaga autorizada.");
}

export function parseArgs(argv) {
  const result = { _: [] };

  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) {
      result._.push(item);
      continue;
    }

    const [rawKey, inlineValue] = item.slice(2).split("=", 2);
    if (inlineValue !== undefined) {
      result[rawKey] = inlineValue;
      continue;
    }

    const next = argv[index + 1];
    if (next !== undefined && !next.startsWith("--")) {
      result[rawKey] = next;
      index += 1;
    } else {
      result[rawKey] = true;
    }
  }

  return result;
}

export function positiveInteger(value, fallback, { max = 200 } = {}) {
  if (value === undefined) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > max) {
    throw new Error(`Valor inteiro inválido: ${value}. Esperado: 1 a ${max}.`);
  }
  return parsed;
}

export function slugify(value) {
  const slug = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
  return slug || "vaga";
}

export function isMainModule(importMetaUrl) {
  if (!process.argv[1]) return false;
  return importMetaUrl === pathToFileURL(path.resolve(process.argv[1])).href;
}

export function cleanText(value) {
  return value
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function referenceFromUrl(value) {
  const url = new URL(value);
  const decoded = decodeURIComponent(url.pathname);
  const csp = decoded.match(/reference-([^/]+)\/?$/i);
  if (csp) return csp[1];
  const territorial = decoded.match(/\/offre\/(o[0-9a-z]+)-/i);
  if (territorial) return territorial[1].toUpperCase();
  const franceTravail = decoded.match(/\/offres\/recherche\/detail\/([^/]+)\/?$/i);
  if (franceTravail) return franceTravail[1];
  return "";
}

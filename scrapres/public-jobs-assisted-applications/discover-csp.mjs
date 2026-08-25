import * as cheerio from "cheerio";
import { politeDelay, requestText } from "./lib/http.mjs";
import {
  isMainModule,
  normalizeJobUrl,
  parseArgs,
  positiveInteger,
  referenceFromUrl
} from "./lib/utils.mjs";

export const DEFAULT_CSP_SEARCH_URL =
  "https://choisirleservicepublic.gouv.fr/nos-offres/";

export function parseCspListing(html, baseUrl = DEFAULT_CSP_SEARCH_URL) {
  const $ = cheerio.load(html);
  const jobs = new Map();

  $('a[href*="/offre-emploi/"]').each((_, element) => {
    const href = $(element).attr("href");
    if (!href) return;
    const url = normalizeJobUrl(new URL(href, baseUrl).toString());
    if (!new URL(url).pathname.startsWith("/offre-emploi/")) return;
    jobs.set(url, {
      source_portal: "choisir-service-public",
      source_url: url,
      reference: referenceFromUrl(url)
    });
  });

  return [...jobs.values()];
}

export function cspPageUrl(searchUrl, page) {
  if (page === 1) return searchUrl;
  const url = new URL(searchUrl);
  const withoutPage = url.pathname
    .replace(/\/page\/\d+\/?$/i, "/")
    .replace(/\/+$/, "");
  url.pathname = `${withoutPage}/page/${page}/`;
  return url.toString();
}

export async function discoverCsp({ searchUrl = DEFAULT_CSP_SEARCH_URL, pages = 1 } = {}) {
  const jobs = new Map();

  for (let page = 1; page <= pages; page += 1) {
    if (page > 1) await politeDelay();
    const pageUrl = cspPageUrl(searchUrl, page);
    const { text } = await requestText(pageUrl);
    const current = parseCspListing(text, pageUrl);
    for (const job of current) jobs.set(job.source_url, job);
    if (current.length === 0) break;
  }

  return [...jobs.values()];
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const pages = positiveInteger(args.pages, 1, { max: 20 });
  const jobs = await discoverCsp({
    searchUrl: args.url ?? DEFAULT_CSP_SEARCH_URL,
    pages
  });
  process.stdout.write(`${JSON.stringify(jobs, null, 2)}\n`);
}

if (isMainModule(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

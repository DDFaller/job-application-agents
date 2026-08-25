import * as cheerio from "cheerio";
import { cookiesFromHeaders, politeDelay, requestText } from "./lib/http.mjs";
import {
  isMainModule,
  normalizeJobUrl,
  parseArgs,
  positiveInteger,
  referenceFromUrl
} from "./lib/utils.mjs";

export const DEFAULT_TERRITORIAL_SEARCH_URL =
  "https://www.emploi-territorial.fr/emploi-mobilite/";

export function parseTerritorialListing(
  html,
  baseUrl = DEFAULT_TERRITORIAL_SEARCH_URL
) {
  const $ = cheerio.load(html);
  const jobs = new Map();

  $('a[href^="/offre/"], a[href*="emploi-territorial.fr/offre/"]').each(
    (_, element) => {
      const href = $(element).attr("href");
      if (!href) return;
      const url = normalizeJobUrl(new URL(href, baseUrl).toString());
      if (!new URL(url).pathname.startsWith("/offre/")) return;
      jobs.set(url, {
        source_portal: "emploi-territorial",
        source_url: url,
        reference: referenceFromUrl(url)
      });
    }
  );

  return [...jobs.values()];
}

export async function discoverTerritorial({
  searchUrl = DEFAULT_TERRITORIAL_SEARCH_URL,
  pages = 1
} = {}) {
  const initial = await requestText(searchUrl);
  const jobs = new Map(
    parseTerritorialListing(initial.text, searchUrl).map((job) => [job.source_url, job])
  );
  const cookie = cookiesFromHeaders(initial.headers);

  for (let page = 2; page <= pages; page += 1) {
    await politeDelay();
    const headers = { "Content-Type": "application/x-www-form-urlencoded" };
    if (cookie) headers.Cookie = cookie;

    const { text } = await requestText(
      "https://www.emploi-territorial.fr/recherche_emploi_mobilite/",
      {
        method: "POST",
        headers,
        body: new URLSearchParams({ page: String(page), ajax: "1" }).toString()
      }
    );
    const current = parseTerritorialListing(text, searchUrl);
    for (const job of current) jobs.set(job.source_url, job);
    if (current.length === 0) break;
  }

  return [...jobs.values()];
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const pages = positiveInteger(args.pages, 1, { max: 20 });
  const jobs = await discoverTerritorial({
    searchUrl: args.url ?? DEFAULT_TERRITORIAL_SEARCH_URL,
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

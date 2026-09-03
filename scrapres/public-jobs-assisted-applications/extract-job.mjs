import { GoogleGenAI } from "@google/genai";
import * as cheerio from "cheerio";
import { jobSchema, assertJobShape } from "./job-schema.mjs";
import { fetchFranceTravailOffer } from "./discover-france-travail.mjs";
import {
  callGeminiWithModelFallback,
  callGeminiWithRetry
} from "./lib/gemini-rate-limit.mjs";
import { requestText } from "./lib/http.mjs";
import {
  cleanText,
  identifyPortal,
  isMainModule,
  normalizeJobUrl,
  parseArgs,
  referenceFromUrl
} from "./lib/utils.mjs";

function findJobPosting(value) {
  if (!value || typeof value !== "object") return null;
  if (value["@type"] === "JobPosting") return value;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findJobPosting(item);
      if (found) return found;
    }
  }
  for (const item of Object.values(value)) {
    const found = findJobPosting(item);
    if (found) return found;
  }
  return null;
}

export function extractCspJsonLd(html) {
  const $ = cheerio.load(html);
  let result = null;
  $('script[type="application/ld+json"]').each((_, element) => {
    if (result) return;
    try {
      result = findJobPosting(JSON.parse($(element).text()));
    } catch {
      // Ignora blocos JSON-LD inválidos e continua procurando.
    }
  });
  return result;
}

export function extractVisibleJobText(html) {
  const $ = cheerio.load(html);
  $(
    "script, style, noscript, svg, nav, header, footer, form, button, dialog, aside"
  ).remove();
  const main = $("main#MainContent, main#main-content, main, article").first();
  return cleanText((main.length ? main : $("body")).text());
}

export async function prepareJobSource(url) {
  const normalizedUrl = normalizeJobUrl(url);
  const portal = identifyPortal(normalizedUrl);

  if (portal === "france-travail") {
    const job = await fetchFranceTravailOffer(referenceFromUrl(normalizedUrl));
    return job.prepared_source;
  }

  const { text: html } = await requestText(normalizedUrl);

  if (portal === "choisir-service-public") {
    const jobPosting = extractCspJsonLd(html);
    if (jobPosting) {
      return {
        portal,
        url: normalizedUrl,
        reference: referenceFromUrl(normalizedUrl),
        format: "schema.org/JobPosting",
        content: JSON.stringify(jobPosting)
      };
    }
  }

  const maxChars = Number.parseInt(process.env.MAX_JOB_TEXT_CHARS ?? "60000", 10);
  const visibleText = extractVisibleJobText(html);
  if (!visibleText) throw new Error("Nenhum conteúdo útil foi encontrado na vaga.");

  return {
    portal,
    url: normalizedUrl,
    reference: referenceFromUrl(normalizedUrl),
    format: "texto HTML limpo",
    content: visibleText.slice(0, maxChars)
  };
}

function extractionPrompt(source) {
  return `
Extraia e normalize uma única vaga de emprego na França.

Fonte autorizada: ${source.url}
Portal: ${source.portal}
Referência observada na URL: ${source.reference || "não identificada"}
Formato fornecido: ${source.format}

Regras obrigatórias:
- Use exclusivamente o conteúdo fornecido abaixo.
- Não invente nem complete informações por conhecimento externo.
- Use string vazia ou lista vazia quando a informação não estiver presente.
- Preserve datas, remuneração, localização, categoria, grades e referência.
- Separe requisitos obrigatórios de qualificações apenas desejáveis.
- Não trate descrição do empregador como responsabilidade do cargo.
- Mantenha os trechos de evidence curtos e literalmente sustentados pela fonte.
- Produza todos os campos solicitados pelo schema.

CONTEÚDO DA VAGA
${source.content}
`;
}

export async function generateStructuredJobResponse(
  client,
  source,
  { model = process.env.GEMINI_MODEL ?? "gemini-3.7-flash", onRetry } = {}
) {
  const config = {
    temperature: 0,
    responseMimeType: "application/json",
    responseJsonSchema: jobSchema
  };
  return callGeminiWithRetry(
    () =>
      client.models.generateContent({
        model,
        contents: extractionPrompt(source),
        config
      }),
    { onRetry }
  );
}

export async function extractJob(url, { localOnly = false, onRetry } = {}) {
  const source = await prepareJobSource(url);

  return extractJobFromSource(source, { localOnly, onRetry });
}

export async function extractJobFromSource(
  source,
  { localOnly = false, onRetry, onModelFallback } = {}
) {

  if (localOnly) {
    return {
      source_portal: source.portal,
      source_url: source.url,
      reference: source.reference,
      source_format: source.format,
      source_content: source.content
    };
  }

  if (!process.env.GEMINI_API_KEY) {
    throw new Error("GEMINI_API_KEY não está configurada.");
  }

  const client = new GoogleGenAI({
    apiKey: process.env.GEMINI_API_KEY,
    httpOptions: {
      // O pipeline controla o 429 usando o prazo retornado pela API.
      retryOptions: { attempts: 1 }
    }
  });
  const primaryModel = process.env.GEMINI_MODEL ?? "gemini-3.7-flash";
  const fallbackModels = (
    process.env.GEMINI_FALLBACK_MODELS ??
    "gemini-3.1-flash-lite,gemini-2.5-flash-lite"
  )
    .split(",")
    .map((model) => model.trim())
    .filter(Boolean);
  const models = [...new Set([primaryModel, ...fallbackModels])];
  const { result: response, model: usedModel } = await callGeminiWithModelFallback(
    (model) => generateStructuredJobResponse(client, source, { model, onRetry }),
    models,
    { onFallback: onModelFallback }
  );

  if (!response.text) {
    throw new Error("Gemini não retornou conteúdo estruturado para a vaga.");
  }
  const job = JSON.parse(response.text);
  assertJobShape(job);

  // Campos de proveniência são impostos pelo programa, não pelo modelo.
  job.source_portal = source.portal;
  job.source_url = source.url;
  if (!job.reference) job.reference = source.reference;
  job.extracted_at = new Date().toISOString();
  job.gemini_model = usedModel;
  job.gemini_api = "generateContent";
  return job;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const url = args._[0];
  if (!url) {
    throw new Error("Uso: node extract-job.mjs URL [--local-only] [--summary]");
  }
  const job = await extractJob(url, { localOnly: Boolean(args["local-only"]) });
  const output = args.summary
    ? {
        reference: job.reference,
        title: job.title,
        source_url: job.source_url,
        gemini_model: job.gemini_model,
        gemini_api: job.gemini_api
      }
    : job;
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
}

if (isMainModule(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

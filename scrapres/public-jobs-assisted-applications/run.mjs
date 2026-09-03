import { discoverCsp } from "./discover-csp.mjs";
import { discoverTerritorial } from "./discover-emploi-territorial.mjs";
import { discoverFranceTravail } from "./discover-france-travail.mjs";
import { extractJobFromSource, prepareJobSource } from "./extract-job.mjs";
import { filterConfig } from "./filter-config.mjs";
import { hasFranceTravailCredentials } from "./lib/france-travail-client.mjs";
import { selectCandidatesAcrossSources } from "./lib/candidate-selection.mjs";
import { preFilterSource, rankJobs, topJobsCsv } from "./rank-jobs.mjs";
import {
  geminiRequestDelay,
  isGeminiRateLimitError,
  isGeminiTransientError
} from "./lib/gemini-rate-limit.mjs";
import { politeDelay } from "./lib/http.mjs";
import {
  loadSeenJobs,
  loadExtractedJobs,
  saveDiscoveredJobs,
  saveExtractedJob,
  savePreFilterReport,
  saveRankingArtifacts,
  saveSeenJobs
} from "./lib/storage.mjs";
import { parseArgs, positiveInteger } from "./lib/utils.mjs";

function rankingSummary(ranking, label) {
  const base = `${ranking.notion_ready.length} vagas ${label}`;
  if (ranking.notion_ready.length || !ranking.all_scored.length) return base;
  const best = ranking.all_scored.find(
    (job) =>
      !(job.hard_rejections ?? []).length &&
      !(job.gaps ?? []).includes("offre expirée")
  );
  if (!best) {
    return `${base} (corte: ${filterConfig.minimum_notion_score}; nenhuma vaga atende aos filtros obrigatórios)`;
  }
  return (
    `${base} (corte: ${filterConfig.minimum_notion_score}; ` +
    `melhor score elegível: ${best.match_score}, ${best.reference || best.title})`
  );
}

async function discover(source, pages) {
  if (source === "csp") return discoverCsp({ pages });
  if (source === "territorial") return discoverTerritorial({ pages });
  if (source === "france-travail") return discoverFranceTravail({ pages });
  if (source !== "all") {
    throw new Error("--source deve ser all, csp, territorial ou france-travail.");
  }

  const sources = [
    { name: "Choisir le service public", promise: discoverCsp({ pages }) },
    { name: "Emploi Territorial", promise: discoverTerritorial({ pages }) }
  ];
  if (hasFranceTravailCredentials()) {
    sources.push({
      name: "France Travail",
      promise: discoverFranceTravail({ pages })
    });
  } else {
    console.error(
      "France Travail ignorado: configure FRANCE_TRAVAIL_CLIENT_ID e " +
        "FRANCE_TRAVAIL_CLIENT_SECRET no .env para incluí-lo em --source all."
    );
  }
  const settled = await Promise.allSettled(sources.map((source) => source.promise));
  const results = [];
  for (const [index, result] of settled.entries()) {
    if (result.status === "fulfilled") {
      results.push(...result.value);
    } else {
      console.error(`Fonte ${sources[index].name} indisponível: ${result.reason.message}`);
    }
  }
  if (!results.length && settled.some((result) => result.status === "rejected")) {
    throw new Error("Nenhuma fonte pôde ser consultada nesta execução.");
  }
  return results;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const source = args.source ?? "all";
  const pages = positiveInteger(args.pages, 1, { max: 20 });
  const limit = positiveInteger(args.limit, 10, { max: 100 });

  if (args["rank-only"]) {
    const extracted = await loadExtractedJobs();
    const ranking = rankJobs(extracted);
    const csvPath = await saveRankingArtifacts(ranking, topJobsCsv(ranking.notion_ready));
    console.error(`${rankingSummary(ranking, "no Top 20")}: ${csvPath}`);
    return;
  }

  const discovered = await discover(source, pages);
  const unique = [...new Map(discovered.map((job) => [job.source_url, job])).values()];
  await saveDiscoveredJobs(
    unique.map(({ prepared_source, ...candidate }) => candidate)
  );
  const countBySource = unique.reduce((counts, job) => {
    counts[job.source_portal] = (counts[job.source_portal] ?? 0) + 1;
    return counts;
  }, {});
  const sourceSummary = Object.entries(countBySource)
    .map(([portal, count]) => `${portal}: ${count}`)
    .join(", ");
  console.error(
    `${unique.length} vagas descobertas nas fontes selecionadas` +
      (sourceSummary ? ` (${sourceSummary}).` : ".")
  );

  const seen = await loadSeenJobs();
  const pending = unique.filter((job) => !seen.jobs[job.source_url]);
  console.error(`${pending.length} vagas novas encontradas antes do pré-filtro.`);

  if (args["discover-only"]) return;
  const prepared = [];
  const preRejected = [];
  for (let index = 0; index < pending.length; index += 1) {
    const candidate = pending[index];
    if (index > 0) await politeDelay();
    try {
      const sourceData =
        candidate.prepared_source ?? await prepareJobSource(candidate.source_url);
      const decision = preFilterSource(sourceData);
      if (decision.accepted) prepared.push({ candidate, sourceData, decision });
      else preRejected.push({ ...candidate, ...decision });
    } catch (error) {
      preRejected.push({ ...candidate, rejection_reason: error.message });
    }
  }
  prepared.sort((left, right) => right.decision.score - left.decision.score);
  const selected = selectCandidatesAcrossSources(prepared, limit);
  await savePreFilterReport({
    accepted: prepared.map(({ candidate, decision }) => ({ ...candidate, ...decision })),
    rejected: preRejected
  });
  console.error(
    `${prepared.length} passaram pelo pré-filtro; ${preRejected.length} foram rejeitadas localmente.`
  );

  if (args["prefilter-only"]) {
    console.error("Pré-filtro concluído sem chamar o Gemini.");
    return;
  }
  const selectedBySource = selected.reduce((counts, item) => {
    const portal = item.candidate.source_portal;
    counts[portal] = (counts[portal] ?? 0) + 1;
    return counts;
  }, {});
  const selectedSummary = Object.entries(selectedBySource)
    .map(([portal, count]) => `${portal}: ${count}`)
    .join(", ");
  console.error(
    `${selected.length} vagas seguirão para o Gemini (limite desta execução: ${limit}` +
      (selectedSummary ? `; ${selectedSummary}` : "") +
      ")."
  );
  if (!process.env.GEMINI_API_KEY) {
    throw new Error(
      "GEMINI_API_KEY não configurada. Use --discover-only, --prefilter-only ou exporte a chave."
    );
  }

  for (let index = 0; index < selected.length; index += 1) {
    const { candidate, sourceData, decision } = selected[index];
    if (index > 0) {
      const delaySeconds = Number.parseInt(
        process.env.GEMINI_REQUEST_DELAY_MS ?? "5000",
        10
      ) / 1000;
      console.error(`Aguardando ${delaySeconds}s para respeitar a cota do Gemini...`);
      await geminiRequestDelay();
    }
    try {
      const job = await extractJobFromSource(sourceData, {
        onRetry: ({ delayMs, nextAttempt, error }) => {
          const reason = isGeminiRateLimitError(error)
            ? "limite temporário"
            : "indisponibilidade temporária";
          console.error(
            `Gemini teve ${reason}; nova tentativa ${nextAttempt} em ${(
              delayMs / 1000
            ).toFixed(1)}s.`
          );
        },
        onModelFallback: ({ model, nextModel, reason }) => {
          const explanation = reason === "daily_quota"
            ? "cota diária esgotada"
            : reason === "rate_limit"
              ? "limite de requisições persistente"
              : "modelo indisponível";
          console.error(
            `Gemini ${model}: ${explanation}; continuando com ${nextModel}.`
          );
        }
      });
      job.preliminary_filter = decision;
      const filePath = await saveExtractedJob(job);
      seen.jobs[candidate.source_url] = {
        reference: job.reference,
        title: job.title,
        extracted_at: job.extracted_at,
        output_file: filePath
      };
      await saveSeenJobs(seen);
      console.error(`OK: ${job.reference || job.title} -> ${filePath}`);
    } catch (error) {
      console.error(`ERRO: ${candidate.source_url}: ${error.message}`);
      if (isGeminiRateLimitError(error)) {
        const hasRetryTime = /retry in\s+[0-9.]+s/i.test(error.message);
        console.error(
          hasRetryTime
            ? "O limite continuou após as tentativas automáticas. Execução interrompida; rode o mesmo comando mais tarde para retomar."
            : "A cota não informou quando será renovada. Execução interrompida; rode o mesmo comando mais tarde para retomar."
        );
        break;
      } else if (isGeminiTransientError(error)) {
        console.error(
          "A indisponibilidade continuou após as tentativas e modelos alternativos; " +
            "a vaga permanecerá pendente para a próxima execução."
        );
      }
    }
  }

  const extracted = await loadExtractedJobs();
  const ranking = rankJobs(extracted);
  const csvPath = await saveRankingArtifacts(ranking, topJobsCsv(ranking.notion_ready));
  console.error(`${rankingSummary(ranking, "aguardam revisão antes do Notion")}: ${csvPath}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});

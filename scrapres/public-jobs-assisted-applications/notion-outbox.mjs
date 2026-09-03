import path from "node:path";
import { readFile } from "node:fs/promises";
import "./lib/env.mjs";
import { isMainModule, parseArgs, slugify } from "./lib/utils.mjs";
import { PROJECT_ROOT, writeJsonAtomic } from "./lib/storage.mjs";

const READY_FILE = path.join(PROJECT_ROOT, "data", "notion-ready.json");
const STATE_FILE = path.join(PROJECT_ROOT, "data", "notion-delivery-state.json");
const OUTBOX_FILE = path.join(PROJECT_ROOT, "data", "notion-outbox.json");
const TARGET_DATABASE_TITLE =
  process.env.NOTION_DATABASE_TITLE ?? "Job Applications";

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw error;
  }
}

function isoDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value ?? "")) ? value : "";
}

function workModel(job) {
  const remote = String(job.remote_work ?? "").toLocaleLowerCase("fr-FR");
  if (/100\s*%|télétravail complet|full remote/.test(remote)) return "Remote";
  if (/oui|hybride|télétravail/.test(remote)) return "Hybrid";
  if (/non|sur site|présentiel/.test(remote)) return "On-site";
  return "Unspecified";
}

function sourceOption(job) {
  return "Other ATS";
}

function markdownList(values) {
  if (!values?.length) return "- Non renseigné";
  return values.map((value) => `- ${value}`).join("\n");
}

export function notionItemFromJob(job, generatedAt) {
  const reference = job.reference || job.source_url;
  const outputFile = path.join(
    PROJECT_ROOT,
    "output",
    job.source_portal,
    `${slugify(reference || job.title)}.json`
  );
  const matchSummary = `${job.match_score}/100 (${job.potential}) — ${(
    job.match_reasons ?? []
  ).join("; ")}`.slice(0, 1900);
  const deadline = isoDate(job.application_deadline);
  const properties = {
    Application: `${job.employer} — ${job.title}`.slice(0, 200),
    Status: "TO_APPLY",
    Company: job.employer,
    Role: job.title,
    Location: job.location,
    "Work Model": workModel(job),
    Source: sourceOption(job),
    "Job URL": job.source_url,
    "Source Job ID": reference,
    "Current Version": `${job.profile_version}/${job.filter_version}`,
    "date:Generated At:start": generatedAt,
    "date:Generated At:is_datetime": 1,
    "Local Bundle Path": outputFile,
    "Match Summary": matchSummary,
    Notes: `Vaga pública classificada pelo projeto public-jobs. Rank ${job.rank}; revisão humana exigida.`
  };
  if (deadline) {
    properties["date:Next Action At:start"] = deadline;
    properties["date:Next Action At:is_datetime"] = 0;
  }

  return {
    id: reference,
    source_url: job.source_url,
    reference,
    title: job.title,
    employer: job.employer,
    match_score: job.match_score,
    potential: job.potential,
    properties,
    content_markdown: `# Job Summary

${job.summary || "Non renseigné"}

- Source: [${job.source_portal}](${job.source_url})
- Score: ${job.match_score}/100 (${job.potential})
- Échéance: ${job.application_deadline || "Non renseignée"}

# Requirements

${markdownList(job.requirements)}

# Match Analysis

${markdownList(job.match_reasons)}

# Gaps

${markdownList(job.gaps)}

# Current Documents

- Données structurées locales: ${outputFile}
`,
    job_snapshot: job
  };
}

async function refreshOutbox() {
  const ready = await readJson(READY_FILE, { jobs: [] });
  const state = await readJson(STATE_FILE, { version: 1, jobs: {} });
  const generatedAt = new Date().toISOString();
  const items = (ready.jobs ?? []).map((job) => {
    const item = notionItemFromJob(job, generatedAt);
    const delivery = state.jobs[item.reference] ?? {};
    return {
      ...item,
      approved: Boolean(delivery.approved),
      approved_at: delivery.approved_at ?? null,
      delivery_status: delivery.delivery_status ?? "pending_user_review",
      notion_page_url: delivery.notion_page_url ?? null,
      sent_at: delivery.sent_at ?? null
    };
  });
  const outbox = {
    version: 1,
    generated_at: generatedAt,
    target_database_title: TARGET_DATABASE_TITLE,
    requires_explicit_user_approval: true,
    direct_notion_token_forbidden: true,
    count: items.length,
    approved_count: items.filter((item) => item.approved).length,
    pending_delivery_count: items.filter(
      (item) => item.approved && item.delivery_status !== "sent"
    ).length,
    items
  };
  await writeJsonAtomic(OUTBOX_FILE, outbox);
  return { outbox, state };
}

function findItem(outbox, reference) {
  const normalized = String(reference ?? "").toLocaleLowerCase("fr-FR");
  return outbox.items.find(
    (item) =>
      item.reference.toLocaleLowerCase("fr-FR") === normalized ||
      item.source_url.toLocaleLowerCase("fr-FR") === normalized
  );
}

function printPreview(items) {
  if (!items.length) {
    console.log("Nenhuma vaga está pronta para o Notion.");
    return;
  }
  for (const item of items) {
    console.log(
      `${item.reference} | ${item.match_score} | ${item.delivery_status} | ${item.employer} — ${item.title}`
    );
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const command = args._[0] ?? "preview";
  const { outbox, state } = await refreshOutbox();

  if (command === "preview") {
    printPreview(outbox.items);
    console.log(`Caixa de saída: ${OUTBOX_FILE}`);
    return;
  }

  if (command === "pending") {
    const pending = outbox.items.filter(
      (item) => item.approved && item.delivery_status !== "sent"
    );
    printPreview(pending);
    return;
  }

  const reference = args.reference;
  const item = findItem(outbox, reference);
  if (!item) throw new Error("Referência não encontrada na lista notion-ready.");

  if (command === "approve") {
    state.jobs[item.reference] = {
      ...(state.jobs[item.reference] ?? {}),
      approved: true,
      approved_at: new Date().toISOString(),
      delivery_status: "approved_for_manual_send"
    };
  } else if (command === "revoke") {
    state.jobs[item.reference] = {
      ...(state.jobs[item.reference] ?? {}),
      approved: false,
      approved_at: null,
      delivery_status: "pending_user_review"
    };
  } else if (command === "mark-sent") {
    if (!item.approved) throw new Error("A vaga precisa estar aprovada antes do envio.");
    if (!args["page-url"]) throw new Error("Informe --page-url após verificar o cartão.");
    state.jobs[item.reference] = {
      ...(state.jobs[item.reference] ?? {}),
      approved: true,
      delivery_status: "sent",
      notion_page_url: args["page-url"],
      sent_at: new Date().toISOString()
    };
  } else {
    throw new Error("Comando esperado: preview, approve, revoke, pending ou mark-sent.");
  }

  await writeJsonAtomic(STATE_FILE, state);
  const refreshed = await refreshOutbox();
  printPreview([findItem(refreshed.outbox, item.reference)]);
}

if (isMainModule(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { slugify } from "./utils.mjs";
import { SOURCE_PORTALS } from "./utils.mjs";

export const PROJECT_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  ".."
);

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw error;
  }
}

export async function writeJsonAtomic(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporaryPath = `${filePath}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temporaryPath, filePath);
}

export async function loadSeenJobs() {
  return readJson(path.join(PROJECT_ROOT, "data", "seen-jobs.json"), {
    version: 1,
    jobs: {}
  });
}

export async function saveSeenJobs(value) {
  await writeJsonAtomic(path.join(PROJECT_ROOT, "data", "seen-jobs.json"), value);
}

export async function saveDiscoveredJobs(jobs) {
  await writeJsonAtomic(path.join(PROJECT_ROOT, "data", "discovered.json"), {
    generated_at: new Date().toISOString(),
    count: jobs.length,
    jobs
  });
}

export async function savePreFilterReport({ accepted, rejected }) {
  await writeJsonAtomic(path.join(PROJECT_ROOT, "data", "pre-filter.json"), {
    generated_at: new Date().toISOString(),
    accepted_count: accepted.length,
    rejected_count: rejected.length,
    accepted,
    rejected
  });
}

export async function saveExtractedJob(job) {
  const reference = job.reference || job.title || "vaga";
  const filename = `${slugify(reference)}.json`;
  const filePath = path.join(PROJECT_ROOT, "output", job.source_portal, filename);
  await writeJsonAtomic(filePath, job);
  return filePath;
}

export async function loadExtractedJobs() {
  const outputRoot = path.join(PROJECT_ROOT, "output");
  const jobs = [];
  for (const portal of SOURCE_PORTALS) {
    const directory = path.join(outputRoot, portal);
    let entries = [];
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch (error) {
      if (error.code === "ENOENT") continue;
      throw error;
    }
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
      jobs.push(await readJson(path.join(directory, entry.name), null));
    }
  }
  return jobs.filter(Boolean);
}

export async function saveRankingArtifacts(ranking, csv) {
  const generatedAt = new Date().toISOString();
  const date = generatedAt.slice(0, 10);
  await writeJsonAtomic(path.join(PROJECT_ROOT, "data", "all-scored.json"), {
    generated_at: generatedAt,
    count: ranking.all_scored.length,
    jobs: ranking.all_scored
  });
  await writeJsonAtomic(path.join(PROJECT_ROOT, "data", "notion-ready.json"), {
    generated_at: generatedAt,
    review_required: true,
    sent_to_notion: false,
    count: ranking.notion_ready.length,
    jobs: ranking.notion_ready
  });
  await writeJsonAtomic(path.join(PROJECT_ROOT, "data", "rejected.json"), {
    generated_at: generatedAt,
    count: ranking.rejected.length,
    jobs: ranking.rejected
  });

  const shortlistDirectory = path.join(PROJECT_ROOT, "output", "shortlists");
  await mkdir(shortlistDirectory, { recursive: true });
  const csvPath = path.join(shortlistDirectory, `public-jobs-top-20-${date}.csv`);
  await writeFile(csvPath, csv, "utf8");
  return csvPath;
}

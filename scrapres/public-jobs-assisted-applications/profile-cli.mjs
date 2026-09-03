import { copyFile, mkdir, readdir } from "node:fs/promises";
import { constants, existsSync } from "node:fs";
import path from "node:path";
import {
  LOCAL_PROFILE_PATH,
  PROJECT_ROOT,
  loadSearchProfile,
  resolveProjectPath
} from "./lib/search-profile.mjs";
import { parseArgs } from "./lib/utils.mjs";

const PROFILES_DIR = path.join(PROJECT_ROOT, "config", "profiles");

async function listProfiles() {
  const entries = await readdir(PROFILES_DIR, { withFileTypes: true });
  const names = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .map((entry) => entry.name.replace(/\.json$/, ""))
    .sort();
  for (const name of names) console.log(name);
}

async function initProfile(args) {
  const preset = args.preset ?? "administrative-fr";
  const source = path.join(PROFILES_DIR, `${preset}.json`);
  const output = args.output ? resolveProjectPath(args.output) : LOCAL_PROFILE_PATH;
  if (!existsSync(source)) throw new Error(`Preset desconhecido: ${preset}`);
  if (existsSync(output) && !args.force) {
    throw new Error(
      `O arquivo já existe: ${output}. Use --force somente se deseja sobrescrevê-lo.`
    );
  }
  await mkdir(path.dirname(output), { recursive: true });
  await copyFile(source, output, args.force ? 0 : constants.COPYFILE_EXCL);
  console.log(`Perfil local criado: ${output}`);
  console.log("Edite o arquivo e configure JOB_SEARCH_PROFILE se usar outro caminho.");
}

function checkProfile(args) {
  const selected = args.profile ? resolveProjectPath(args.profile) : undefined;
  const { profile, path: profilePath } = loadSearchProfile({ profilePath: selected });
  const evidenceCount = Object.values(profile.evidence).flat().length;
  console.log(`OK: ${profile.display_name}`);
  console.log(`id: ${profile.id}`);
  console.log(`arquivo: ${profilePath}`);
  console.log(`score mínimo: ${profile.minimum_notion_score}`);
  console.log(`regras diretas: ${profile.direct_match_rules.length}`);
  console.log(`IDs de evidência: ${evidenceCount}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const command = args._[0] ?? "check";
  if (command === "list") return listProfiles();
  if (command === "init") return initProfile(args);
  if (command === "check") return checkProfile(args);
  throw new Error("Comando esperado: list, init ou check.");
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});

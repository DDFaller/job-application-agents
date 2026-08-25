import { access, mkdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import {
  attachApplicationBundle,
  createApplicationHandoff,
  createEmptyApplicationQueue,
  findApplication,
  linkApplicationUrl,
  markApplicationApplied,
  markApplicationOpened,
  registerHandoff,
  upsertApplication
} from "./lib/application-queue.mjs";
import { PROJECT_ROOT, writeJsonAtomic } from "./lib/storage.mjs";
import { isMainModule, parseArgs, slugify } from "./lib/utils.mjs";

const QUEUE_FILE = path.join(PROJECT_ROOT, "data", "application-queue.json");
const RANKED_FILE = path.join(PROJECT_ROOT, "data", "notion-ready.json");
const HANDOFF_DIRECTORY = path.join(PROJECT_ROOT, "data", "application-handoffs");

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw error;
  }
}

async function loadQueue() {
  return readJson(QUEUE_FILE, createEmptyApplicationQueue());
}

function requireArgument(args, name) {
  const value = args[name];
  if (!value || value === true) throw new Error(`Informe --${name}.`);
  return value;
}

function printItems(items) {
  if (!items.length) {
    console.log("Nenhuma candidatura na fila.");
    return;
  }
  for (const item of items) {
    console.log(
      `${item.reference} | ${item.status} | ${item.platform} | ${item.employer} — ${item.title}`
    );
  }
}

function openCommand() {
  if (process.platform === "darwin") return { command: "open", args: [] };
  if (process.platform === "win32") return { command: "cmd", args: ["/c", "start", ""] };
  return { command: "xdg-open", args: [] };
}

async function launchUrl(url) {
  const launcher = openCommand();
  await new Promise((resolve, reject) => {
    const child = spawn(launcher.command, [...launcher.args, url], {
      stdio: "ignore",
      shell: false
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`O navegador não pôde ser aberto (código ${code}).`));
    });
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const command = args._[0] ?? "list";
  const queue = await loadQueue();

  if (command === "list") {
    printItems(queue.items);
    console.log(`Fila privada: ${QUEUE_FILE}`);
    return;
  }

  if (command === "import-ranked") {
    const ranked = await readJson(RANKED_FILE, null);
    if (!ranked) {
      throw new Error("Execute o ranking antes: data/notion-ready.json não existe.");
    }
    for (const job of ranked.jobs ?? []) upsertApplication(queue, job);
    await writeJsonAtomic(QUEUE_FILE, queue);
    printItems(queue.items);
    return;
  }

  if (command === "add") {
    const url = requireArgument(args, "url");
    const item = upsertApplication(queue, {
      source_url: url,
      application_url: url,
      reference: args.reference,
      title: args.title,
      employer: args.employer
    });
    await writeJsonAtomic(QUEUE_FILE, queue);
    printItems([item]);
    return;
  }

  const reference = requireArgument(args, "reference");
  const item = findApplication(queue, reference);
  if (!item) throw new Error("Referência não encontrada na fila de candidaturas.");

  if (command === "link") {
    const updated = linkApplicationUrl(queue, reference, requireArgument(args, "url"));
    await writeJsonAtomic(QUEUE_FILE, queue);
    printItems([updated]);
    return;
  }

  if (command === "handoff") {
    const handoff = createApplicationHandoff(item);
    await mkdir(HANDOFF_DIRECTORY, { recursive: true });
    const handoffPath = path.join(HANDOFF_DIRECTORY, `${slugify(item.reference)}.json`);
    await writeJsonAtomic(handoffPath, handoff);
    registerHandoff(queue, reference, handoffPath);
    await writeJsonAtomic(QUEUE_FILE, queue);
    console.log(`Handoff: ${handoffPath}`);
    console.log(handoff.suggested_prompt);
    return;
  }

  if (command === "attach") {
    const bundlePath = path.resolve(requireArgument(args, "bundle"));
    const bundleStat = await stat(bundlePath);
    if (!bundleStat.isDirectory() && !bundleStat.isFile()) {
      throw new Error("O bundle precisa ser um arquivo ou diretório existente.");
    }
    const updated = attachApplicationBundle(queue, reference, bundlePath);
    await writeJsonAtomic(QUEUE_FILE, queue);
    printItems([updated]);
    return;
  }

  if (command === "open") {
    console.log(item.application_url);
    if (!args.launch) {
      console.log("Use --launch para abrir no navegador padrão após revisar a URL.");
      return;
    }
    const updated = markApplicationOpened(queue, reference);
    await access(updated.bundle_path);
    await launchUrl(item.application_url);
    await writeJsonAtomic(QUEUE_FILE, queue);
    printItems([updated]);
    return;
  }

  if (command === "mark-applied") {
    const updated = markApplicationApplied(queue, reference, {
      confirmed: args.confirmed === true
    });
    await writeJsonAtomic(QUEUE_FILE, queue);
    printItems([updated]);
    return;
  }

  throw new Error(
    "Comando esperado: list, import-ranked, add, link, handoff, attach, open ou mark-applied."
  );
}

if (isMainModule(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

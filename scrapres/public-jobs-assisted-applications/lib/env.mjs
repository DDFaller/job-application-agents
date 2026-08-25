import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

try {
  process.loadEnvFile(path.join(projectRoot, ".env"));
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

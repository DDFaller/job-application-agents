import { readFileSync } from "node:fs";
import { searchProfile } from "./active-search-profile.mjs";
import { resolveProjectPath } from "./search-profile.mjs";

const configuredPath =
  process.env.CAREER_PROFILE_CURRENT ?? searchProfile.career_profile_current ?? "";

export const careerProfilePath = resolveProjectPath(configuredPath);
export const careerProfileManifest = careerProfilePath
  ? JSON.parse(readFileSync(careerProfilePath, "utf8"))
  : null;
export const careerProfileVersion =
  careerProfileManifest?.version ?? `${searchProfile.id}:${searchProfile.profile_version}`;

const approvedIds = new Set();
for (const filename of Object.keys(careerProfileManifest?.source_hashes ?? {})) {
  const content = readFileSync(
    `${careerProfileManifest.source_dir}/${filename}`,
    "utf8"
  );
  for (const match of content.matchAll(/\[(MC-[A-Z]+-\d+)\]/g)) {
    approvedIds.add(match[1]);
  }
}

export function assertApprovedEvidenceIds(ids) {
  const requested = [...new Set(ids)].filter(Boolean);
  if (requested.length && !careerProfileManifest) {
    throw new Error(
      "O perfil contém IDs de evidência, mas nenhum master curriculum foi configurado. " +
        "Defina CAREER_PROFILE_CURRENT ou career_profile_current no perfil local."
    );
  }
  const unknown = requested.filter((id) => !approvedIds.has(id));
  if (unknown.length) {
    throw new Error(
      `IDs de evidência ausentes no master curriculum ${careerProfileVersion}: ${unknown.join(", ")}`
    );
  }
}

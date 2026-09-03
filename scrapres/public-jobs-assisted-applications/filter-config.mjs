import {
  assertApprovedEvidenceIds,
  careerProfileVersion
} from "./lib/career-profile.mjs";
import {
  searchProfile,
  searchProfilePath
} from "./lib/active-search-profile.mjs";

export const filterConfig = {
  ...searchProfile,
  version: `${searchProfile.id}:${searchProfile.profile_version}`,
  profile_version: careerProfileVersion,
  source_file: searchProfilePath
};

// Evidências são opcionais no preset público. Cada usuário pode mapeá-las no
// perfil local e validá-las contra seu próprio master curriculum.
export const profileEvidence = searchProfile.evidence;

assertApprovedEvidenceIds(Object.values(profileEvidence).flat());

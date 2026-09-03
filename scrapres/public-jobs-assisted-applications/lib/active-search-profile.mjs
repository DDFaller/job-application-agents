import { loadSearchProfile } from "./search-profile.mjs";

const loaded = loadSearchProfile();

export const searchProfile = loaded.profile;
export const searchProfilePath = loaded.path;

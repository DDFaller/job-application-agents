import "./env.mjs";

export const FRANCE_TRAVAIL_TOKEN_URL =
  "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire";
export const FRANCE_TRAVAIL_API_BASE_URL =
  "https://api.francetravail.io/partenaire/offresdemploi/v2";
export const FRANCE_TRAVAIL_SCOPE = "api_offresdemploiv2 o2dsoffre";

let tokenCache = null;

export function hasFranceTravailCredentials(env = process.env) {
  return Boolean(
    env.FRANCE_TRAVAIL_CLIENT_ID?.trim() &&
      env.FRANCE_TRAVAIL_CLIENT_SECRET?.trim()
  );
}

function credentials(env) {
  const clientId = env.FRANCE_TRAVAIL_CLIENT_ID?.trim();
  const clientSecret = env.FRANCE_TRAVAIL_CLIENT_SECRET?.trim();
  if (!clientId || !clientSecret) {
    throw new Error(
      "France Travail não configurado. Defina FRANCE_TRAVAIL_CLIENT_ID e " +
        "FRANCE_TRAVAIL_CLIENT_SECRET no arquivo .env."
    );
  }
  return { clientId, clientSecret };
}

function responseErrorDetails(payload) {
  if (!payload || typeof payload !== "object") return "";
  const code = typeof payload.error === "string" ? payload.error.trim() : "";
  const description =
    typeof payload.error_description === "string"
      ? payload.error_description.trim()
      : typeof payload.message === "string"
        ? payload.message.trim()
        : "";
  return [code, description].filter(Boolean).join(": ").slice(0, 500);
}

function franceTravailAuthenticationHint(payload) {
  if (payload?.error === "invalid_client") {
    return (
      "O France Travail recusou o cliente. No portal francetravail.io, confirme " +
      "que a aplicação está ativa e subscrita à API « Offres d'emploi v2 », e " +
      "que o Client ID e a clé secrète pertencem à mesma aplicação. Se a chave " +
      "foi regenerada, atualize as duas variáveis no .env."
    );
  }
  if (payload?.error === "invalid_scope") {
    return (
      "A aplicação não possui o escopo solicitado. Subscreva-a à API " +
      "« Offres d'emploi v2 » no portal francetravail.io."
    );
  }
  return "";
}

async function parseJsonResponse(response, operation) {
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`${operation}: resposta JSON inválida (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    const details = responseErrorDetails(payload);
    const hint = operation === "Autenticação France Travail"
      ? franceTravailAuthenticationHint(payload)
      : "";
    throw new Error(
      `${operation}: HTTP ${response.status}${details ? ` (${details})` : ""}.` +
        `${hint ? ` ${hint}` : ""}`
    );
  }
  return payload;
}

export async function getFranceTravailAccessToken({
  fetchImpl = fetch,
  env = process.env,
  now = Date.now(),
  forceRefresh = false
} = {}) {
  const { clientId, clientSecret } = credentials(env);
  if (
    !forceRefresh &&
    tokenCache?.clientId === clientId &&
    tokenCache.expiresAt > now + 60_000
  ) {
    return tokenCache.accessToken;
  }

  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: clientId,
    client_secret: clientSecret,
    scope: FRANCE_TRAVAIL_SCOPE
  });
  const response = await fetchImpl(FRANCE_TRAVAIL_TOKEN_URL, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: body.toString(),
    signal: AbortSignal.timeout(
      Number.parseInt(env.HTTP_TIMEOUT_MS ?? "25000", 10)
    )
  });
  const payload = await parseJsonResponse(response, "Autenticação France Travail");
  if (typeof payload.access_token !== "string" || !payload.access_token) {
    throw new Error("Autenticação France Travail: access_token ausente.");
  }

  const expiresIn = Number.isFinite(Number(payload.expires_in))
    ? Number(payload.expires_in)
    : 1_200;
  tokenCache = {
    clientId,
    accessToken: payload.access_token,
    expiresAt: now + expiresIn * 1_000
  };
  return tokenCache.accessToken;
}

export async function franceTravailApiRequest(
  pathname,
  {
    query = {},
    headers = {},
    fetchImpl = fetch,
    env = process.env,
    retryAuthentication = true
  } = {}
) {
  const url = new URL(`${FRANCE_TRAVAIL_API_BASE_URL}/${pathname.replace(/^\/+/, "")}`);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const accessToken = await getFranceTravailAccessToken({ fetchImpl, env });
  const response = await fetchImpl(url, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
      ...headers
    },
    signal: AbortSignal.timeout(
      Number.parseInt(env.HTTP_TIMEOUT_MS ?? "25000", 10)
    )
  });

  if (response.status === 401 && retryAuthentication) {
    await getFranceTravailAccessToken({
      fetchImpl,
      env,
      forceRefresh: true
    });
    return franceTravailApiRequest(pathname, {
      query,
      headers,
      fetchImpl,
      env,
      retryAuthentication: false
    });
  }

  return parseJsonResponse(response, `API France Travail (${pathname})`);
}

export function clearFranceTravailTokenCache() {
  tokenCache = null;
}

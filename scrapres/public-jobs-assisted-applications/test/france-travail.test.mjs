import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  discoverFranceTravail,
  normalizeFranceTravailOffer
} from "../discover-france-travail.mjs";
import {
  clearFranceTravailTokenCache,
  getFranceTravailAccessToken,
  hasFranceTravailCredentials
} from "../lib/france-travail-client.mjs";
import { preFilterSource } from "../rank-jobs.mjs";

const offer = JSON.parse(
  await readFile(new URL("./fixtures/france-travail-offer.json", import.meta.url), "utf8")
);
const testEnv = {
  FRANCE_TRAVAIL_CLIENT_ID: "client-test",
  FRANCE_TRAVAIL_CLIENT_SECRET: "secret-test",
  HTTP_TIMEOUT_MS: "1000"
};

test("detecta a presença das duas credenciais France Travail", () => {
  assert.equal(hasFranceTravailCredentials(testEnv), true);
  assert.equal(hasFranceTravailCredentials({ FRANCE_TRAVAIL_CLIENT_ID: "x" }), false);
});

test("autentica com client_credentials sem expor o segredo", async () => {
  clearFranceTravailTokenCache();
  let request;
  const fetchImpl = async (url, options) => {
    request = { url: String(url), options };
    return new Response(JSON.stringify({ access_token: "token-test", expires_in: 1200 }), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });
  };

  const token = await getFranceTravailAccessToken({ fetchImpl, env: testEnv });
  assert.equal(token, "token-test");
  assert.match(request.url, /access_token/);
  assert.match(request.options.body, /grant_type=client_credentials/);
  assert.match(request.options.body, /scope=api_offresdemploiv2\+o2dsoffre/);
  assert.match(request.options.body, /client_secret=secret-test/);
});

test("explica invalid_client sem expor as credenciais", async () => {
  clearFranceTravailTokenCache();
  const fetchImpl = async () =>
    new Response(
      JSON.stringify({
        error: "invalid_client",
        error_description: "Client authentication failed"
      }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    );

  await assert.rejects(
    () => getFranceTravailAccessToken({ fetchImpl, env: testEnv }),
    (error) => {
      assert.match(error.message, /HTTP 400.*invalid_client/);
      assert.match(error.message, /subscrita.*Offres d'emploi v2/);
      assert.doesNotMatch(error.message, /client-test|secret-test/);
      return true;
    }
  );
});

test("explica invalid_scope com a subscrição necessária", async () => {
  clearFranceTravailTokenCache();
  const fetchImpl = async () =>
    new Response(JSON.stringify({ error: "invalid_scope" }), {
      status: 400,
      headers: { "Content-Type": "application/json" }
    });

  await assert.rejects(
    () => getFranceTravailAccessToken({ fetchImpl, env: testEnv }),
    /invalid_scope.*Subscreva-a.*Offres d'emploi v2/
  );
});

test("normaliza a oferta sem conservar email ou telefone de contato", () => {
  const normalized = normalizeFranceTravailOffer(offer);
  assert.equal(normalized.reference, "190ABCD");
  assert.equal(normalized.source_portal, "france-travail");
  assert.match(normalized.source_url, /\/detail\/190ABCD$/);
  assert.doesNotMatch(normalized.prepared_source.content, /example\.test|0102030405/);
  assert.equal(preFilterSource(normalized.prepared_source).accepted, true);
});

test("descobre por palavras-chave, pagina e deduplica IDs", async () => {
  clearFranceTravailTokenCache();
  const apiRequests = [];
  const fetchImpl = async (url, options = {}) => {
    const value = String(url);
    if (value.includes("access_token")) {
      return new Response(JSON.stringify({ access_token: "token-test", expires_in: 1200 }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
    apiRequests.push({ url: value, options });
    const resultats = apiRequests.length === 1
      ? Array.from({ length: 20 }, () => offer)
      : [offer, offer];
    return new Response(JSON.stringify({ resultats }), {
      status: 206,
      headers: { "Content-Type": "application/json" }
    });
  };
  const profile = {
    france_travail: {
      keywords: ["agent administratif"],
      departments: ["75"]
    }
  };

  const jobs = await discoverFranceTravail({
    pages: 2,
    profile,
    fetchImpl,
    env: testEnv
  });
  assert.equal(jobs.length, 1);
  assert.equal(apiRequests.length, 2, "uma página completa avança até a parcial");
  assert.match(apiRequests[0].url, /motsCles=agent\+administratif/);
  assert.match(apiRequests[0].url, /departement=75/);
  assert.match(apiRequests[0].url, /range=0-19/);
  assert.match(apiRequests[1].url, /range=20-39/);
  assert.equal(apiRequests[0].options.headers.Range, undefined);
  assert.equal(apiRequests[0].options.headers.Authorization, "Bearer token-test");
});

test("falha com orientação clara quando as credenciais faltam", async () => {
  clearFranceTravailTokenCache();
  await assert.rejects(
    () => getFranceTravailAccessToken({ env: {} }),
    /FRANCE_TRAVAIL_CLIENT_ID.*FRANCE_TRAVAIL_CLIENT_SECRET/
  );
});

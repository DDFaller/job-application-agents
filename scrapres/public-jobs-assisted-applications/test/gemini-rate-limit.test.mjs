import assert from "node:assert/strict";
import test from "node:test";
import {
  callGeminiWithModelFallback,
  callGeminiWithRetry,
  geminiRetryDelayMs,
  isGeminiDailyQuotaError,
  isGeminiModelUnavailableError,
  isGeminiRateLimitError,
  isGeminiTransientError
} from "../lib/gemini-rate-limit.mjs";
import { generateStructuredJobResponse } from "../extract-job.mjs";

test("reconhece 429 e adiciona margem ao prazo sugerido", () => {
  const error = Object.assign(
    new Error("429 quota exceeded. Please retry in 4.455942384s."),
    { status: 429 }
  );

  assert.equal(isGeminiRateLimitError(error), true);
  assert.equal(geminiRetryDelayMs(error), 5956);
});

test("não repete 429 sem prazo, que pode representar cota diária", () => {
  const error = Object.assign(new Error("429 quota exceeded"), { status: 429 });
  assert.equal(geminiRetryDelayMs(error), null);
});

test("não repete limite diário mesmo quando a API sugere segundos", () => {
  const error = Object.assign(
    new Error(
      'quotaId":"GenerateRequestsPerDayPerProjectPerModel-FreeTier" retryDelay":"58s"'
    ),
    { status: 429 }
  );
  assert.equal(isGeminiDailyQuotaError(error), true);
  assert.equal(geminiRetryDelayMs(error), null);
});

test("troca de modelo quando a cota diária do principal acaba", async () => {
  const calls = [];
  const fallbacks = [];
  const dailyError = Object.assign(
    new Error("GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
    { status: 429 }
  );

  const response = await callGeminiWithModelFallback(
    async (model) => {
      calls.push(model);
      if (model === "principal") throw dailyError;
      return "ok";
    },
    ["principal", "reserva"],
    { onFallback: (event) => fallbacks.push(event) }
  );

  assert.deepEqual(calls, ["principal", "reserva"]);
  assert.equal(response.model, "reserva");
  assert.equal(response.result, "ok");
  assert.equal(fallbacks[0].nextModel, "reserva");
});

test("troca modelos descontinuados sem repetir o mesmo modelo", async () => {
  const unavailable = Object.assign(
    new Error("This model is no longer available to new users"),
    { status: 404 }
  );
  assert.equal(isGeminiModelUnavailableError(unavailable), true);
  const response = await callGeminiWithModelFallback(
    async (model) => {
      if (model === "antigo") throw unavailable;
      return "ok";
    },
    ["antigo", "atual"]
  );
  assert.equal(response.model, "atual");
});

test("reconhece 503 UNAVAILABLE e troca para o modelo alternativo", async () => {
  const unavailable = new Error(
    '{"error":{"code":503,"message":"This model is currently experiencing high demand.","status":"UNAVAILABLE"}}'
  );
  assert.equal(isGeminiModelUnavailableError(unavailable), true);
  assert.equal(isGeminiTransientError(unavailable), true);
  assert.equal(geminiRetryDelayMs(unavailable, 1), 5000);
  assert.equal(geminiRetryDelayMs(unavailable, 2), 10000);

  const calls = [];
  const response = await callGeminiWithModelFallback(
    async (model) => {
      calls.push(model);
      if (model === "ocupado") throw unavailable;
      return "ok";
    },
    ["ocupado", "reserva"]
  );

  assert.deepEqual(calls, ["ocupado", "reserva"]);
  assert.equal(response.model, "reserva");
});

test("repete falha transitória de rede com backoff", async () => {
  let calls = 0;
  const waits = [];
  const result = await callGeminiWithRetry(
    async () => {
      calls += 1;
      if (calls < 3) throw new TypeError("fetch failed");
      return "ok";
    },
    {
      sleep: async (delayMs) => waits.push(delayMs),
      maxAttempts: 3
    }
  );

  assert.equal(result, "ok");
  assert.equal(calls, 3);
  assert.deepEqual(waits, [5000, 10000]);
});

test("repete uma chamada temporariamente limitada e preserva o resultado", async () => {
  let calls = 0;
  const waits = [];
  const result = await callGeminiWithRetry(
    async () => {
      calls += 1;
      if (calls === 1) {
        throw Object.assign(new Error("Please retry in 2s."), { status: 429 });
      }
      return "ok";
    },
    {
      sleep: async (delayMs) => waits.push(delayMs),
      maxAttempts: 2
    }
  );

  assert.equal(result, "ok");
  assert.equal(calls, 2);
  assert.deepEqual(waits, [3500]);
});

test("extrai cada vaga com uma única chamada generateContent", async () => {
  const calls = [];
  const client = {
    models: {
      generateContent: async (parameters) => {
        calls.push(parameters);
        return { text: "{}" };
      }
    }
  };
  const source = {
    url: "https://www.emploi-territorial.fr/offre/o001-test",
    portal: "emploi-territorial",
    reference: "O001",
    format: "texto HTML limpo",
    content: "Agent administratif"
  };

  const response = await generateStructuredJobResponse(client, source);

  assert.equal(response.text, "{}");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].config.responseMimeType, "application/json");
  assert.equal(calls[0].config.responseJsonSchema.type, "object");
  assert.match(calls[0].contents, /Agent administratif/);
});

function errorMessage(error) {
  return String(error?.message ?? error ?? "");
}

export function isGeminiRateLimitError(error) {
  const message = errorMessage(error);
  return (
    error?.status === 429 ||
    error?.code === 429 ||
    /^429\b/.test(message) ||
    /quota exceeded|rate.?limit/i.test(message)
  );
}

export function isGeminiDailyQuotaError(error) {
  if (!isGeminiRateLimitError(error)) return false;
  const message = errorMessage(error);
  return /PerDay|requests?\s+per\s+day|daily\s+quota/i.test(message);
}

export function isGeminiModelUnavailableError(error) {
  const message = errorMessage(error);
  return (
    error?.status === 404 ||
    error?.code === 404 ||
    /model.+(?:not found|no longer available|not supported)/i.test(message) ||
    isGeminiServiceUnavailableError(error)
  );
}

export function isGeminiServiceUnavailableError(error) {
  const message = errorMessage(error);
  return (
    error?.status === 503 ||
    error?.code === 503 ||
    /["']?code["']?\s*:\s*503\b/i.test(message) ||
    /["']?status["']?\s*:\s*["']UNAVAILABLE["']/i.test(message) ||
    /model.+(?:high demand|temporarily unavailable)/i.test(message)
  );
}

export function isGeminiTransientError(error) {
  const message = errorMessage(error);
  const causeMessage = errorMessage(error?.cause);
  return (
    isGeminiServiceUnavailableError(error) ||
    [500, 502, 504].includes(error?.status) ||
    [500, 502, 504].includes(error?.code) ||
    /["']?code["']?\s*:\s*(?:500|502|504)\b/i.test(message) ||
    /\b(?:INTERNAL|BAD_GATEWAY|GATEWAY_TIMEOUT)\b/i.test(message) ||
    /\bfetch failed\b/i.test(message) ||
    /\b(?:ECONNRESET|ECONNREFUSED|ETIMEDOUT|UND_ERR_CONNECT_TIMEOUT)\b/i.test(
      `${message} ${causeMessage}`
    )
  );
}

export function geminiRetryDelayMs(error, attempt = 1) {
  const isRateLimit = isGeminiRateLimitError(error);
  const isTransient = isGeminiTransientError(error);
  if (!isRateLimit && !isTransient) return null;
  // RetryInfo também pode aparecer em limites diários. Nesse caso, repetir
  // após alguns segundos só gasta novas tentativas sem renovar a cota.
  if (isGeminiDailyQuotaError(error)) return null;

  const message = errorMessage(error);
  const patterns = [
    /please retry in\s+([0-9.]+)s/i,
    /retryDelay["'\s:=]+([0-9.]+)s/i,
    /retry after\s+([0-9.]+)s/i
  ];

  for (const pattern of patterns) {
    const match = message.match(pattern);
    if (!match) continue;
    const seconds = Number.parseFloat(match[1]);
    if (!Number.isFinite(seconds) || seconds < 0) continue;

    const bufferMs = Number.parseInt(
      process.env.GEMINI_RETRY_BUFFER_MS ?? "1500",
      10
    );
    const maxDelayMs = Number.parseInt(
      process.env.GEMINI_MAX_RETRY_DELAY_MS ?? "60000",
      10
    );
    return Math.min(Math.ceil(seconds * 1000) + bufferMs, maxDelayMs);
  }

  if (isTransient) {
    const initialDelayMs = Number.parseInt(
      process.env.GEMINI_TRANSIENT_RETRY_DELAY_MS ?? "5000",
      10
    );
    const maxDelayMs = Number.parseInt(
      process.env.GEMINI_MAX_RETRY_DELAY_MS ?? "60000",
      10
    );
    if (!Number.isFinite(initialDelayMs) || initialDelayMs < 0) return null;
    return Math.min(initialDelayMs * 2 ** Math.max(0, attempt - 1), maxDelayMs);
  }

  // Um 429 sem prazo de retomada pode ser uma cota diária. Não insistimos.
  return null;
}

export async function callGeminiWithModelFallback(
  operation,
  models,
  { onFallback = () => {} } = {}
) {
  let lastError;
  for (let index = 0; index < models.length; index += 1) {
    const model = models[index];
    try {
      return { result: await operation(model), model };
    } catch (error) {
      lastError = error;
      const nextModel = models[index + 1];
      const reason = isGeminiDailyQuotaError(error)
        ? "daily_quota"
        : isGeminiModelUnavailableError(error)
          ? "model_unavailable"
          : isGeminiRateLimitError(error)
            ? "rate_limit"
          : "";
      if (!nextModel || !reason) throw error;
      onFallback({ model, nextModel, reason, error });
    }
  }
  throw lastError;
}

export async function callGeminiWithRetry(
  operation,
  {
    maxAttempts = Number.parseInt(process.env.GEMINI_MAX_ATTEMPTS ?? "4", 10),
    onRetry = () => {},
    sleep = (delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs))
  } = {}
) {
  let attempt = 1;
  while (true) {
    try {
      return await operation();
    } catch (error) {
      const delayMs = geminiRetryDelayMs(error, attempt);
      if (delayMs === null || attempt >= maxAttempts) throw error;

      onRetry({ attempt, nextAttempt: attempt + 1, delayMs, error });
      await sleep(delayMs);
      attempt += 1;
    }
  }
}

export async function geminiRequestDelay() {
  // generateContent usa uma chamada por vaga. 5 s mantém até 12 chamadas por
  // minuto, com margem para a cota observada de 20 requisições por minuto.
  const delayMs = Number.parseInt(
    process.env.GEMINI_REQUEST_DELAY_MS ?? "5000",
    10
  );
  if (Number.isFinite(delayMs) && delayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
}

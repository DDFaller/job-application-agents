import "./env.mjs";

const USER_AGENT =
  "public-jobs-assisted-applications/1.1 (public-sector job search; respectful crawler)";

export async function requestText(url, options = {}) {
  const timeoutMs = Number.parseInt(process.env.HTTP_TIMEOUT_MS ?? "25000", 10);
  const headers = new Headers(options.headers ?? {});
  headers.set("Accept", headers.get("Accept") ?? "text/html,application/xhtml+xml");
  headers.set("User-Agent", headers.get("User-Agent") ?? USER_AGENT);

  const response = await fetch(url, {
    ...options,
    headers,
    redirect: "follow",
    signal: options.signal ?? AbortSignal.timeout(timeoutMs)
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ao acessar ${url}`);
  }

  return {
    text: await response.text(),
    headers: response.headers,
    status: response.status,
    url: response.url
  };
}

export function cookiesFromHeaders(headers) {
  const values = headers.getSetCookie?.() ?? [];
  return values.map((value) => value.split(";", 1)[0]).join("; ");
}

export async function politeDelay() {
  const delayMs = Number.parseInt(process.env.REQUEST_DELAY_MS ?? "1500", 10);
  if (delayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
}

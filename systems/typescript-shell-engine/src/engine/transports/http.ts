/**
 * HTTP transport — POST one envelope to the /api/v2/shell endpoint.
 *
 * The web endpoint answers protocol envelopes with `{"envelopes": [...]}`
 * (see systems/python-reference-runtime/l4/api_handlers/api_handlers_agent.py
 * `_shell_dispatch`); this
 * adapter serializes the envelopes back into response lines so the bridge
 * decodes them with the same code path as every other transport.
 */

import type { Transport } from "../bridge.ts";

export interface HttpTransportOptions {
  baseUrl: string;
  /** Path of the shell endpoint (default /api/v2/shell). */
  path?: string;
  /** Abort timeout in ms (default 10000). */
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

/** Create an HTTP transport posting envelopes to the shell endpoint. */
export function createHttpTransport(options: HttpTransportOptions): Transport {
  const { baseUrl, path = "/api/v2/shell", timeoutMs = 10000 } = options;
  const fetchImpl = options.fetchImpl ?? fetch;
  const endpoint = `${baseUrl.replace(/\/$/, "")}${path}`;

  return async (line: string) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: line,
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`http transport: ${response.status} ${response.statusText}`);
      }
      const body = (await response.json()) as { envelopes?: unknown[] };
      if (!Array.isArray(body.envelopes)) {
        throw new Error("http transport: response lacks envelopes array");
      }
      return body.envelopes.map((envelope) => JSON.stringify(envelope));
    } finally {
      clearTimeout(timer);
    }
  };
}

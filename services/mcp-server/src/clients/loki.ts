const LOKI_URL = process.env.LOKI_URL ?? "http://localhost:3100";

export interface LokiStream {
  stream: Record<string, string>;
  values: [string, string][];
}

interface LokiResponse {
  status: string;
  data: {
    resultType: string;
    result: LokiStream[];
  };
}

export async function queryRange(
  query: string,
  start: string,
  end: string,
  limit = 1000,
  direction: "forward" | "backward" = "forward",
): Promise<LokiStream[]> {
  const params = new URLSearchParams({
    query,
    start,
    end,
    limit: String(limit),
    direction,
  });

  const url = `${LOKI_URL}/loki/api/v1/query_range?${params}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Loki query failed: ${res.status} ${await res.text()}`);
  }

  const body = (await res.json()) as LokiResponse;
  if (body.status !== "success") {
    throw new Error(`Loki query error: ${JSON.stringify(body)}`);
  }
  return body.data.result;
}

export async function testConnection(): Promise<void> {
  const res = await fetch(`${LOKI_URL}/ready`);
  if (!res.ok) {
    throw new Error(`Loki unreachable: ${res.status}`);
  }
  console.log("[loki] connection verified");
}

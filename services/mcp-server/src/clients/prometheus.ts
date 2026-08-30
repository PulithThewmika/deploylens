const PROM_URL = process.env.PROM_URL ?? "http://localhost:9090";

export interface PromInstantResult {
  metric: Record<string, string>;
  value: [number, string];
}

export interface PromRangeResult {
  metric: Record<string, string>;
  values: [number, string][];
}

interface PromResponse<T> {
  status: string;
  data: {
    resultType: string;
    result: T[];
  };
}

export async function instantQuery(
  query: string,
  time?: string,
): Promise<PromInstantResult[]> {
  const params = new URLSearchParams({ query });
  if (time) params.set("time", time);

  const url = `${PROM_URL}/api/v1/query?${params}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Prometheus query failed: ${res.status} ${await res.text()}`);
  }

  const body = (await res.json()) as PromResponse<PromInstantResult>;
  if (body.status !== "success") {
    throw new Error(`Prometheus query error: ${JSON.stringify(body)}`);
  }
  return body.data.result;
}

export async function rangeQuery(
  query: string,
  start: string,
  end: string,
  step: string,
): Promise<PromRangeResult[]> {
  const params = new URLSearchParams({ query, start, end, step });

  const url = `${PROM_URL}/api/v1/query_range?${params}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Prometheus range query failed: ${res.status} ${await res.text()}`);
  }

  const body = (await res.json()) as PromResponse<PromRangeResult>;
  if (body.status !== "success") {
    throw new Error(`Prometheus range query error: ${JSON.stringify(body)}`);
  }
  return body.data.result;
}

export async function testConnection(): Promise<void> {
  const res = await fetch(`${PROM_URL}/api/v1/status/buildinfo`);
  if (!res.ok) {
    throw new Error(`Prometheus unreachable: ${res.status}`);
  }
  console.log("[prometheus] connection verified");
}

import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

const client = createClient<paths>({ baseUrl: "" });

export type HealthStatus = components["schemas"]["Health"];

export async function getHealth(): Promise<HealthStatus> {
  const { data, error, response } = await client.GET("/api/v1/health/");
  if (error || !data) {
    throw new Error(`Health API zwróciło status ${response.status}`);
  }
  return data;
}

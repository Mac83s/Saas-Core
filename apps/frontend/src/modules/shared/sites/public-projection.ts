import { request as httpRequest } from "node:http";

/** The XML projections a reader's feed client and a crawler ask for.
 *
 *  Proxied as bytes rather than rebuilt here: the backend already knows the
 *  canonical hostname and what is published, and a second serializer would be
 *  a second place for the escaping to be wrong. */
export type ProjectionResult =
  { kind: "xml"; body: string; contentType: string } | { kind: "not-found" };

/** `fetch` cannot send this request: `Host` is a forbidden header name, so
 *  undici replaces it with the upstream's own address and the backend resolves
 *  the wrong site. The visitor's host is the whole routing key. */
function requestBackend(
  url: URL,
  host: string,
): Promise<{ status: number; body: string; contentType: string }> {
  return new Promise((resolve, reject) => {
    const outgoing = httpRequest(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: "GET",
        headers: { host, accept: "application/xml" },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode ?? 0,
            body: Buffer.concat(chunks).toString("utf8"),
            contentType:
              (response.headers["content-type"] as string | undefined) ??
              "application/xml; charset=utf-8",
          }),
        );
      },
    );
    outgoing.on("error", reject);
    outgoing.end();
  });
}

export async function getPublicProjection(
  host: string,
  resource: "feed.xml" | "sitemap.xml" | "robots.txt",
): Promise<ProjectionResult> {
  const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const response = await requestBackend(
    new URL(`/api/v1/public/site/${resource}`, backend),
    host,
  );
  if (response.status === 404) return { kind: "not-found" };
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Public Sites API zwróciło status ${response.status}`);
  }
  return {
    kind: "xml",
    body: response.body,
    contentType: response.contentType,
  };
}

import { request as httpRequest } from "node:http";

/**
 * Whether an address of a company's site is gone for good (ADR-077), asked of
 * the backend before the visit reaches the page: a page can answer 404 but
 * not 410, so the proxy answers it.
 *
 * A site without any such address says so, and its host is not asked again
 * for a minute — every other site pays one small request a minute for a
 * feature it does not use. A backend that does not answer in time is no
 * verdict: the page then says the same words with a 404.
 */
export interface GoneVerdict {
  readonly gone: boolean;
  readonly locale?: string;
  readonly homePath?: string;
}

const QUIET_MS = 60_000;
const ANSWER_MS = 2_000;
/** Hosts are the visitor's word; the memo must not grow with every one. */
const QUIET_LIMIT = 5_000;
const quietUntil = new Map<string, number>();

export async function goneVerdict(
  host: string,
  path: string,
  now: number = Date.now(),
): Promise<GoneVerdict> {
  if ((quietUntil.get(host) ?? 0) > now) return { gone: false };
  try {
    const answer = await ask(host, path);
    if (answer.rules) {
      quietUntil.delete(host);
    } else {
      if (quietUntil.size >= QUIET_LIMIT) quietUntil.clear();
      quietUntil.set(host, now + QUIET_MS);
    }
    return answer.gone === true
      ? {
          gone: true,
          ...(typeof answer.locale === "string"
            ? { locale: answer.locale }
            : {}),
          ...(typeof answer.home_path === "string"
            ? { homePath: answer.home_path }
            : {}),
        }
      : { gone: false };
  } catch {
    return { gone: false };
  }
}

/** For tests: forget which hosts said they have nothing gone. */
export function forgetQuietHosts(): void {
  quietUntil.clear();
}

type BackendVerdict = {
  rules?: unknown;
  gone?: unknown;
  locale?: unknown;
  home_path?: unknown;
};

/** `node:http`, as the page's own request: `fetch` cannot send the visitor's
 *  `Host`, and the host is what names the site (`public-site.tsx`). */
function ask(host: string, path: string): Promise<BackendVerdict> {
  const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const url = new URL("/api/v1/public/site/gone/", backend);
  url.searchParams.set("path", path);
  return new Promise((resolve, reject) => {
    const outgoing = httpRequest(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        method: "GET",
        headers: { host, accept: "application/json" },
        timeout: ANSWER_MS,
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => {
          try {
            if (response.statusCode !== 200) throw new Error("no verdict");
            resolve(
              JSON.parse(
                Buffer.concat(chunks).toString("utf8"),
              ) as BackendVerdict,
            );
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    outgoing.on("timeout", () => outgoing.destroy(new Error("timeout")));
    outgoing.on("error", reject);
    outgoing.end();
  });
}

import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { forgetQuietHosts, goneVerdict } from "./gone-check";

let server: Server;
let asked: { host: string | undefined; url: string | undefined }[];
let answer: { status: number; body: string };

beforeEach(async () => {
  asked = [];
  forgetQuietHosts();
  server = createServer((request, response) => {
    asked.push({ host: request.headers.host, url: request.url });
    response.writeHead(answer.status, { "content-type": "application/json" });
    response.end(answer.body);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  process.env.BACKEND_INTERNAL_URL = `http://127.0.0.1:${port}`;
});

afterEach(async () => {
  delete process.env.BACKEND_INTERNAL_URL;
  await new Promise((resolve) => server.close(resolve));
});

describe("goneVerdict (ADR-077)", () => {
  it("asks the backend under the visitor's host and reads its verdict", async () => {
    answer = {
      status: 200,
      body: JSON.stringify({
        rules: true,
        gone: true,
        locale: "ru",
        home_path: "/ru/",
      }),
    };
    expect(await goneVerdict("stary.example.test", "/ru/породы/")).toEqual({
      gone: true,
      locale: "ru",
      homePath: "/ru/",
    });
    expect(asked).toEqual([
      {
        host: "stary.example.test",
        url: `/api/v1/public/site/gone/?path=${encodeURIComponent("/ru/породы/")}`,
      },
    ]);
  });

  it("does not ask a host without such addresses again for a minute", async () => {
    answer = {
      status: 200,
      body: JSON.stringify({ rules: false, gone: false }),
    };
    const at = 1_000_000;
    expect(await goneVerdict("firma.example.test", "/a", at)).toEqual({
      gone: false,
    });
    await goneVerdict("firma.example.test", "/b", at + 59_000);
    expect(asked).toHaveLength(1);
    await goneVerdict("firma.example.test", "/c", at + 61_000);
    // Another host is asked on its own account.
    await goneVerdict("inna.example.test", "/a", at);
    expect(asked).toHaveLength(3);
  });

  it("keeps asking a host that has them", async () => {
    answer = {
      status: 200,
      body: JSON.stringify({ rules: true, gone: false }),
    };
    await goneVerdict("stary.example.test", "/a");
    await goneVerdict("stary.example.test", "/b");
    expect(asked).toHaveLength(2);
  });

  it("is no verdict when the backend does not answer one", async () => {
    answer = { status: 500, body: "boom" };
    expect(await goneVerdict("stary.example.test", "/a")).toEqual({
      gone: false,
    });
    // And a failure silences nobody.
    await goneVerdict("stary.example.test", "/a");
    expect(asked).toHaveLength(2);
  });
});

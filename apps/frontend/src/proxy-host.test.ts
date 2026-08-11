import { describe, expect, it } from "vitest";

import { normalizeRequestHostname } from "./proxy-host";

describe("normalizeRequestHostname", () => {
  it.each([
    ["127.0.0.1:8080", "127.0.0.1"],
    ["LOCALHOST.", "localhost"],
    ["Tenant.Example.Test:8443", "tenant.example.test"],
    ["[::1]:8080", "[::1]"],
  ])("normalizuje %s", (authority, expected) => {
    expect(normalizeRequestHostname(authority)).toBe(expected);
  });

  it.each([null, "", "example.test/path", "example.test@evil.test"])(
    "odrzuca %s",
    (authority) => {
      expect(normalizeRequestHostname(authority)).toBe("");
    },
  );
});

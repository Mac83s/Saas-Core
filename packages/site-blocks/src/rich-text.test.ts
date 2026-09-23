import { describe, expect, it } from "vitest";

import { blockAssetIds, richTextAnchorSlug, setAtPath } from "./rich-text";
import type { JsonObject } from "./types";

describe("rich text helpers", () => {
  it("slugifies Polish headings into stable, unique anchors", () => {
    expect(richTextAnchorSlug("Źródła i łąki — przegląd")).toBe(
      "zrodla-i-laki-przeglad",
    );
    expect(richTextAnchorSlug("2024: plan", new Set())).toBe("plan");
    expect(richTextAnchorSlug("!!!")).toBe("section");
    expect(richTextAnchorSlug("Plan", new Set(["plan", "plan-2"]))).toBe(
      "plan-3",
    );
    expect(richTextAnchorSlug("x".repeat(200)).length).toBeLessThanOrEqual(56);
  });

  it("finds every nested asset id once, in order", () => {
    const data = {
      image: { asset_id: "a", alt: "x" },
      content: [
        { type: "figure", image: { asset_id: "b", alt: "y" } },
        { type: "figure", image: { asset_id: "a", alt: "z" } },
      ],
      images: [{ asset_id: "c", alt: "w" }],
    };
    expect(blockAssetIds(data)).toEqual(["a", "b", "c"]);
    expect(blockAssetIds(undefined)).toEqual([]);
  });

  it("sets values only under existing parents and within array bounds", () => {
    const data: JsonObject = { images: [], content: [{ type: "figure" }] };
    setAtPath(data, ["images", 0], { asset_id: "a", alt: "x" });
    setAtPath(data, ["content", 0, "image"], { asset_id: "b", alt: "y" });
    expect(data).toEqual({
      images: [{ asset_id: "a", alt: "x" }],
      content: [{ type: "figure", image: { asset_id: "b", alt: "y" } }],
    });
    expect(() => setAtPath(data, ["images", 5], "x")).toThrow();
    expect(() => setAtPath(data, ["missing", "image"], "x")).toThrow();
    expect(() => setAtPath(data, [], "x")).toThrow();
  });
});

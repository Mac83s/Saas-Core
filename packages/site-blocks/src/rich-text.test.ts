import { describe, expect, it } from "vitest";

import {
  blockAssetIds,
  richTextAnchorSlug,
  setAtPath,
  unfilledPlaceholders,
} from "./rich-text";
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

describe("unfilled placeholders", () => {
  it("finds every marker with its block and exact path", () => {
    const blocks: { data: JsonObject }[] = [
      { data: { title: "Gotowe" } },
      {
        data: {
          content: [
            {
              type: "quote",
              content: [{ text: "[Uzupełnij: prawdziwa opinia klienta]" }],
            },
          ],
          lead: "Mamy [Fill in: number] clients and [Fill in: years] years.",
        },
      },
    ];
    expect(unfilledPlaceholders(blocks)).toEqual([
      {
        blockIndex: 1,
        path: ["content", "0", "content", "0", "text"],
        text: "[Uzupełnij: prawdziwa opinia klienta]",
      },
      { blockIndex: 1, path: ["lead"], text: "[Fill in: number]" },
      { blockIndex: 1, path: ["lead"], text: "[Fill in: years]" },
    ]);
    expect(
      unfilledPlaceholders([{ data: { text: "[x] zwykły nawias" } }]),
    ).toEqual([]);
  });
});

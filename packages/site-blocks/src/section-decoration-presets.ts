import catalog from "@saas-core/contracts/site-blocks/section-decoration-presets.v1.json";
import type { SectionDecorationV1 } from "./types";

export type SectionDecorationPreset = {
  id: string;
  labels: Record<"pl" | "en", { name: string; description: string }>;
  decoration: SectionDecorationV1;
  guidance: {
    contentMotion: boolean;
    recommendedWith: readonly string[];
    avoid: string;
  };
};

export const sectionDecorationPresets =
  catalog.presets as readonly SectionDecorationPreset[];

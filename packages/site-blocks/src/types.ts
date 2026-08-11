import type { ComponentType, ReactElement } from "react";

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };

export interface SiteBlock<TData extends JsonObject = JsonObject> {
  readonly block_type: string;
  readonly schema_version: number;
  readonly data: TData;
}

export type HeroV1Data = JsonObject & {
  heading: string;
  body?: string;
  ctaLabel?: string;
  ctaHref?: string;
};

export type HeroV2Data = JsonObject & {
  title: string;
  text?: string;
  action?: {
    label: string;
    href: string;
  };
};

export type RichTextV1Data = JsonObject & {
  text: string;
};

export type DesignTokensV1 = JsonObject & {
  schemaVersion: 1;
  palette: "neutral" | "blue" | "emerald";
  typography: "sans" | "serif";
  radius: "none" | "small" | "medium" | "large";
  spacing: "compact" | "comfortable" | "spacious";
};

export type BlockMigrator = (data: Readonly<JsonObject>) => JsonObject;

export interface BlockSchemaVersion {
  readonly version: number;
  readonly schema: object;
}

export interface BlockDefinition {
  readonly type: string;
  readonly latestVersion: number;
  readonly schemas: readonly BlockSchemaVersion[];
  readonly migrators: Readonly<Record<number, BlockMigrator>>;
  readonly component: ComponentType<{ data: JsonObject }>;
}

export interface SiteBlockManifest {
  readonly moduleId: string;
  readonly namespace: string;
  readonly blocks: readonly BlockDefinition[];
}

export interface DraftPreviewDocument {
  readonly kind: "draft-preview";
  readonly versionId: string;
  readonly blocks: readonly SiteBlock[];
  readonly designTokens: DesignTokensV1;
}

export interface PublishedPageDocument {
  readonly kind: "publication";
  readonly publicationId: string;
  readonly snapshotHash: string;
  readonly blocks: readonly SiteBlock[];
  readonly designTokens: DesignTokensV1;
}

export interface BlockRegistry {
  readonly definitions: ReadonlyMap<string, BlockDefinition>;
  validate(block: SiteBlock): void;
  migrate(block: SiteBlock): SiteBlock;
  render(block: SiteBlock, key: string): ReactElement;
}

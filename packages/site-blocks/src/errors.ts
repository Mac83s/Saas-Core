export class SiteBlockError extends Error {}

export class UnknownBlockTypeError extends SiteBlockError {
  constructor(blockType: string) {
    super(`Nieznany typ bloku: ${blockType}`);
    this.name = "UnknownBlockTypeError";
  }
}

export class UnknownBlockVersionError extends SiteBlockError {
  constructor(blockType: string, version: number) {
    super(`Nieobsługiwana wersja bloku ${blockType}: ${version}`);
    this.name = "UnknownBlockVersionError";
  }
}

/** One schema violation, addressed to the field it belongs to. `path` is the
 *  JSON Pointer segments of the offending property — `["action", "href"]` for
 *  `/action/href` — so a form can attach the message to its own field instead
 *  of showing one opaque error for the whole block. */
export interface BlockValidationIssue {
  readonly path: readonly string[];
  readonly message: string;
  readonly keyword: string;
}

export class InvalidBlockDataError extends SiteBlockError {
  readonly details: readonly string[];
  readonly issues: readonly BlockValidationIssue[];

  constructor(
    blockType: string,
    version: number,
    details: readonly string[],
    issues: readonly BlockValidationIssue[] = [],
  ) {
    super(`Dane bloku ${blockType} v${version} są nieprawidłowe.`);
    this.name = "InvalidBlockDataError";
    this.details = details;
    this.issues = issues;
  }
}

export class InvalidBlockManifestError extends SiteBlockError {
  constructor(message: string) {
    super(message);
    this.name = "InvalidBlockManifestError";
  }
}

export class InvalidDesignTokensError extends SiteBlockError {
  readonly details: readonly string[];

  constructor(details: readonly string[]) {
    super("Design tokens są nieprawidłowe.");
    this.name = "InvalidDesignTokensError";
    this.details = details;
  }
}

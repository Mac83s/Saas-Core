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

export class InvalidBlockDataError extends SiteBlockError {
  readonly details: readonly string[];

  constructor(blockType: string, version: number, details: readonly string[]) {
    super(`Dane bloku ${blockType} v${version} są nieprawidłowe.`);
    this.name = "InvalidBlockDataError";
    this.details = details;
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

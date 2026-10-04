/**
 * For tests of screens that offer AI translation. The repository's own
 * generated deployment is its first profile, which may compose no translation
 * engine — and a screen asks nothing where there is none. A test that wants
 * the engine says so:
 *
 *   vi.mock("../../../generated/deployment", async (original) =>
 *     (await import("../translation/testing")).withTranslationEngine(original),
 *   );
 */
type Generated = typeof import("../../../generated/deployment");

export async function withTranslationEngine(
  original: () => Promise<unknown>,
): Promise<Generated> {
  const generated = (await original()) as Generated;
  return {
    ...generated,
    deployment: {
      ...generated.deployment,
      modules: [
        ...new Set([...generated.deployment.modules, "shared.translation"]),
      ],
    } as unknown as Generated["deployment"],
  };
}

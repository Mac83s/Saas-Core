import {
  compileOldAddresses,
  type CompiledOldAddresses,
} from "#lib/product-site";
import { oldAddresses } from "../product/old-addresses";
import { RESERVED_SEGMENTS } from "../proxy-segments";
import { productSite } from "./site";

/**
 * The product's old-address rules, compiled against its table (ADR-080) —
 * `null` where there are none to answer: no table served here, no rule
 * declared, or rules that cannot be served as written (caught by
 * `product-site/table.test.ts` in the product's gate; here a broken list
 * only switches the rules off instead of taking every page down).
 *
 * A module of its own: the proxy and the sitemap read it, a page's bundle
 * never does.
 */
function compile(): {
  rules: CompiledOldAddresses | null;
  problem: Error | null;
} {
  if (!productSite) return { rules: null, problem: null };
  try {
    const rules = compileOldAddresses(
      oldAddresses,
      productSite,
      RESERVED_SEGMENTS,
    );
    return { rules: rules.size ? rules : null, problem: null };
  } catch (error) {
    console.error(error);
    return { rules: null, problem: error as Error };
  }
}

export const {
  rules: productOldAddresses,
  problem: productOldAddressesProblem,
} = compile();

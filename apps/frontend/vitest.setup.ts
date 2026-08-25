import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without this, a second test in the same file queries a DOM that still holds
// the first render and every `getByRole` finds two matches. Files that already
// call `cleanup` in their own `afterEach` are unaffected — it is idempotent.
afterEach(cleanup);

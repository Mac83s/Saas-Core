import { renderHook } from "@testing-library/react";
import { expect, test } from "vitest";

import { useShown } from "./use-shown";

test("a closing dialog keeps what it showed, and the next opening shows the new", () => {
  const first = { number: 2 };
  const hook = renderHook(
    ({ value }: { value: { number: number } | null }) => useShown(value),
    { initialProps: { value: null as { number: number } | null } },
  );
  expect(hook.result.current).toBeNull();

  hook.rerender({ value: first });
  expect(hook.result.current).toBe(first);

  // Closed: the state is empty, the dialog still reads „Wersja 2”.
  hook.rerender({ value: null });
  expect(hook.result.current).toBe(first);

  const second = { number: 5 };
  hook.rerender({ value: second });
  expect(hook.result.current).toBe(second);
});

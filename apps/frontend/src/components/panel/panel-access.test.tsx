import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test } from "vitest";

import type { PanelAccess } from "#lib/panel-navigation";
import { PanelAccessProvider, useAsksModule } from "./panel-access";

const access: PanelAccess = {
  modules: ["core.organizations", "shared.sites"],
  permissions: [],
  isOwner: true,
  limited: false,
};

const asks = (module: string, value?: PanelAccess) =>
  renderHook(() => useAsksModule(module), {
    wrapper: value
      ? ({ children }: { children: ReactNode }) => (
          <PanelAccessProvider access={value}>{children}</PanelAccessProvider>
        )
      : undefined,
  }).result.current;

test("a platform workspace is asked only about the modules it is offered", () => {
  const publisher: PanelAccess = { ...access, publisher: true };
  expect(asks("shared.sites", publisher)).toBe(true);
  expect(asks("shared.booking", publisher)).toBe(false);
  expect(asks("shared.image-generation", publisher)).toBe(false);
});

test("a company is asked as before, whatever its type composes; so is a screen outside the panel", () => {
  expect(asks("shared.sites", access)).toBe(true);
  expect(asks("shared.booking", access)).toBe(true);
  expect(asks("shared.booking")).toBe(true);
});

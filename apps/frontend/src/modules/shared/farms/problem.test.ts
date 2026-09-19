import { expect, test } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";

import { farmProblem } from "./problem";

const problem = (detail: unknown) =>
  new ApiProblemError({
    type: "about:blank",
    title: "Błąd",
    status: 400,
    detail,
  } as ConstructorParameters<typeof ApiProblemError>[0]);

test("pokazuje pierwsze zdanie błędu walidacji albo tekst zapasowy", () => {
  expect(farmProblem(problem("Nie ma takiego gospodarstwa."), "x")).toBe(
    "Nie ma takiego gospodarstwa.",
  );
  expect(
    farmProblem(problem({ herd_number: ["Numer ma postać PL…"] }), "x"),
  ).toBe("Numer ma postać PL…");
  expect(farmProblem(new Error("sieć"), "Zapasowy")).toBe("Zapasowy");
});

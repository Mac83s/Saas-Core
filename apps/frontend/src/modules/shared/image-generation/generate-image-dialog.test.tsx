import axe from "axe-core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { GenerateImageDialog } from "./generate-image-dialog";

const { getImageGenerationJob, requestImageGeneration } = vi.hoisted(() => ({
  getImageGenerationJob: vi.fn(),
  requestImageGeneration: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getImageGenerationJob,
  requestImageGeneration,
  getMediaAssetPreview: vi
    .fn()
    .mockRejectedValue(new Error("Unavailable fixture preview")),
}));

const JOB_ID = "019ff20d-a000-7000-8000-0000000000a1";
const ASSET_ID = "019ff20d-a000-7000-8000-0000000000a2";
const PROMPT = "Jasna sala zabiegowa bez ludzi";

function job(state: string, extra: object = {}) {
  return {
    id: JOB_ID,
    state,
    aspect: "16:9",
    width: 1536,
    height: 864,
    media_asset_id: null,
    error_code: "",
    created_at: "2026-09-24T12:00:00Z",
    finished_at: null,
    ...extra,
  };
}

function problem(status: number, code: string) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status,
    code,
    detail: "fixture",
    correlation_id: null,
  });
}

function renderDialog(
  locale: "pl" | "en" = "pl",
  onUse: (assetId: string) => void = vi.fn(),
) {
  const messages = locale === "pl" ? polishMessages : englishMessages;
  const result = render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      <GenerateImageDialog aspect="16:9" creditCost={2} onUse={onUse} />
    </NextIntlClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: messages.ImageGeneration.open }),
  );
  return { ...result, messages: messages.ImageGeneration };
}

function submit(messages: typeof polishMessages.ImageGeneration) {
  fireEvent.change(screen.getByLabelText(messages.prompt), {
    target: { value: PROMPT },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: messages.generate.replace("{cost}", "2"),
    }),
  );
}

let uuid: { mockRestore: () => void } | undefined;

beforeEach(() => {
  vi.clearAllMocks();
  uuid = vi
    .spyOn(globalThis.crypto, "randomUUID")
    .mockReturnValueOnce("0000000a-0000-4000-8000-000000000001")
    .mockReturnValueOnce("0000000a-0000-4000-8000-000000000002");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  uuid?.mockRestore();
});

test.each(["pl", "en"] as const)(
  "%s: shows the cost, the AI marking and the warning, and passes axe",
  async (locale) => {
    const { messages } = renderDialog(locale);
    expect(
      screen.getByText(locale === "pl" ? /2 kredyty/ : /2 credits/),
    ).not.toBeNull();
    expect(screen.getByText(messages.marking)).not.toBeNull();
    expect(screen.getByText(messages.warning)).not.toBeNull();
    const results = await axe.run(document.body);
    expect(results.violations).toEqual([]);
  },
);

test("submits with a fresh Idempotency-Key, polls until ready and uses the image", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const onUse = vi.fn();
  requestImageGeneration.mockResolvedValue(job("queued"));
  getImageGenerationJob
    .mockResolvedValueOnce(job("running"))
    .mockResolvedValueOnce(job("succeeded", { media_asset_id: ASSET_ID }));
  const { messages } = renderDialog("pl", onUse);

  submit(messages);
  await waitFor(() => expect(requestImageGeneration).toHaveBeenCalledOnce());
  expect(requestImageGeneration).toHaveBeenCalledWith(
    { prompt: PROMPT, aspect: "16:9", expected_cost: 2 },
    "0000000a-0000-4000-8000-000000000001",
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4100);
  });
  expect(getImageGenerationJob).toHaveBeenCalledTimes(2);
  const use = await screen.findByRole("button", { name: messages.use });
  // The preview carries the badge the published page will show.
  expect(document.querySelector(".site-ai-badge")?.textContent).toBe("AI");

  fireEvent.click(use);
  expect(onUse).toHaveBeenCalledWith(ASSET_ID);
});

test("generate again sends a new job under a new key", async () => {
  requestImageGeneration.mockResolvedValue(
    job("succeeded", { media_asset_id: ASSET_ID }),
  );
  const { messages } = renderDialog();
  submit(messages);
  const again = await screen.findByRole("button", {
    name: messages.again.replace("{cost}", "2"),
  });
  fireEvent.click(again);
  await waitFor(() => expect(requestImageGeneration).toHaveBeenCalledTimes(2));
  expect(requestImageGeneration.mock.calls[1]?.[1]).toBe(
    "0000000a-0000-4000-8000-000000000002",
  );
});

test.each([
  [402, "credits_exhausted", "creditsExhausted"],
  [409, "credit_price_changed", "priceChanged"],
  [409, "quota_exceeded", "quotaExceeded"],
  [409, "image_generation_conflict", "conflict"],
  [429, "image_generation_busy", "busy"],
  [429, "image_generation_refusal_limit", "refusalLimit"],
  [503, "image_generation_unavailable", "unavailable"],
] as const)("%i %s has its own Polish message", async (status, code, key) => {
  requestImageGeneration.mockRejectedValue(problem(status, code));
  const { messages } = renderDialog();
  submit(messages);
  expect((await screen.findByRole("alert")).textContent).toBe(messages[key]);
});

test("a refused description says so and charges nothing", async () => {
  requestImageGeneration.mockResolvedValue(
    job("refused", { error_code: "moderation_blocked" }),
  );
  const { messages } = renderDialog();
  submit(messages);
  expect((await screen.findByRole("alert")).textContent).toBe(messages.refused);
});

test("polling stops when the dialog goes away", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  requestImageGeneration.mockResolvedValue(job("queued"));
  getImageGenerationJob.mockResolvedValue(job("running"));
  const { messages, unmount } = renderDialog();
  submit(messages);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2100);
  });
  expect(getImageGenerationJob).toHaveBeenCalledOnce();
  const signal = getImageGenerationJob.mock.calls[0]?.[1] as AbortSignal;
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(getImageGenerationJob).toHaveBeenCalledOnce();
});

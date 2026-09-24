"use client";

import { useEffect, useId, useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useLocale, useTranslations } from "next-intl";
import { useForm } from "react-hook-form";
import { SparklesIcon } from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  getImageGenerationJob,
  requestImageGeneration,
  type ImageGenerationJob,
} from "@saas-core/api-client";
import { withAiBadge } from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Textarea } from "@saas-core/ui/components/textarea";

import { PrivateMediaPreview } from "../sites/private-media-preview";

export type GeneratedImageAspect = "16:9" | "4:3" | "3:2";

const POLL_MS = 2000;
const POLL_LIMIT_MS = 3 * 60 * 1000;

/** The codes the API answers with, each with its own sentence (ADR-059). */
const PROBLEM_KEYS: Record<string, string> = {
  credits_exhausted: "creditsExhausted",
  credit_price_changed: "priceChanged",
  quota_exceeded: "quotaExceeded",
  image_generation_conflict: "conflict",
  image_generation_busy: "busy",
  image_generation_refusal_limit: "refusalLimit",
  image_generation_unavailable: "unavailable",
};

/** The slot's aspect as the API names it, when the API generates it at all. */
export function generatedAspect(
  aspect: readonly [number, number] | undefined,
  offered: readonly string[],
): GeneratedImageAspect | undefined {
  const key = aspect ? `${aspect[0]}:${aspect[1]}` : "";
  return offered.includes(key) ? (key as GeneratedImageAspect) : undefined;
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

/**
 * „Wygeneruj obraz AI” przy polu obrazu: opis → zlecenie → gotowy obraz.
 *
 * Obraz ma już proporcję miejsca, więc nie przechodzi przez kadrowanie. Każde
 * wysłanie to nowy klucz idempotencji; ponowienie tego samego żądania po
 * zerwanym połączeniu nie zdarza się tu, bo formularz blokuje się na czas pracy.
 */
export function GenerateImageDialog({
  aspect,
  creditCost,
  onUse,
}: {
  aspect: GeneratedImageAspect;
  creditCost: number;
  onUse: (assetId: string) => void;
}) {
  const t = useTranslations("ImageGeneration");
  const locale = useLocale() === "en" ? "en" : "pl";
  const id = useId();
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [assetId, setAssetId] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const polling = useRef<AbortController | null>(null);
  const schema = z.object({
    prompt: z
      .string()
      .trim()
      .min(3, t("promptTooShort"))
      .max(1000, t("promptTooLong")),
  });
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { prompt: "" },
  });
  const promptError = form.formState.errors.prompt?.message;

  // Leaving the editor stops the polling; the job itself goes on server-side.
  useEffect(() => () => polling.current?.abort(), []);

  async function generate({ prompt }: { prompt: string }) {
    polling.current?.abort();
    const controller = new AbortController();
    polling.current = controller;
    setWorking(true);
    setProblem(undefined);
    setAssetId(undefined);
    try {
      let job: ImageGenerationJob = await requestImageGeneration(
        { prompt, aspect, expected_cost: creditCost },
        crypto.randomUUID(),
      );
      const deadline = Date.now() + POLL_LIMIT_MS;
      while (!["succeeded", "refused", "failed"].includes(job.state)) {
        if (Date.now() >= deadline) {
          setProblem(t("timeout"));
          return;
        }
        await wait(POLL_MS, controller.signal);
        job = await getImageGenerationJob(job.id, controller.signal);
      }
      if (job.state === "succeeded" && job.media_asset_id) {
        setAssetId(job.media_asset_id);
      } else {
        setProblem(t(job.state === "refused" ? "refused" : "failed"));
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      const code = error instanceof ApiProblemError ? error.problem.code : "";
      setProblem(t(PROBLEM_KEYS[code] ?? "problem"));
    } finally {
      if (!controller.signal.aborted) setWorking(false);
    }
  }

  function close() {
    polling.current?.abort();
    setOpen(false);
    setWorking(false);
    setAssetId(undefined);
    setProblem(undefined);
  }

  return (
    <>
      <Button onClick={() => setOpen(true)} type="button" variant="outline">
        <SparklesIcon aria-hidden="true" />
        {t("open")}
      </Button>
      <Dialog onOpenChange={(next) => !next && close()} open={open}>
        <DialogContent closeLabel={t("close")}>
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>
              {t("description", { aspect, cost: creditCost })}
            </DialogDescription>
          </DialogHeader>
          <form
            aria-busy={working}
            className="grid gap-4"
            noValidate
            onSubmit={(event) => {
              // The dialog renders in a portal, but React still bubbles the
              // submit to the page form around the field.
              event.stopPropagation();
              void form.handleSubmit(generate)(event);
            }}
          >
            <Field data-invalid={Boolean(promptError)}>
              <FieldLabel htmlFor={`${id}-prompt`}>{t("prompt")}</FieldLabel>
              <Textarea
                aria-describedby={`${id}-warning`}
                aria-invalid={Boolean(promptError)}
                disabled={working}
                id={`${id}-prompt`}
                maxLength={1000}
                rows={4}
                {...form.register("prompt")}
              />
              <FieldDescription>{t("marking")}</FieldDescription>
              <FieldError>{promptError}</FieldError>
            </Field>
            <p
              className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
              id={`${id}-warning`}
            >
              {t("warning")}
            </p>
            {working ? (
              <p className="text-sm text-muted-foreground" role="status">
                {t("working")}
              </p>
            ) : null}
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
            {assetId ? (
              <div className="overflow-hidden rounded-lg">
                {withAiBadge(
                  <PrivateMediaPreview
                    alt={t("previewAlt")}
                    assetId={assetId}
                  />,
                  locale,
                )}
              </div>
            ) : null}
            <DialogFooter>
              {assetId ? (
                <>
                  <Button disabled={working} type="submit" variant="outline">
                    {t("again", { cost: creditCost })}
                  </Button>
                  <Button
                    onClick={() => {
                      onUse(assetId);
                      close();
                    }}
                    type="button"
                  >
                    {t("use")}
                  </Button>
                </>
              ) : (
                <Button disabled={working} type="submit">
                  {t("generate", { cost: creditCost })}
                </Button>
              )}
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

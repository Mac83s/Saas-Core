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
  getImageGenerationOffer,
  requestImageGeneration,
  type ImageGenerationAspect,
  type ImageGenerationJob,
  type ImageGenerationOffer,
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

import { mutationKey, type MutationReceipt } from "../sites/idempotency";
import { PrivateMediaPreview } from "../sites/private-media-preview";

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
  offered: readonly ImageGenerationAspect[],
): ImageGenerationAspect | undefined {
  const key = aspect ? `${aspect[0]}:${aspect[1]}` : "";
  return offered.find((item) => item === key);
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
 * Obraz ma już proporcję miejsca, więc nie przechodzi przez kadrowanie. Klucz
 * idempotencji trwa, dopóki wynik wysłania jest nieznany: ponowienie po
 * zerwanej odpowiedzi trafia w to samo zlecenie, a nie płaci drugi raz. Nowy
 * klucz dostaje dopiero wysłanie po otrzymanym zleceniu albo zmieniony opis.
 */
export function GenerateImageDialog({
  aspect,
  offer,
  onUse,
}: {
  aspect: ImageGenerationAspect;
  offer: ImageGenerationOffer;
  onUse: (assetId: string) => void;
}) {
  const t = useTranslations("ImageGeneration");
  const locale = useLocale() === "en" ? "en" : "pl";
  const id = useId();
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [assetId, setAssetId] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [status, setStatus] = useState("");
  // The editor reads the offer once; a price change re-reads it here.
  const [creditCost, setCreditCost] = useState(offer.credit_cost);
  const polling = useRef<AbortController | null>(null);
  const receipt = useRef<MutationReceipt | undefined>(undefined);
  const useButton = useRef<HTMLButtonElement>(null);
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
  // A finished image moves focus to the action that uses it.
  useEffect(() => {
    if (assetId) useButton.current?.focus();
  }, [assetId]);

  async function generate({ prompt }: { prompt: string }) {
    polling.current?.abort();
    const controller = new AbortController();
    polling.current = controller;
    setWorking(true);
    setProblem(undefined);
    setAssetId(undefined);
    setStatus(t("working"));
    const input = { prompt, aspect, expected_cost: creditCost };
    let job: ImageGenerationJob;
    try {
      job = await requestImageGeneration(
        input,
        mutationKey(receipt, "image-generation", input),
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      setStatus("");
      setWorking(false);
      const code = error instanceof ApiProblemError ? error.problem.code : "";
      if (code === "credit_price_changed") {
        await refreshPrice();
        return;
      }
      setProblem(t(PROBLEM_KEYS[code] ?? "problem"));
      return;
    }
    // The job exists and will be charged if it succeeds: from here on a
    // failed read is a blip to wait out, never "request failed, try again".
    receipt.current = undefined;
    const deadline = Date.now() + POLL_LIMIT_MS;
    try {
      while (!["succeeded", "refused", "failed"].includes(job.state)) {
        if (Date.now() >= deadline) {
          setStatus(t("timeout"));
          return;
        }
        await wait(POLL_MS, controller.signal);
        job = await getImageGenerationJob(job.id, controller.signal).catch(
          (error: unknown) => {
            if (controller.signal.aborted) throw error;
            return job;
          },
        );
      }
      if (job.state === "succeeded" && job.media_asset_id) {
        setAssetId(job.media_asset_id);
        setStatus(t("ready"));
      } else {
        setStatus("");
        setProblem(t(job.state === "refused" ? "refused" : "failed"));
      }
    } catch {
      // Only an abort gets here: the dialog closed or the editor left.
    } finally {
      if (!controller.signal.aborted) setWorking(false);
    }
  }

  async function refreshPrice() {
    try {
      const fresh = await getImageGenerationOffer();
      setCreditCost(fresh.credit_cost);
      setProblem(t("priceChanged"));
    } catch {
      setProblem(t("priceChangedReload"));
    }
  }

  function close() {
    polling.current?.abort();
    setOpen(false);
    setWorking(false);
    setAssetId(undefined);
    setProblem(undefined);
    setStatus("");
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
              <FieldDescription>
                {t(offer.badge_visible ? "marking" : "markingFileOnly")}
              </FieldDescription>
              <FieldError>{promptError}</FieldError>
            </Field>
            <p
              className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
              id={`${id}-warning`}
            >
              {t("warning")}
            </p>
            {/* Always mounted, so a screen reader hears each change in it. */}
            <p className="text-sm text-muted-foreground" role="status">
              {status}
            </p>
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
            {assetId ? (
              <div className="overflow-hidden rounded-lg">
                {/* The badge only where the published page will show one. */}
                {offer.badge_visible ? (
                  withAiBadge(
                    <PrivateMediaPreview
                      alt={t("previewAlt")}
                      assetId={assetId}
                    />,
                    locale,
                  )
                ) : (
                  <PrivateMediaPreview
                    alt={t("previewAlt")}
                    assetId={assetId}
                  />
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
                    ref={useButton}
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

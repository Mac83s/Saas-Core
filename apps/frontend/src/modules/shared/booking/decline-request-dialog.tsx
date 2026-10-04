"use client";

import { useRef, useState, type ReactElement, type RefObject } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  answerBookingRequest,
  type BookingAppointment,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Textarea } from "@saas-core/ui/components/textarea";

import { visitName } from "./visit-name";

/** As the API bounds the company's words to a customer it declines. */
const REASON_MAX_LENGTH = 300;

/**
 * „Odmówić tej rezerwacji?” (ADR-072 §9): the company declines a customer's
 * request and may say why in its own words — plain text without a link, sent
 * in the customer's e-mail and kept nowhere else. Used from the visit's
 * window and from the list of requests.
 */
export function DeclineRequestDialog({
  appointment,
  onDeclined,
  onOpenChange,
  open,
  returnFocus,
  trigger,
  when,
}: {
  appointment: Pick<BookingAppointment, "id" | "title" | "customer_name">;
  /** After the dialog is gone: the report may remove whatever opened it. */
  onDeclined: (appointment: BookingAppointment) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  /** Where focus goes once the request — and the button that opened this — is gone. */
  returnFocus?: RefObject<HTMLElement | null>;
  /** The button that opens the dialog, when the dialog owns it. */
  trigger?: ReactElement;
  /** The visit's time, as its opener writes it. */
  when: string;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [declined, setDeclined] = useState<BookingAppointment>();
  // One key per answer: a double click or a retry declines once. Other
  // words are another answer.
  const sent = useRef<{ key: string; reason: string }>(undefined);

  async function decline() {
    setBusy(true);
    setProblem(undefined);
    const words = reason.trim();
    if (sent.current?.reason !== words)
      sent.current = { key: crypto.randomUUID(), reason: words };
    try {
      setDeclined(
        await answerBookingRequest(
          appointment.id,
          "decline",
          sent.current.key,
          words,
        ),
      );
      onOpenChange(false);
    } catch (error) {
      const refused =
        error instanceof ApiProblemError ? error.problem : undefined;
      setProblem(
        refused?.errors?.[0]?.code === "links"
          ? t("declineReasonLinks")
          : refused?.code === "appointment_not_changeable"
            ? t("notChangeable")
            : t("answerError"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        setProblem(undefined);
        onOpenChange(next);
      }}
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen && declined) onDeclined(declined);
      }}
      open={open}
    >
      {trigger ? (
        <DialogTrigger render={trigger}>{t("declineRequest")}</DialogTrigger>
      ) : null}
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() =>
          declined && returnFocus ? returnFocus.current : true
        }
      >
        <DialogHeader>
          <DialogTitle>{t("declineTitle")}</DialogTitle>
          <DialogDescription>
            {visitName(appointment)} · {when}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">{t("declineText")}</p>
        <Field>
          <FieldLabel htmlFor={`decline-reason-${appointment.id}`}>
            {t("declineReason")}
          </FieldLabel>
          <Textarea
            aria-describedby={`decline-reason-hint-${appointment.id}`}
            id={`decline-reason-${appointment.id}`}
            maxLength={REASON_MAX_LENGTH}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            value={reason}
          />
          <FieldDescription id={`decline-reason-hint-${appointment.id}`}>
            {t("declineReasonHint")}
          </FieldDescription>
        </Field>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {t("keep")}
          </DialogClose>
          <Button
            disabled={busy}
            onClick={() => void decline()}
            type="button"
            variant="destructive"
          >
            {t("declineConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

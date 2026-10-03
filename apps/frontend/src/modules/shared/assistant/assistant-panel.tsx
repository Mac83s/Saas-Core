"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { SearchIcon, SendHorizontalIcon } from "lucide-react";

import {
  ApiProblemError,
  answerAssistantConsent,
  getAssistantConversation,
  getAssistantOffer,
  listAssistantConversations,
  sendAssistantMessage,
  startAssistantConversation,
  type AssistantConversation,
  type AssistantOffer,
  type AssistantTurn,
  type AssistantTurnItem,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Textarea } from "@saas-core/ui/components/textarea";

import { PanelPage } from "#components/panel/panel-page";
import { PlanGate } from "#components/panel/plan-gate";
import { ConsentDialog } from "./consent-dialog";

type Locale = "pl" | "en";

const POLL_MS = 1200;
const WORKING = new Set(["queued", "running"]);
const FAILURES = new Set([
  "conversation_budget",
  "budget",
  "refused",
  "unavailable",
  "step_limit",
  "authorization_revoked",
  "timeout",
]);
const STATUS_TONE = {
  done: "success",
  pending: "warning",
  refused: "neutral",
  failed: "neutral",
  skipped: "neutral",
  declined: "neutral",
} as const;

/**
 * The assistant's chat (ADR-076, A3): the person writes, the assistant reads
 * and proposes, and a change runs only after the person's click in the
 * consent dialog. A message is answered later, so the conversation is read
 * again until its last turn settles.
 */
export function AssistantPanel({
  canManageBilling = false,
}: {
  /** The owner may change the plan; everybody else asks them. */
  canManageBilling?: boolean;
}) {
  const t = useTranslations("Assistant");
  const locale = useLocale() as Locale;
  const [offer, setOffer] = useState<AssistantOffer>();
  const [conversation, setConversation] = useState<AssistantConversation>();
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [consentOpen, setConsentOpen] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const asked = useRef<string>(undefined);

  const last = conversation?.turns.at(-1);
  const working = last ? WORKING.has(last.state) : false;
  const waiting = last?.state === "awaiting_consent" ? last : undefined;

  const refresh = useCallback(async (id: string, signal?: AbortSignal) => {
    setConversation(await getAssistantConversation(id, signal));
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getAssistantOffer(), listAssistantConversations(1)])
      .then(async ([nextOffer, [latest]]) => {
        if (cancelled) return;
        setOffer(nextOffer);
        if (latest) await refresh(latest.id);
      })
      .catch(() => {
        if (!cancelled) setProblem(t("loadError"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refresh, t]);

  // An answer arrives later: read again while the last turn is in progress.
  useEffect(() => {
    if (!conversation || !working) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      refresh(conversation.id, controller.signal).catch(() => undefined);
    }, POLL_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [conversation, working, refresh]);

  // A plan that starts waiting is shown at once, once.
  useEffect(() => {
    if (waiting && asked.current !== waiting.id) {
      asked.current = waiting.id;
      setConsentOpen(true);
    }
  }, [waiting]);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [conversation]);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || sending || working || waiting) return;
    setSending(true);
    setProblem(undefined);
    try {
      const current =
        conversation ??
        (await startAssistantConversation(locale, crypto.randomUUID()));
      await sendAssistantMessage(current.id, message, crypto.randomUUID());
      setText("");
      await refresh(current.id);
    } catch (error) {
      setProblem(sendProblem(error, t));
      getAssistantOffer()
        .then(setOffer)
        .catch(() => undefined);
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void send();
    }
  }

  const reload = useCallback(async () => {
    if (conversation) await refresh(conversation.id);
  }, [conversation, refresh]);

  const closed = offer ? !offer.available : false;
  const outsidePlan = offer ? !offer.in_plan : false;

  return (
    <PanelPage
      actions={
        conversation?.turns.length && !working && !waiting ? (
          <Button
            onClick={() => {
              setConversation(undefined);
              setProblem(undefined);
            }}
            type="button"
            variant="outline"
          >
            {t("newConversation")}
          </Button>
        ) : undefined
      }
      description={t("description")}
      form
      title={t("title")}
    >
      {loading ? null : outsidePlan ? (
        <PlanGate
          action={
            canManageBilling
              ? {
                  href: "/panel/settings/billing?feature=assistant.text.enabled",
                  label: t("planGateAction"),
                }
              : undefined
          }
          title={t("planGateTitle")}
        >
          {t(canManageBilling ? "planGateOwner" : "planGateMember")}
        </PlanGate>
      ) : (
        <div className="space-y-6">
          <div aria-live="polite" className="space-y-6" role="log">
            {conversation?.turns.length ? (
              conversation.turns.map((turn) => (
                <Turn
                  key={turn.id}
                  locale={locale}
                  onDecide={() => setConsentOpen(true)}
                  turn={turn}
                />
              ))
            ) : (
              <div className="space-y-2 text-sm text-muted-foreground">
                <p>{t("emptyLead")}</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li>{t("example1")}</li>
                  <li>{t("example2")}</li>
                  <li>{t("example3")}</li>
                </ul>
              </div>
            )}
          </div>
          {working ? (
            <p className="text-sm text-muted-foreground" role="status">
              {t("writing")}
            </p>
          ) : null}
          <div ref={end} />
          <form
            className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] space-y-2 border-t bg-background pt-3 pb-2 lg:bottom-0"
            onSubmit={(event) => void send(event)}
          >
            {closed ? (
              <p className="text-sm text-muted-foreground" role="status">
                {t("closed")}
              </p>
            ) : null}
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
            <div className="flex items-end gap-2">
              <Textarea
                aria-label={t("composerLabel")}
                className="max-h-48 min-h-11 flex-1 text-base md:text-base"
                disabled={closed || sending}
                maxLength={offer?.max_message_characters}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder={
                  waiting ? t("composerWaiting") : t("composerPlaceholder")
                }
                rows={1}
                value={text}
              />
              <Button
                aria-label={t("send")}
                disabled={
                  closed ||
                  sending ||
                  working ||
                  Boolean(waiting) ||
                  !text.trim()
                }
                size="icon"
                type="submit"
              >
                <SendHorizontalIcon aria-hidden="true" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t("notice", { credits: offer?.credits_per_message ?? 0 })}
              <span className="hidden lg:inline"> {t("enterHint")}</span>
            </p>
          </form>
        </div>
      )}
      {conversation && waiting ? (
        <ConsentDialog
          groups={waiting.consents}
          onAnswer={async (answer) => {
            await answerAssistantConsent(conversation.id, waiting.id, answer);
            await reload();
          }}
          onOpenChange={setConsentOpen}
          onStale={reload}
          open={consentOpen}
        />
      ) : null}
    </PanelPage>
  );
}

function Turn({
  turn,
  locale,
  onDecide,
}: {
  turn: AssistantTurn;
  locale: Locale;
  onDecide: () => void;
}) {
  const t = useTranslations("Assistant");
  return (
    <div className="space-y-3">
      <p className="ml-auto w-fit max-w-[85%] rounded-2xl bg-muted px-4 py-2 text-sm whitespace-pre-wrap">
        <span className="sr-only">{t("you")}: </span>
        {turn.text}
      </p>
      <div className="space-y-2">
        <span className="sr-only">{t("assistant")}: </span>
        {turn.items.map((item, index) =>
          item.kind === "text" ? (
            <p className="text-sm whitespace-pre-wrap" key={index}>
              {item.text}
            </p>
          ) : (
            <Action item={item} key={item.step_id ?? index} locale={locale} />
          ),
        )}
        {turn.state === "awaiting_consent" ? (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
            <p className="min-w-0 flex-1 basis-48">{t("awaiting")}</p>
            <Button onClick={onDecide} type="button">
              {t("decide")}
            </Button>
          </div>
        ) : null}
        {turn.state === "failed" ? (
          <p className="text-sm text-destructive" role="alert">
            {t(
              `failure_${FAILURES.has(turn.failure_code) ? turn.failure_code : "unavailable"}`,
            )}
          </p>
        ) : null}
      </div>
    </div>
  );
}

/** One step: what it is called for a person, and how it ended. */
function Action({ item, locale }: { item: AssistantTurnItem; locale: Locale }) {
  const t = useTranslations("Assistant");
  const status = item.status ?? "pending";
  const title = item.title?.[locale] ?? "";
  if (item.risk === "read" && status === "done") {
    // A read is a quiet step: the same title a change shows, without a badge.
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <SearchIcon aria-hidden="true" className="size-3.5 shrink-0" />
        <span>{title}</span>
      </p>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant={STATUS_TONE[status]}>{t(`status_${status}`)}</Badge>
      <span>{title}</span>
    </p>
  );
}

function sendProblem(
  error: unknown,
  t: ReturnType<typeof useTranslations>,
): string {
  if (error instanceof ApiProblemError) {
    const code = error.problem.code;
    if (code === "assistant_rate_limited") return t("limited");
    if (code === "assistant_turn_in_progress") return t("inProgress");
    if (code === "credits_exhausted") return t("noCredits");
    if (code === "assistant_unavailable") return t("closed");
  }
  return t("sendError");
}

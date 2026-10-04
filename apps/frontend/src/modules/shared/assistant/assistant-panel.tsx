"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { CopyIcon, SearchIcon, SendHorizontalIcon } from "lucide-react";

import {
  ApiProblemError,
  answerAssistantConsent,
  getAssistantConversation,
  getAssistantOffer,
  listAssistantConversations,
  sendAssistantMessage,
  startAssistantConversation,
  type AssistantConversation,
  type AssistantConversationKind,
  type AssistantOffer,
  type AssistantTurn,
  type AssistantTurnItem,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Textarea } from "@saas-core/ui/components/textarea";

import { PanelPage } from "#components/panel/panel-page";
import { PlanGate } from "#components/panel/plan-gate";
import { Link } from "#i18n/navigation";
import { useMedia } from "#lib/use-media";
import { ConsentDialog } from "./consent-dialog";
import { SetupProfile } from "./setup-profile";

type Locale = "pl" | "en";
type Person = NonNullable<AssistantTurnItem["people"]>[number];

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
 *
 * A `setup` conversation sets the company up: it is free, and the notes the
 * assistant keeps about the company are shown with it — beside the
 * conversation on a wide screen, under it and closed on a narrow one.
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
  // Counts the reads that found the last turn settled: the notes beside a
  // setup conversation are read again with each.
  const [settled, setSettled] = useState(0);
  const end = useRef<HTMLDivElement>(null);
  const asked = useRef<string>(undefined);
  // From 1280 px the page has a column beside the conversation. The first
  // render does not know the width yet and takes the narrow layout.
  const wide = useMedia("(min-width: 1280px)");

  const last = conversation?.turns.at(-1);
  const working = last ? WORKING.has(last.state) : false;
  const waiting = last?.state === "awaiting_consent" ? last : undefined;
  // A conversation without a turn is the empty state, whatever its kind.
  const shown = last ? conversation : undefined;
  const setup = shown?.kind === "setup";

  const refresh = useCallback(async (id: string, signal?: AbortSignal) => {
    const next = await getAssistantConversation(id, signal);
    setConversation(next);
    if (!WORKING.has(next.turns.at(-1)?.state ?? "")) {
      setSettled((count) => count + 1);
    }
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

  /**
   * Sends a message to the conversation shown; with none shown it goes to a
   * new one of `kind`. An empty conversation of the other kind is left behind:
   * the free setup message must not land in a conversation that costs credits.
   */
  async function deliver(
    message: string,
    kind: AssistantConversationKind,
    typed: boolean,
  ) {
    if (!message || sending || working || waiting) return;
    setSending(true);
    setProblem(undefined);
    try {
      const open =
        shown ?? (conversation?.kind === kind ? conversation : undefined);
      const current =
        open ??
        (await startAssistantConversation(locale, crypto.randomUUID(), kind));
      await sendAssistantMessage(current.id, message, crypto.randomUUID());
      if (typed) setText("");
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

  async function send(event?: FormEvent) {
    event?.preventDefault();
    await deliver(text.trim(), "operate", true);
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
  const setupSpent = offer
    ? offer.setup.turns_left <= 0 || offer.setup.turns_left_today <= 0
    : false;

  // One block, in one of two places: never both, so it reads the notes once.
  const notes =
    shown && setup ? (
      <SetupProfile
        beside={wide}
        conversationId={shown.id}
        revision={settled}
      />
    ) : undefined;

  return (
    <PanelPage
      actions={
        shown && !working && !waiting ? (
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
      aside={wide ? notes : undefined}
      asideLabel={t("profileTitle")}
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
          {setup ? (
            <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <Badge variant="info">{t("setupBadge")}</Badge>
              <span>{t("setupFree")}</span>
            </p>
          ) : null}
          {!shown && offer?.setup.allowed ? (
            <section className="space-y-3 rounded-lg border p-4">
              <h2 className="font-medium">{t("setupCardTitle")}</h2>
              <p className="text-sm text-muted-foreground">
                {t("setupCardText")}
              </p>
              {setupSpent ? (
                // Nothing to press: the sentence says where the rest is done.
                <p className="text-sm">{t("setupSpent")}</p>
              ) : (
                <Button
                  disabled={closed || sending}
                  onClick={() =>
                    void deliver(t("setupFirstMessage"), "setup", false)
                  }
                  type="button"
                >
                  {t("setupStart")}
                </Button>
              )}
            </section>
          ) : null}
          <div aria-live="polite" className="space-y-6" role="log">
            {shown ? (
              shown.turns.map((turn) => (
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
          {wide ? null : notes}
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
              {setup
                ? t("noticeSetup")
                : t("notice", { credits: offer?.credits_per_message ?? 0 })}
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
            <Words item={item} key={index} locale={locale} />
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

/**
 * What the assistant wrote. Where it names a person it wrote a handle
 * (`klient:k7m2q`) — the model never has the name, the e-mail or the phone.
 * The server sends a card for each handle of this conversation, read for the
 * signed-in person: the name stands in the handle's place and the card
 * follows the text.
 */
function Words({ item, locale }: { item: AssistantTurnItem; locale: Locale }) {
  const t = useTranslations("Assistant");
  const text = item.text ?? "";
  const people = item.people ?? [];
  if (people.length === 0) {
    return <p className="text-sm whitespace-pre-wrap">{text}</p>;
  }
  const byHandle = new Map(people.map((person) => [person.handle, person]));
  const parts: ReactNode[] = [];
  let rest = text;
  while (rest) {
    // The handle that comes first in what is left of the text.
    let at = -1;
    let found: Person | undefined;
    for (const person of byHandle.values()) {
      const index = rest.indexOf(person.handle);
      if (index >= 0 && (at < 0 || index < at)) {
        at = index;
        found = person;
      }
    }
    if (!found) {
      parts.push(rest);
      break;
    }
    parts.push(rest.slice(0, at));
    parts.push(
      <span className="font-medium" key={parts.length}>
        {found.name ?? t("personHidden")}
      </span>,
    );
    rest = rest.slice(at + found.handle.length);
  }
  return (
    <div className="space-y-2">
      <p className="text-sm whitespace-pre-wrap">{parts}</p>
      {[...byHandle.values()].map((person) => (
        <PersonCard key={person.handle} locale={locale} person={person} />
      ))}
    </div>
  );
}

/** A person as the signed-in person may see them in the panel. */
function PersonCard({ person, locale }: { person: Person; locale: Locale }) {
  const t = useTranslations("Assistant");
  const name = person.name ?? t("personHidden");
  const contact = [
    { label: t("personEmail"), value: person.email },
    { label: t("personPhone"), value: person.phone },
  ].filter((row): row is { label: string; value: string } =>
    Boolean(row.value),
  );
  return (
    <section
      aria-label={t("personCard", { name })}
      className="max-w-md space-y-2 rounded-lg border p-3 text-sm"
    >
      <p className="font-medium">{name}</p>
      {contact.length > 0 ? (
        <dl className="space-y-1">
          {contact.map((row) => (
            <div
              className="flex flex-wrap items-center gap-x-2"
              key={row.label}
            >
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 break-all">{row.value}</span>
                <Copy label={row.label} value={row.value} />
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-muted-foreground">
          {person.name === null ? t("personNoAccess") : t("personNoContact")}
        </p>
      )}
      {person.links.length > 0 ? (
        <p className="flex flex-wrap gap-x-4 gap-y-1">
          {person.links.map((link) => (
            <Link
              className="underline underline-offset-4"
              href={link.href}
              key={link.href}
            >
              {link.title[locale]}
            </Link>
          ))}
        </p>
      ) : null}
    </section>
  );
}

function Copy({ label, value }: { label: string; value: string }) {
  const t = useTranslations("Assistant");
  const [copied, setCopied] = useState(false);
  return (
    <Button
      aria-label={t("copyValue", { label })}
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => setCopied(true));
      }}
      size="sm"
      type="button"
      variant="outline"
    >
      <CopyIcon aria-hidden="true" />
      <span aria-live="polite">{copied ? t("copied") : t("copy")}</span>
    </Button>
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
    if (code === "assistant_setup_budget") return t("setupBudget");
    if (code === "assistant_setup_daily_budget") return t("setupDailyBudget");
  }
  return t("sendError");
}

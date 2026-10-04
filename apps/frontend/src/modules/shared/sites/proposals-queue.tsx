"use client";

import { useEffect, useRef, useState } from "react";
import { CheckIcon, FileDiffIcon, XIcon } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import {
  acceptContentProposal,
  discardContentProposal,
  listContentProposals,
  readContentProposal,
  type ContentProposal,
  type ContentProposalDetail,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

import { nativeName } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { PagePresentationSummary } from "./page-presentation-fields";
import { sitesErrorMessage } from "./problem";

type SourceClaim = { kind: string; reference: string; observed_at: string };
type Block = { block_type: string; data: Record<string, unknown> };

/** Include nested FAQ answers and feature labels in the review, as escaped text. */
function blockText(block: Block): string {
  function text(value: unknown): string[] {
    if (typeof value === "string") return [value];
    if (Array.isArray(value)) return value.flatMap(text);
    if (value && typeof value === "object")
      return Object.values(value).flatMap(text);
    return [];
  }
  return text(block.data).join(" · ");
}

function ProposalDiff({ detail }: { detail: ContentProposalDetail }) {
  const t = useTranslations("Sites");
  const before = detail.blocks_before as unknown as Block[];
  const after = detail.blocks_after as unknown as Block[];
  // The API names the page's own look only when one side has it.
  const lookChanged =
    detail.page_presentation_before !== undefined ||
    detail.page_presentation_after !== undefined;

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {lookChanged && (
        <p className="text-sm sm:col-span-2">
          <span className="font-medium">{t("pagePresentation.review")}: </span>
          <PagePresentationSummary value={detail.page_presentation_before} />
          {" → "}
          <PagePresentationSummary value={detail.page_presentation_after} />
        </p>
      )}
      {(
        [
          ["proposalBefore", before, detail.metadata_before],
          ["proposalAfter", after, detail.metadata_after],
        ] as const
      ).map(([label, blocks, metadata]) => (
        <section
          aria-label={t(label)}
          className="space-y-2 rounded-md bg-muted/40 p-3"
          key={label}
        >
          <h3 className="text-sm font-medium">{t(label)}</h3>
          {metadata && Object.keys(metadata).length > 0 && (
            <dl className="space-y-2 text-sm">
              {(
                [
                  "title",
                  "description",
                  "social_title",
                  "social_description",
                ] as const
              ).map((field) => (
                <div key={field}>
                  <dt className="font-medium">
                    {t(`proposalMetadata_${field}`)}
                  </dt>
                  <dd className="whitespace-pre-wrap break-words">
                    {typeof metadata[field] === "string" && metadata[field]
                      ? metadata[field]
                      : t("proposalEmptyField")}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {blocks.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("proposalNoBlocks")}
            </p>
          ) : (
            <ol className="space-y-2">
              {blocks.map((block, index) => (
                <li className="text-sm" key={`${label}-${index}`}>
                  <code className="text-xs text-muted-foreground">
                    {block.block_type}
                  </code>
                  <p className="break-words">{blockText(block)}</p>
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  );
}

/** What an automation proposed and nobody has decided on yet.
 *
 *  The reasoning is shown as the integration's claim rather than as a finding:
 *  it argued something from sources it names, and the person reading decides.
 *  Presenting a recommendation as a certainty is how an operator stops
 *  reading them. */
export function ProposalsQueue({ onDecided }: { onDecided?: () => void }) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [proposals, setProposals] = useState<ContentProposal[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [openId, setOpenId] = useState<string>();
  const [detail, setDetail] = useState<ContentProposalDetail>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [reload, setReload] = useState(0);
  // The row's button gets focus back when the review closes.
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    let mounted = true;
    void listContentProposals()
      .then((items) => {
        if (mounted) setProposals(items);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, [t, reload]);

  /** The before/after is read only on request: the queue is a screen somebody
   *  scans, and the diff is what they open once something looks worth it. */
  function review(proposal: ContentProposal, trigger: HTMLElement | null) {
    const currentRequest = ++requestId.current;
    setReturnTo(trigger);
    setOpenId(proposal.proposal_id);
    setDetail(undefined);
    setProblem(undefined);
    void readContentProposal(proposal.proposal_id)
      .then((value) => {
        if (requestId.current === currentRequest) setDetail(value);
      })
      .catch((error: unknown) => {
        if (requestId.current === currentRequest)
          setProblem(sitesErrorMessage(error, t));
      });
  }

  function close() {
    ++requestId.current;
    setOpenId(undefined);
    setDetail(undefined);
  }

  function decide(proposal: ContentProposal, action: "accept" | "reject") {
    if (busy) return;
    if (
      action === "accept" &&
      (!detail?.review_token || detail.proposal_id !== proposal.proposal_id)
    )
      return;
    setBusy(true);
    setProblem(undefined);
    const operation =
      action === "accept"
        ? acceptContentProposal(proposal.proposal_id, detail!.review_token)
        : discardContentProposal(proposal.proposal_id);
    void operation
      .then(() => {
        close();
        setReload((value) => value + 1);
        onDecided?.();
      })
      .catch((error: unknown) => {
        setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const kindLabel = (proposal: ContentProposal) =>
    proposal.resource_type === "site_page"
      ? t("proposalOnPage")
      : t("proposalOnEntry");
  const created = (proposal: ContentProposal) =>
    format.dateTime(new Date(proposal.created_at), {
      dateStyle: "medium",
      timeStyle: "short",
    });
  // Sorted by weight, not by the label's letters.
  const riskRank = (risk: string) => ["low", "medium", "high"].indexOf(risk);

  const columns: ColumnDef<ContentProposal, unknown>[] = [
    {
      id: "proposal",
      accessorKey: "summary",
      header: t("lists.proposalColumn"),
      meta: { primary: true },
      cell: ({ row: { original: proposal } }) => (
        <div className="space-y-1">
          <p className="flex flex-wrap items-center gap-2 font-medium">
            <FileDiffIcon aria-hidden="true" className="size-4" />
            {kindLabel(proposal)}
            {/* A page has one line per language: which one this is. */}
            {proposal.locale && (
              <Badge variant="outline">{nativeName(proposal.locale)}</Badge>
            )}
          </p>
          {/* The integration's argument, attributed to it. */}
          <p className="text-sm">
            {t("proposalClaim", { summary: proposal.summary })}
          </p>
          {proposal.expected_outcome && (
            <p className="text-sm text-muted-foreground">
              {t("proposalExpected", { outcome: proposal.expected_outcome })}
            </p>
          )}
        </div>
      ),
    },
    {
      id: "sources",
      header: t("lists.proposalSources"),
      // The sources it named, so the claim can be checked rather than trusted.
      cell: ({ row: { original: proposal } }) => (
        <ul className="space-y-1">
          {(proposal.sources as unknown as SourceClaim[]).map((source) => (
            <li
              className="text-sm text-muted-foreground"
              key={`${source.kind}-${source.reference}`}
            >
              {t(`proposalSource_${source.kind}`)}:{" "}
              <code className="break-all">{source.reference}</code>
            </li>
          ))}
        </ul>
      ),
    },
    {
      id: "risk",
      accessorFn: (proposal) => riskRank(proposal.risk),
      header: t("lists.proposalRisk"),
      cell: ({ row: { original: proposal } }) => (
        <Badge
          variant={
            proposal.risk === "high"
              ? "destructive"
              : proposal.risk === "medium"
                ? "default"
                : "secondary"
          }
        >
          {t(`proposalRisk_${proposal.risk}`)}
        </Badge>
      ),
    },
    {
      id: "created",
      accessorKey: "created_at",
      header: t("lists.proposalCreated"),
      cell: ({ row: { original: proposal } }) => (
        <span className="text-muted-foreground">{created(proposal)}</span>
      ),
    },
    {
      id: "actions",
      header: t("lists.actions"),
      meta: { actions: true },
      cell: ({ row: { original: proposal } }) => (
        <RowActions
          items={[
            {
              label: t("proposalShowDiff"),
              icon: <FileDiffIcon aria-hidden="true" />,
              inline: true,
              onSelect: (trigger) => review(proposal, trigger),
            },
            {
              label: t("proposalReject"),
              icon: <XIcon aria-hidden="true" />,
              destructive: true,
              onSelect: () => decide(proposal, "reject"),
            },
          ]}
          label={t("lists.proposalActionsFor", { date: created(proposal) })}
        />
      ),
    },
  ];

  const open = proposals.find((proposal) => proposal.proposal_id === openId);
  const reviewed =
    open && detail?.proposal_id === open.proposal_id ? detail : undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("proposalsTitle")}</CardTitle>
        <CardDescription>{t("proposalsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        {problem && !open && (
          <p className="mb-3 text-sm text-destructive" role="alert">
            {problem}
          </p>
        )}
        <DataTable
          caption={t("lists.proposalsCaption")}
          columns={columns}
          data={proposals}
          getRowId={(proposal) => proposal.proposal_id}
          labels={{ ...labels, empty: t("proposalsEmpty") }}
          loading={!loaded}
        />
      </CardContent>
      {open ? (
        <Dialog
          onOpenChange={(next) => {
            if (!next && !busy) close();
          }}
          open
        >
          <DialogContent
            className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl"
            closeLabel={common("close")}
            finalFocus={() => returnTo ?? true}
          >
            <DialogHeader>
              <DialogTitle>
                {kindLabel(open)}
                {open.locale ? ` — ${nativeName(open.locale)}` : ""}
              </DialogTitle>
              <DialogDescription>
                {t("proposalClaim", { summary: open.summary })}
              </DialogDescription>
            </DialogHeader>
            {problem && (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            )}
            {reviewed ? (
              <ProposalDiff detail={reviewed} />
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("proposalLoadingDiff")}
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              {t("proposalCommands", { commands: open.commands.join(", ") })}
            </p>
            {open.metadata_pending && (
              <p className="text-sm">{t("proposalMetadataPending")}</p>
            )}
            <p className="text-sm text-muted-foreground">
              {detail?.language_version_waiting
                ? t("proposalAcceptLanguageHint")
                : open.resource_type === "site_page"
                  ? t("proposalAcceptPageHint")
                  : t("proposalAcceptEntryHint")}
            </p>
            <DialogFooter>
              <Button
                disabled={busy}
                onClick={() => decide(open, "reject")}
                type="button"
                variant="destructive"
              >
                <XIcon aria-hidden="true" />
                {t("proposalReject")}
              </Button>
              {/* Accepting needs the token of the change actually shown. */}
              {reviewed?.review_token && (
                <Button
                  disabled={busy}
                  onClick={() => decide(open, "accept")}
                  type="button"
                >
                  <CheckIcon aria-hidden="true" />
                  {t("proposalAccept")}
                </Button>
              )}
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </Card>
  );
}

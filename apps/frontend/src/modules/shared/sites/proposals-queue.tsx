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

import { sitesErrorMessage } from "./problem";

type SourceClaim = { kind: string; reference: string; observed_at: string };
type Block = { block_type: string; data: Record<string, unknown> };

/** The words a block actually shows, so a diff can be read rather than parsed.
 *
 *  Deliberately shallow: every controlled block keeps its text in string
 *  fields one level down, and walking deeper would start rendering data the
 *  block itself chooses not to show. */
function blockText(block: Block): string {
  return Object.values(block.data)
    .filter((value): value is string => typeof value === "string")
    .join(" · ");
}

function ProposalDiff({ detail }: { detail: ContentProposalDetail }) {
  const t = useTranslations("Sites");
  const before = detail.blocks_before as unknown as Block[];
  const after = detail.blocks_after as unknown as Block[];

  return (
    <div className="grid gap-4 sm:grid-cols-2">
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
          <h4 className="text-sm font-medium">{t(label)}</h4>
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
  const format = useFormatter();
  const [proposals, setProposals] = useState<ContentProposal[]>([]);
  const [openId, setOpenId] = useState<string>();
  const [detail, setDetail] = useState<ContentProposalDetail>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [reload, setReload] = useState(0);
  const requestId = useRef(0);

  useEffect(() => {
    let mounted = true;
    void listContentProposals()
      .then((items) => {
        if (mounted) setProposals(items);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      mounted = false;
    };
  }, [t, reload]);

  function toggle(proposal: ContentProposal) {
    const currentRequest = ++requestId.current;
    if (openId === proposal.proposal_id) {
      setOpenId(undefined);
      setDetail(undefined);
      return;
    }
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

  function decide(proposal: ContentProposal, action: "accept" | "reject") {
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
        ++requestId.current;
        setOpenId(undefined);
        setDetail(undefined);
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("proposalsTitle")}</CardTitle>
        <CardDescription>{t("proposalsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        {problem && (
          <p className="mb-3 text-sm text-destructive" role="alert">
            {problem}
          </p>
        )}
        {proposals.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("proposalsEmpty")}</p>
        ) : (
          <ul className="space-y-4">
            {proposals.map((proposal) => {
              const open = openId === proposal.proposal_id;
              return (
                <li
                  className="space-y-3 rounded-lg border p-4"
                  key={proposal.proposal_id}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <FileDiffIcon aria-hidden="true" className="size-4" />
                    <span className="font-medium">
                      {proposal.resource_type === "site_page"
                        ? t("proposalOnPage")
                        : t("proposalOnEntry")}
                    </span>
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
                    <span className="ms-auto text-sm text-muted-foreground">
                      {format.dateTime(new Date(proposal.created_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </span>
                  </div>

                  {/* The integration's argument, attributed to it. */}
                  <p className="text-sm">
                    {t("proposalClaim", { summary: proposal.summary })}
                  </p>
                  {proposal.expected_outcome && (
                    <p className="text-sm text-muted-foreground">
                      {t("proposalExpected", {
                        outcome: proposal.expected_outcome,
                      })}
                    </p>
                  )}

                  <div className="space-y-1">
                    <p className="text-sm font-medium">
                      {t("proposalSources")}
                    </p>
                    <ul className="space-y-1">
                      {(proposal.sources as unknown as SourceClaim[]).map(
                        (source) => (
                          <li
                            className="text-sm text-muted-foreground"
                            key={`${source.kind}-${source.reference}`}
                          >
                            {t(`proposalSource_${source.kind}`)}:{" "}
                            <code className="break-all">
                              {source.reference}
                            </code>
                          </li>
                        ),
                      )}
                    </ul>
                  </div>

                  <p className="text-sm text-muted-foreground">
                    {t("proposalCommands", {
                      commands: proposal.commands.join(", "),
                    })}
                  </p>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      aria-expanded={open}
                      disabled={busy}
                      onClick={() => toggle(proposal)}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      {open ? t("proposalHideDiff") : t("proposalShowDiff")}
                    </Button>
                    {open &&
                      detail?.proposal_id === proposal.proposal_id &&
                      detail.review_token && (
                        <Button
                          disabled={busy}
                          onClick={() => decide(proposal, "accept")}
                          size="sm"
                          type="button"
                        >
                          <CheckIcon aria-hidden="true" />
                          {t("proposalAccept")}
                        </Button>
                      )}
                    <Button
                      disabled={busy}
                      onClick={() => decide(proposal, "reject")}
                      size="sm"
                      type="button"
                      variant="destructive"
                    >
                      <XIcon aria-hidden="true" />
                      {t("proposalReject")}
                    </Button>
                  </div>

                  {open &&
                    (detail?.proposal_id === proposal.proposal_id ? (
                      <ProposalDiff detail={detail} />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        {t("proposalLoadingDiff")}
                      </p>
                    ))}

                  {proposal.metadata_pending && (
                    <p className="text-sm">{t("proposalMetadataPending")}</p>
                  )}
                  <p className="text-sm text-muted-foreground">
                    {proposal.resource_type === "site_page"
                      ? t("proposalAcceptPageHint")
                      : t("proposalAcceptEntryHint")}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

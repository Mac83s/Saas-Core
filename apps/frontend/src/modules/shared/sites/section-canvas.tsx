"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ReorderList } from "@saas-core/ui/components/reorder-list";
import { Button } from "@saas-core/ui/components/button";
import {
  blockOptions,
  blockPayload,
  registry,
  type BlockFormValues,
} from "./block-form";

export function SectionCanvas({
  blocks,
  selected,
  onSelect,
  inspector,
  blockIds,
  onMove,
  disabled,
}: {
  blocks: BlockFormValues[];
  blockIds: string[];
  onMove: (from: number, to: number) => void;
  disabled: boolean;
  selected: number;
  onSelect: (index: number) => void;
  inspector: ReactNode;
}) {
  const t = useTranslations("Sites");
  const [viewport, setViewport] = useState<"desktop" | "tablet" | "mobile">(
    "desktop",
  );
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t("studio.liveDescription")}
      </p>
      <div
        role="group"
        aria-label={t("previewViewport")}
        className="flex flex-wrap gap-2"
      >
        {(["desktop", "tablet", "mobile"] as const).map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={viewport === value ? "default" : "outline"}
            aria-pressed={viewport === value}
            onClick={() => setViewport(value)}
          >
            {t(`previewViewport_${value}`)}
          </Button>
        ))}
      </div>
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 overflow-x-auto rounded-lg border bg-muted/30 p-3">
          <div
            data-testid="live-canvas"
            data-viewport={viewport}
            className="site-theme site-theme--neutral site-theme--sans site-theme--radius-medium site-theme--comfortable mx-auto space-y-3 bg-background"
            style={{
              width:
                viewport === "desktop"
                  ? "100%"
                  : viewport === "tablet"
                    ? 768
                    : 390,
              minHeight: 200,
            }}
          >
            <ReorderList
              items={blocks.map((block, index) => ({
                id: blockIds[index],
                block,
              }))}
              label={t("studio.sections")}
              instructions={t("studio.reorderInstructions")}
              handleLabel={(_item, index) =>
                t("studio.reorderSection", { number: index + 1 })
              }
              movedLabel={(_item, position, count) =>
                t("studio.movedSection", { position, count })
              }
              onMove={onMove}
              disabled={disabled}
            >
              {({ block }, index, handle) => {
                let rendered: ReactNode;
                try {
                  rendered = registry.render(
                    blockPayload(block),
                    String(index),
                  );
                } catch {
                  rendered = (
                    <p className="p-6 text-sm text-muted-foreground">
                      {t("studio.incomplete")}
                    </p>
                  );
                }
                const label = t(
                  blockOptions.find(
                    (option) => option.type === block.block_type,
                  )?.labelKey ?? "addBlock",
                );
                return (
                  <div
                    key={index}
                    className={`relative rounded border-2 ${selected === index ? "border-primary" : "border-transparent"}`}
                  >
                    <div className="absolute right-2 top-2 z-10">{handle}</div>
                    <div aria-hidden="true" inert>
                      {rendered}
                    </div>
                    <button
                      type="button"
                      className="absolute inset-0 cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                      aria-label={t("studio.selectSection", {
                        number: index + 1,
                        name: label,
                      })}
                      aria-pressed={selected === index}
                      onClick={() => onSelect(index)}
                    />
                  </div>
                );
              }}
            </ReorderList>
          </div>
        </div>
        <div
          className="min-w-0 space-y-3"
          aria-label={t("studio.inspector")}
          role="region"
        >
          {inspector}
        </div>
      </div>
    </div>
  );
}

"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { renderPrivateMedia } from "./private-media-preview";
import { useTranslations } from "next-intl";
import {
  designTokenClassName,
  siteAppearanceClassName,
  renderSiteHeader,
  renderNavigation,
  renderResponsiveNavigation,
  type NavigationLink,
  renderSiteFooter,
  type SiteAppearance,
  type BlockFieldDefinition,
} from "@saas-core/site-blocks";
import { InlineText } from "@saas-core/ui/components/inline-text";
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
  library,
  appearance,
  navigation = [],
  blockIds,
  onMove,
  onTextChange,
  disabled,
}: {
  blocks: BlockFormValues[];
  blockIds: string[];
  onMove: (from: number, to: number) => void;
  disabled: boolean;
  onTextChange: (index: number, path: readonly string[], value: string) => void;
  selected: number;
  onSelect: (index: number) => void;
  inspector: ReactNode;
  library: ReactNode;
  appearance?: SiteAppearance;
  navigation?: readonly NavigationLink[];
}) {
  const t = useTranslations("Sites");
  const libraryId = useId();
  const libraryRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const inspectorRef = useRef<HTMLDivElement>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [viewport, setViewport] = useState<"desktop" | "tablet" | "mobile">(
    "desktop",
  );
  const mobileNavigation =
    appearance &&
    renderResponsiveNavigation(
      appearance,
      navigation,
      t("appearance.menu"),
      renderNavigation(navigation, t("appearance.navigation")),
    );
  const menuMode =
    viewport !== "desktop" ? appearance?.navigation[viewport] : undefined;
  return (
    <div className="space-y-3 pb-20 lg:pb-0">
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
      <div
        data-testid="studio-workspace"
        className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[15rem_minmax(0,1fr)_18rem]"
      >
        <aside
          ref={libraryRef}
          tabIndex={-1}
          className="min-w-0 space-y-3 rounded-lg border p-3 xl:col-span-2 2xl:col-span-1 2xl:sticky 2xl:top-4"
          aria-label={t("sectionLibrary.title")}
        >
          <h3 className="hidden font-semibold 2xl:block">
            {t("sectionLibrary.title")}
          </h3>
          <Button
            type="button"
            variant="outline"
            className="w-full 2xl:hidden"
            aria-expanded={libraryOpen}
            aria-controls={libraryId}
            onClick={() => setLibraryOpen(!libraryOpen)}
          >
            {t("sectionLibrary.open")}
          </Button>
          <div
            id={libraryId}
            className={`${libraryOpen ? "block" : "hidden"} max-h-[60vh] space-y-4 overflow-y-auto p-1.5 2xl:block 2xl:max-h-[75vh]`}
          >
            {library}
          </div>
        </aside>
        <div className="min-w-0 overflow-x-auto rounded-lg border bg-muted/30 p-3">
          <div
            ref={canvasRef}
            tabIndex={-1}
            role="region"
            aria-label={t("studio.canvas")}
            data-testid="live-canvas"
            data-viewport={viewport}
            className={`${appearance ? `${designTokenClassName(appearance.designTokens)} ${siteAppearanceClassName(appearance)}` : "site-theme site-theme--neutral site-theme--sans site-theme--radius-medium site-theme--comfortable"} mx-auto space-y-3 bg-background site-canvas--${viewport}`}
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
            {appearance && (
              <div inert aria-hidden="true">
                {menuMode === "drawer" && mobileNavigation}
                {renderSiteHeader(
                  appearance,
                  renderNavigation(navigation, t("appearance.navigation")),
                )}
              </div>
            )}
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
                    blockIds[index],
                    selected === index
                      ? {
                          text: (path, value) => {
                            const definition = inlineField(
                              blockOptions.find(
                                (option) => option.type === block.block_type,
                              )?.fields ?? [],
                              path,
                            );
                            if (!definition) return value;
                            return (
                              <InlineText
                                key={path.join(".")}
                                value={value}
                                disabled={disabled}
                                label={t("studio.editText", {
                                  field: t(definition.labelKey),
                                })}
                                instructions={t(
                                  definition.kind === "textarea"
                                    ? "studio.inlineMultilineHint"
                                    : "studio.inlineHint",
                                )}
                                multiline={definition.kind === "textarea"}
                                onCommit={(next) =>
                                  onTextChange(index, path, next)
                                }
                              />
                            );
                          },
                        }
                      : undefined,
                    renderPrivateMedia,
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
                    className={`relative rounded border-2 ${selected === index ? "border-primary" : "border-transparent"}`}
                  >
                    <div className="flex items-center justify-between gap-2 border-b bg-background p-2 text-sm">
                      <button
                        type="button"
                        className="min-w-0 rounded text-left focus-visible:outline-2 focus-visible:outline-primary"
                        aria-label={t("studio.selectSection", {
                          number: index + 1,
                          name: label,
                        })}
                        aria-pressed={selected === index}
                        onClick={() => onSelect(index)}
                      >
                        {index + 1}. {label}
                      </button>
                      {handle}
                    </div>
                    <div className="relative">
                      <div
                        aria-hidden={selected !== index ? true : undefined}
                        inert={selected !== index}
                      >
                        {rendered}
                      </div>
                      {selected !== index && (
                        <button
                          type="button"
                          tabIndex={-1}
                          aria-hidden="true"
                          className="absolute inset-0 cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                          onClick={() => onSelect(index)}
                        />
                      )}
                    </div>
                  </div>
                );
              }}
            </ReorderList>
            {appearance && (
              <div inert aria-hidden="true">
                {renderSiteFooter(appearance)}
                {menuMode === "bottom" && mobileNavigation}
              </div>
            )}
          </div>
        </div>
        <div
          className="min-w-0 space-y-3 xl:sticky xl:top-4 xl:max-h-[85vh] xl:overflow-y-auto"
          ref={inspectorRef}
          tabIndex={-1}
          aria-label={t("studio.inspector")}
          role="region"
        >
          <h3 className="font-semibold">{t("studio.inspector")}</h3>
          {inspector}
        </div>
      </div>
      <nav
        aria-label={t("studio.tools")}
        className="fixed inset-x-0 bottom-0 z-40 flex justify-around gap-2 border-t bg-background p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] shadow-lg lg:hidden"
      >
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setLibraryOpen(true);
            requestAnimationFrame(() => {
              libraryRef.current?.focus();
              libraryRef.current?.scrollIntoView({ block: "start" });
            });
          }}
        >
          {t("studio.libraryTool")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            canvasRef.current?.focus();
            canvasRef.current?.scrollIntoView({ block: "start" });
          }}
        >
          {t("studio.canvas")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            inspectorRef.current?.focus();
            inspectorRef.current?.scrollIntoView({ block: "start" });
          }}
        >
          {t("studio.settingsTool")}
        </Button>
      </nav>
    </div>
  );
}

/** Only text fields from the manifest may become inline controls. */
function inlineField(
  fields: readonly BlockFieldDefinition[],
  path: readonly string[],
): BlockFieldDefinition | undefined {
  const field = fields.find((candidate) =>
    candidate.path.every((part, index) => path[index] === part),
  );
  if (!field) return undefined;
  const rest = path.slice(field.path.length);
  if (field.kind === "list" && /^\d+$/.test(rest[0] ?? ""))
    return inlineField(field.item ?? [], rest.slice(1));
  return rest.length === 0 &&
    (field.kind === "text" || field.kind === "textarea")
    ? field
    : undefined;
}

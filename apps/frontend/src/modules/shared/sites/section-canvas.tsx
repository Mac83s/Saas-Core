"use client";

import {
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from "react";
import { renderPrivateMedia } from "./private-media-preview";
import { useTranslations } from "next-intl";
import {
  designTokenClassName,
  pagePresentationClassName,
  siteAppearanceClassName,
  renderSiteHeader,
  renderNavigation,
  renderResponsiveNavigation,
  type NavigationLink,
  renderSiteFooter,
  type SiteAppearance,
  type BlockFieldDefinition,
  type PagePresentationV1,
  type PagePresentationV2,
} from "@saas-core/site-blocks";
import { InlineText } from "@saas-core/ui/components/inline-text";
import { ReorderList } from "@saas-core/ui/components/reorder-list";
import {
  MonitorIcon,
  TabletIcon,
  SmartphoneIcon,
  LayersIcon,
  PlusIcon,
  PaletteIcon,
  LayoutTemplateIcon,
  PanelRightIcon,
} from "lucide-react";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  blockOptions,
  blockPayload,
  registry,
  type BlockFormValues,
} from "./block-form";

/** Lets the page editor pick a section exactly as the outline does. */
export type SectionCanvasHandle = { choose: (index: number) => void };

export function SectionCanvas({
  ref,
  unfilled,
  blocks,
  selected,
  onSelect,
  inspector,
  library,
  appearanceControls,
  inspectorRequest = 0,
  templates,
  emptyState,
  appearance,
  pagePresentation,
  navigation = [],
  blockIds,
  onMove,
  onTextChange,
  disabled,
}: {
  ref?: Ref<SectionCanvasHandle>;
  /** `[Uzupełnij: …]` markers still in each section, by position. */
  unfilled?: readonly number[];
  blocks: BlockFormValues[];
  blockIds: string[];
  onMove: (from: number, to: number) => void;
  disabled: boolean;
  onTextChange: (index: number, path: readonly string[], value: string) => void;
  selected: number;
  onSelect: (index: number) => void;
  inspector: ReactNode;
  library: ReactNode;
  appearanceControls?: ReactNode;
  inspectorRequest?: number;
  templates?: ReactNode;
  emptyState?: ReactNode;
  appearance?: SiteAppearance;
  /** This page's own look: style, full width and fonts on the canvas root. */
  pagePresentation?: PagePresentationV1 | PagePresentationV2 | null;
  navigation?: readonly NavigationLink[];
}) {
  const t = useTranslations("Sites");
  const canvasRef = useRef<HTMLDivElement>(null);
  const inspectorRef = useRef<HTMLElement>(null);
  const [leftPanel, setLeftPanel] = useState<
    "outline" | "library" | "templates" | "appearance"
  >(blocks.length ? "outline" : "templates");
  const [mobileNavigationState, setMobileNavigationState] = useState<{
    panel: "left" | "canvas" | "inspector";
    request: number;
  }>({ panel: "canvas", request: inspectorRequest });
  const mobilePanel =
    mobileNavigationState.request === inspectorRequest
      ? mobileNavigationState.panel
      : "inspector";
  const setMobilePanel = (panel: "left" | "canvas" | "inspector") =>
    setMobileNavigationState({ panel, request: inspectorRequest });
  useEffect(() => {
    if (!inspectorRequest) return;
    const frame = requestAnimationFrame(() =>
      inspectorRef.current
        ?.querySelector<HTMLElement>('[aria-invalid="true"]')
        ?.focus(),
    );
    return () => cancelAnimationFrame(frame);
  }, [inspectorRequest]);
  const sectionLabel = (index: number) =>
    t(
      blockOptions.find((option) => option.type === blocks[index]?.block_type)
        ?.labelKey ?? "addBlock",
    );
  const chooseSection = (index: number) => {
    onSelect(index);
    setMobilePanel("canvas");
    requestAnimationFrame(() => {
      if (window.matchMedia?.("(max-width: 1199px)").matches)
        canvasRef.current?.focus({ preventScroll: true });
      canvasRef.current
        ?.querySelector(`[data-section-index="${index}"]`)
        ?.scrollIntoView?.({
          block: "nearest",
          behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)")
            .matches
            ? "auto"
            : "smooth",
        });
    });
  };
  useImperativeHandle(ref, () => ({ choose: chooseSection }));
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
    <div
      className="studio-workspace"
      data-testid="studio-workspace"
      data-mobile-panel={mobilePanel}
    >
      <aside
        className="studio-sidebar studio-sidebar--left"
        aria-label={t("studio.pageNavigation")}
      >
        <div className="studio-sidebar-header">
          <h3>{t("studio.pageNavigation")}</h3>
          <div
            className="studio-sidebar-tabs"
            role="group"
            aria-label={t("studio.tools")}
          >
            {(
              [
                ["outline", LayersIcon, "studio.sections"],
                ["library", PlusIcon, "sectionLibrary.open"],
                ["templates", LayoutTemplateIcon, "studio.pageTemplates"],
                ["appearance", PaletteIcon, "studio.design"],
              ] as const
            )
              .filter(([key]) => key !== "appearance" || appearanceControls)
              .map(([key, Icon, label]) => (
                <Button
                  key={key}
                  type="button"
                  size="sm"
                  variant={leftPanel === key ? "secondary" : "ghost"}
                  aria-pressed={leftPanel === key}
                  aria-label={t(label)}
                  disabled={disabled}
                  onClick={() => setLeftPanel(key)}
                >
                  <Icon aria-hidden="true" />
                  {t(key === "library" ? "studio.libraryTool" : label)}
                </Button>
              ))}
          </div>
        </div>
        <div className="studio-sidebar-scroll">
          {leftPanel === "outline" && (
            <>
              <p className="mb-4 text-sm text-muted-foreground">
                {t("studio.outlineHint")}
              </p>
              <ol className="studio-outline">
                {blocks.map((block, index) => (
                  <li key={blockIds[index]}>
                    <button
                      type="button"
                      aria-current={selected === index ? "true" : undefined}
                      disabled={disabled}
                      onClick={() => chooseSection(index)}
                    >
                      <span className="studio-outline-number">{index + 1}</span>
                      <span className="min-w-0">
                        <span className="block text-xs text-muted-foreground">
                          {sectionLabel(index)}
                        </span>
                        <span className="block truncate font-medium">
                          {outlineTitle(block) || sectionLabel(index)}
                        </span>
                      </span>{" "}
                      {unfilled?.[index] ? (
                        <span className="ml-auto">
                          <UnfilledBadge count={unfilled[index]} />
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ol>
              <Button
                type="button"
                variant="outline"
                className="mt-4 w-full"
                disabled={disabled}
                onClick={() => setLeftPanel("library")}
              >
                <PlusIcon aria-hidden="true" />
                {t("studio.addSection")}
              </Button>
            </>
          )}
          {leftPanel === "library" && library}
          {leftPanel === "templates" && templates}
          {leftPanel === "appearance" && appearanceControls}
        </div>
      </aside>
      <div className="studio-stage">
        <div className="studio-stage-toolbar">
          <div
            role="group"
            aria-label={t("previewViewport")}
            className="flex gap-1"
          >
            {(
              [
                ["desktop", MonitorIcon],
                ["tablet", TabletIcon],
                ["mobile", SmartphoneIcon],
              ] as const
            ).map(([value, Icon]) => (
              <Button
                key={value}
                type="button"
                size="sm"
                variant={viewport === value ? "secondary" : "ghost"}
                aria-pressed={viewport === value}
                onClick={() => setViewport(value)}
              >
                <Icon aria-hidden="true" />
                <span className="hidden sm:inline">
                  {t(`previewViewport_${value}`)}
                </span>
                <span className="sr-only sm:hidden">
                  {t(`previewViewport_${value}`)}
                </span>
              </Button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {t("studio.liveCanvasLabel")}
          </span>
        </div>
        <div className="studio-stage-scroll">
          <div
            ref={canvasRef}
            tabIndex={-1}
            role="region"
            aria-label={t("studio.canvas")}
            data-testid="live-canvas"
            data-viewport={viewport}
            className={`${appearance ? `${designTokenClassName(appearance.designTokens)} ${siteAppearanceClassName(appearance)}` : "site-theme site-theme--neutral site-theme--sans site-theme--radius-medium site-theme--comfortable"} ${pagePresentationClassName(pagePresentation)} studio-page site-canvas--${viewport}`}
            style={{
              width:
                viewport === "desktop"
                  ? "100%"
                  : viewport === "tablet"
                    ? 768
                    : 390,
              minHeight: 200,
              maxWidth: viewport === "desktop" ? undefined : "100%",
            }}
          >
            {blocks.length === 0 && emptyState}
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
                                  field: t(definition.field.labelKey),
                                })}
                                instructions={t(
                                  definition.multiline
                                    ? "studio.inlineMultilineHint"
                                    : "studio.inlineHint",
                                )}
                                multiline={definition.multiline}
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
                    data-section-index={index}
                    className={`studio-section ${selected === index ? "studio-section--selected" : ""}`}
                  >
                    <div className="studio-section-handle">
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
      </div>
      <aside
        ref={inspectorRef}
        className="studio-sidebar studio-sidebar--right"
        aria-label={t("studio.inspector")}
      >
        <div className="studio-sidebar-header">
          <p className="text-xs text-muted-foreground">
            {t("studio.inspector")}
          </p>
          <h3>
            {blocks.length
              ? sectionLabel(selected)
              : t("studio.nothingSelected")}
          </h3>
        </div>
        <div className="studio-sidebar-scroll">
          {blocks.length ? (
            inspector
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("studio.selectHint")}
            </p>
          )}
        </div>
      </aside>
      <nav aria-label={t("studio.tools")} className="studio-mobile-nav">
        {(
          [
            ["left", LayersIcon, "studio.pageNavigation"],
            ["canvas", MonitorIcon, "studio.canvas"],
            ["inspector", PanelRightIcon, "studio.settingsTool"],
          ] as const
        ).map(([key, Icon, label]) => (
          <Button
            key={key}
            type="button"
            variant={mobilePanel === key ? "secondary" : "ghost"}
            aria-pressed={mobilePanel === key}
            onClick={() => setMobilePanel(key)}
          >
            <Icon aria-hidden="true" />
            {t(label)}
          </Button>
        ))}
      </nav>
    </div>
  );
}

/** Texts inside a rich-text node that are one line: a heading, a note's
 *  title, a quote's author and source, a figure's caption. */
const RICH_TEXT_LINES = new Set([
  "text",
  "title",
  "author",
  "source",
  "caption",
]);

/** Only text fields from the manifest may become inline controls. Inside a
 *  rich-text field that is every run of text (a paragraph's, a list item's,
 *  a quote's or a note's — edited as plain text, multiline) and the
 *  one-line texts above; the edit is written at its exact data path. */
function inlineField(
  fields: readonly BlockFieldDefinition[],
  path: readonly string[],
): { field: BlockFieldDefinition; multiline: boolean } | undefined {
  const field = fields.find((candidate) =>
    candidate.path.every((part, index) => path[index] === part),
  );
  if (!field) return undefined;
  const rest = path.slice(field.path.length);
  if (field.kind === "list" && /^\d+$/.test(rest[0] ?? ""))
    return inlineField(field.item ?? [], rest.slice(1));
  if (field.kind === "richText" && /^\d+$/.test(rest[0] ?? "")) {
    const inside = rest.slice(1);
    const run = inside.length > 1 && inside[inside.length - 1] === "text";
    if (run || (inside.length === 1 && RICH_TEXT_LINES.has(inside[0])))
      return { field, multiline: run };
    return undefined;
  }
  return rest.length === 0 &&
    (field.kind === "text" || field.kind === "textarea")
    ? { field, multiline: field.kind === "textarea" }
    : undefined;
}

/** The count a section carries in the outline and in the banner: the digit is
 *  what is seen, the words are what is read and what a hover shows. */
export function UnfilledBadge({ count }: { count: number }) {
  const t = useTranslations("Sites.studio.placeholders");
  const label = t("count", { count });
  return (
    <Badge
      className="border-warning-foreground/30 bg-warning text-warning-foreground"
      title={label}
    >
      <span aria-hidden="true">{count}</span>
      <span className="sr-only">{label}</span>
    </Badge>
  );
}

/** The outline names a section by its own words where it has some. */
export function outlineTitle(block: BlockFormValues): string {
  const { title, heading, author, quote } = block.data;
  for (const candidate of [title, heading, author])
    if (typeof candidate === "string" && candidate.trim()) return candidate;
  if (typeof quote === "string" && quote.trim()) {
    const words = quote.trim().split(/\s+/);
    return words.length > 6 ? `${words.slice(0, 6).join(" ")}…` : quote.trim();
  }
  return "";
}

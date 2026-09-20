"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import type { SiteAppearance } from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";

export function AppearanceEditor({
  value,
  onChange,
  onSave,
  onReload,
  busy,
  dirty,
  problem,
}: {
  value?: SiteAppearance;
  onChange: (value: SiteAppearance) => void;
  onSave: () => void;
  onReload: () => void;
  busy: boolean;
  dirty: boolean;
  problem?: string;
}) {
  const t = useTranslations("Sites.appearance");
  const id = useId();
  const select = (
    name: string,
    current: string,
    options: readonly string[],
    change: (value: string) => void,
  ) => (
    <Field key={name}>
      <FieldLabel htmlFor={`${id}-${name}`}>{t(name)}</FieldLabel>
      <NativeSelect
        id={`${id}-${name}`}
        value={current}
        onChange={(e) => change(e.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {t(`options.${option}`)}
          </option>
        ))}
      </NativeSelect>
    </Field>
  );
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("scope")}</p>
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      {!value ? (
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={onReload}
        >
          {t("reload")}
        </Button>
      ) : (
        <fieldset disabled={busy} className="min-w-0 space-y-4">
          <div className="flex flex-wrap gap-2" aria-label={t("presets")}>
            {(["modern", "editorial", "compact"] as const).map((preset) => (
              <Button
                key={preset}
                type="button"
                variant="outline"
                onClick={() =>
                  onChange({
                    ...value,
                    font: preset === "editorial" ? "georgia" : "system",
                    width: preset === "editorial" ? "narrow" : "wide",
                    buttons: preset === "modern" ? "pill" : "outline",
                    designTokens: {
                      ...value.designTokens,
                      palette: preset === "modern" ? "emerald" : "neutral",
                      spacing: preset === "compact" ? "compact" : "spacious",
                      radius: preset === "editorial" ? "none" : "medium",
                    },
                  })
                }
              >
                {t(`preset.${preset}`)}
              </Button>
            ))}
          </div>
          <div className="grid gap-3">
            {select(
              "font",
              value.font,
              ["system", "arial", "georgia", "trebuchet", "verdana"],
              (font) =>
                onChange({ ...value, font: font as SiteAppearance["font"] }),
            )}
            {select(
              "palette",
              value.designTokens.palette,
              ["neutral", "blue", "emerald"],
              (palette) =>
                onChange({
                  ...value,
                  designTokens: {
                    ...value.designTokens,
                    palette:
                      palette as SiteAppearance["designTokens"]["palette"],
                  },
                }),
            )}
            {select(
              "width",
              value.width,
              ["narrow", "standard", "wide"],
              (width) =>
                onChange({ ...value, width: width as SiteAppearance["width"] }),
            )}
            {select(
              "spacing",
              value.designTokens.spacing,
              ["compact", "comfortable", "spacious"],
              (spacing) =>
                onChange({
                  ...value,
                  designTokens: {
                    ...value.designTokens,
                    spacing:
                      spacing as SiteAppearance["designTokens"]["spacing"],
                  },
                }),
            )}
            {select(
              "radius",
              value.designTokens.radius,
              ["none", "small", "medium", "large"],
              (radius) =>
                onChange({
                  ...value,
                  designTokens: {
                    ...value.designTokens,
                    radius: radius as SiteAppearance["designTokens"]["radius"],
                  },
                }),
            )}
            {select(
              "buttons",
              value.buttons,
              ["solid", "outline", "pill"],
              (buttons) =>
                onChange({
                  ...value,
                  buttons: buttons as SiteAppearance["buttons"],
                }),
            )}
          </div>
          <details open className="space-y-3 rounded-lg border p-3">
            <summary className="cursor-pointer font-medium">
              {t("header")}
            </summary>
            {select(
              "headerLayout",
              value.header.layout,
              ["none", "classic", "centered", "stacked"],
              (layout) =>
                onChange({
                  ...value,
                  header: {
                    ...value.header,
                    layout: layout as SiteAppearance["header"]["layout"],
                  },
                }),
            )}
            <Field>
              <FieldLabel htmlFor={`${id}-brand`}>{t("brand")}</FieldLabel>
              <Input
                id={`${id}-brand`}
                maxLength={160}
                value={value.header.brand}
                onChange={(e) =>
                  onChange({
                    ...value,
                    header: { ...value.header, brand: e.target.value },
                  })
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor={`${id}-tagline`}>{t("tagline")}</FieldLabel>
              <Input
                id={`${id}-tagline`}
                maxLength={180}
                value={value.header.tagline}
                onChange={(e) =>
                  onChange({
                    ...value,
                    header: { ...value.header, tagline: e.target.value },
                  })
                }
              />
            </Field>
          </details>
          <details className="space-y-3 rounded-lg border p-3">
            <summary className="cursor-pointer font-medium">
              {t("footer")}
            </summary>
            {select(
              "footerLayout",
              value.footer.layout,
              ["none", "simple", "centered", "columns"],
              (layout) =>
                onChange({
                  ...value,
                  footer: {
                    ...value.footer,
                    layout: layout as SiteAppearance["footer"]["layout"],
                  },
                }),
            )}
            <Field>
              <FieldLabel htmlFor={`${id}-footer-text`}>
                {t("footerText")}
              </FieldLabel>
              <Textarea
                id={`${id}-footer-text`}
                maxLength={300}
                value={value.footer.text}
                onChange={(e) =>
                  onChange({
                    ...value,
                    footer: { ...value.footer, text: e.target.value },
                  })
                }
              />
            </Field>
            {value.footer.links.map((link, index) => (
              <div key={index} className="space-y-2 rounded border p-2">
                <Field>
                  <FieldLabel htmlFor={`${id}-link-${index}`}>
                    {t("linkLabel", { number: index + 1 })}
                  </FieldLabel>
                  <Input
                    id={`${id}-link-${index}`}
                    value={link.label}
                    maxLength={80}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        footer: {
                          ...value.footer,
                          links: value.footer.links.map((item, i) =>
                            i === index
                              ? { ...item, label: e.target.value }
                              : item,
                          ),
                        },
                      })
                    }
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor={`${id}-href-${index}`}>
                    {t("linkHref", { number: index + 1 })}
                  </FieldLabel>
                  <Input
                    id={`${id}-href-${index}`}
                    value={link.href}
                    maxLength={500}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        footer: {
                          ...value.footer,
                          links: value.footer.links.map((item, i) =>
                            i === index
                              ? { ...item, href: e.target.value }
                              : item,
                          ),
                        },
                      })
                    }
                  />
                </Field>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    onChange({
                      ...value,
                      footer: {
                        ...value.footer,
                        links: value.footer.links.filter((_, i) => i !== index),
                      },
                    })
                  }
                >
                  {t("removeLink")}
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              disabled={value.footer.links.length >= 8}
              onClick={() =>
                onChange({
                  ...value,
                  footer: {
                    ...value.footer,
                    links: [
                      ...value.footer.links,
                      { label: t("newLink"), href: "/" },
                    ],
                  },
                })
              }
            >
              {t("addLink")}
            </Button>
          </details>
          <details className="space-y-3 rounded-lg border p-3">
            <summary className="cursor-pointer font-medium">
              {t("navigation")}
            </summary>
            {select(
              "mobile",
              value.navigation.mobile,
              ["drawer", "bottom"],
              (mobile) =>
                onChange({
                  ...value,
                  navigation: {
                    ...value.navigation,
                    mobile: mobile as "drawer" | "bottom",
                  },
                }),
            )}
            {select(
              "tablet",
              value.navigation.tablet,
              ["drawer", "bottom"],
              (tablet) =>
                onChange({
                  ...value,
                  navigation: {
                    ...value.navigation,
                    tablet: tablet as "drawer" | "bottom",
                  },
                }),
            )}
            <p className="text-xs text-muted-foreground">
              {t("navigationHint")}
            </p>
          </details>
          <Button type="button" disabled={!dirty} onClick={onSave}>
            {t("save")}
          </Button>
          <Button type="button" variant="outline" onClick={onReload}>
            {t("reload")}
          </Button>
        </fieldset>
      )}
    </div>
  );
}

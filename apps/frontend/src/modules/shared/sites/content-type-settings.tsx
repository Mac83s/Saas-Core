"use client";

/** What one content type is (ADR-079 pkt 25): its name, what its entries are
 *  to search engines, whether they join the site's RSS feed, its addresses
 *  per language, its place in the menu, who may write it — and switching it
 *  off. Everything here is the company's to change; nothing asks for a word
 *  a company's owner would have to look up. */

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { PowerOffIcon, SaveIcon } from "lucide-react";

import {
  listContentTypes,
  setCollectionAutomationPolicy,
  setCollectionNavigation,
  updateContentType,
  type ContentCollection,
  type ContentSchemaType,
  type ContentSchemaTypeOption,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { usePublisher } from "#components/panel/panel-access";
import { Link } from "#i18n/navigation";
import { AutomationPolicyField } from "./automation-policy";
import { CollectionPaths } from "./collection-paths";
import {
  SwitchOffDialog,
  contentTypeProblem,
  contentTypesHref,
  schemaTypeText,
} from "./content-types-panel";

export function ContentTypeSettings({
  siteId,
  typeId,
  address,
  onLoaded,
  onSwitchedOff,
}: {
  siteId: string;
  typeId: string;
  /** The site's public address, before the type's own part of it. */
  address?: string | null;
  /** The type's name, for the page's title. */
  onLoaded?: (collection: ContentCollection) => void;
  onSwitchedOff: (collection: ContentCollection) => void;
}) {
  const t = useTranslations("Sites");
  const locale = useLocale();
  // The platform's own workspace has no builder site (ADR-079 pkt 29): what
  // a type is to the site's feed and to the site's menu changes nothing its
  // readers see, and the menu waits for a publication its panel has not. So
  // neither switch is drawn there, and the words name the service's pages.
  const publisher = usePublisher();
  const [collection, setCollection] = useState<ContentCollection | null>();
  const [options, setOptions] = useState<ContentSchemaTypeOption[]>([]);
  const [name, setName] = useState("");
  const [schemaType, setSchemaType] =
    useState<ContentSchemaType>("BlogPosting");
  const [inFeed, setInFeed] = useState(true);
  const [nameProblem, setNameProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  const [switchingOff, setSwitchingOff] = useState(false);

  useEffect(() => {
    let current = true;
    listContentTypes(siteId)
      .then((found) => {
        if (!current) return;
        const row = found.types.find((item) => item.collection.id === typeId);
        setOptions(found.schema_types);
        setCollection(row?.collection ?? null);
        if (row) {
          setName(row.collection.name);
          setSchemaType(row.collection.schema_type);
          setInFeed(row.collection.in_site_feed);
          onLoaded?.(row.collection);
        }
      })
      .catch((error: unknown) => {
        if (current) setProblem(contentTypeProblem(error, t));
      });
    return () => {
      current = false;
    };
    // `onLoaded` is the page's own setter: asking again when it changes
    // identity would load the type on every render of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId, typeId, t]);

  if (collection === undefined && !problem)
    return (
      <p className="text-sm text-muted-foreground">
        {t("contentTypes.loading")}
      </p>
    );
  if (!collection)
    return (
      <div className="space-y-3 text-sm">
        <p role="alert">{problem ?? t("contentTypes.notFound")}</p>
        <Link className="underline" href={contentTypesHref(siteId)}>
          {t("contentTypes.backToList")}
        </Link>
      </div>
    );
  if (collection.archived)
    return (
      <div className="space-y-3 text-sm">
        <p className="rounded-lg border bg-muted/40 p-3">
          {t("contentTypes.isOff")}
        </p>
        <Link className="underline" href={contentTypesHref(siteId)}>
          {t("contentTypes.backToList")}
        </Link>
      </div>
    );

  const chosen = options.find((option) => option.schema_type === schemaType);
  const changed =
    name.trim() !== collection.name ||
    schemaType !== collection.schema_type ||
    inFeed !== collection.in_site_feed;

  async function run(action: () => Promise<ContentCollection>, done?: string) {
    setBusy(true);
    setProblem(undefined);
    setNotice("");
    try {
      const updated = await action();
      setCollection(updated);
      onLoaded?.(updated);
      if (done) setNotice(done);
    } catch (error) {
      setProblem(contentTypeProblem(error, t));
    } finally {
      setBusy(false);
    }
  }

  function save() {
    const typed = name.trim();
    if (typed.length < 2) {
      setNameProblem(t("required"));
      return;
    }
    setNameProblem(undefined);
    void run(
      () =>
        updateContentType(collection!.id, {
          name: typed,
          schema_type: schemaType,
          in_site_feed: inFeed,
        }),
      t("contentTypes.saved"),
    );
  }

  return (
    <div className="space-y-6">
      {notice ? (
        <p aria-live="polite" className="text-sm text-muted-foreground">
          {notice}
        </p>
      ) : null}
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("contentTypes.detailsTitle")}</CardTitle>
          <CardDescription>
            {t(
              publisher
                ? "contentTypes.detailsDescriptionPublisher"
                : "contentTypes.detailsDescription",
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              save();
            }}
          >
            <FieldGroup>
              <Field data-invalid={Boolean(nameProblem)}>
                <FieldLabel htmlFor="type-settings-name">
                  {t("contentTypes.name")}
                </FieldLabel>
                <Input
                  aria-describedby="type-settings-name-hint"
                  id="type-settings-name"
                  maxLength={160}
                  onChange={(event) => setName(event.target.value)}
                  value={name}
                />
                <FieldDescription id="type-settings-name-hint">
                  {t(
                    publisher
                      ? "contentTypes.nameHintPublisher"
                      : "contentTypes.nameHint",
                  )}
                </FieldDescription>
                <FieldError>{nameProblem}</FieldError>
              </Field>
              <Field>
                <FieldLabel htmlFor="type-settings-kind">
                  {t("contentTypes.kind")}
                </FieldLabel>
                <NativeSelect
                  aria-describedby="type-settings-kind-hint"
                  id="type-settings-kind"
                  onChange={(event) =>
                    setSchemaType(event.target.value as ContentSchemaType)
                  }
                  value={schemaType}
                >
                  {options.map((option) => (
                    <option key={option.schema_type} value={option.schema_type}>
                      {schemaTypeText(option, locale, "title")}
                    </option>
                  ))}
                </NativeSelect>
                <FieldDescription id="type-settings-kind-hint">
                  {chosen ? schemaTypeText(chosen, locale, "hint") : ""}
                </FieldDescription>
              </Field>
              {publisher ? null : (
                <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                  <input
                    checked={inFeed}
                    className="mt-1"
                    onChange={(event) => setInFeed(event.target.checked)}
                    type="checkbox"
                  />
                  <span>
                    <span className="font-medium">
                      {t("contentTypes.feed")}
                    </span>
                    <span className="block text-muted-foreground">
                      {t("contentTypes.feedHint")}
                    </span>
                  </span>
                </label>
              )}
            </FieldGroup>
            <Button disabled={busy || !changed} type="submit">
              <SaveIcon aria-hidden="true" />
              {t("contentTypes.save")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("contentTypes.addressTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <CollectionPaths
            address={address}
            collection={collection}
            key={collection.id}
            ofType
            onSaved={(updated) => {
              setCollection(updated);
              onLoaded?.(updated);
            }}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            {t(
              publisher
                ? "contentTypes.automationTitle"
                : "contentTypes.menuTitle",
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {publisher ? null : (
            <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
              <input
                checked={collection.show_in_navigation}
                className="mt-1"
                disabled={busy}
                onChange={(event) => {
                  const show = event.target.checked;
                  void run(() => setCollectionNavigation(collection.id, show));
                }}
                type="checkbox"
              />
              <span>
                <span className="font-medium">{t("contentTypes.inMenu")}</span>
                <span className="block text-muted-foreground">
                  {t("contentTypes.inMenuHint")}
                </span>
              </span>
            </label>
          )}
          <AutomationPolicyField
            busy={busy}
            id="type-settings-policy"
            onChange={(policy) =>
              void run(() =>
                setCollectionAutomationPolicy(collection.id, policy),
              )
            }
            value={collection.automation_policy}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("contentTypes.offTitle")}</CardTitle>
          <CardDescription>
            {t(
              publisher
                ? "contentTypes.offDescriptionPublisher"
                : "contentTypes.offDescription",
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            disabled={busy}
            onClick={() => setSwitchingOff(true)}
            variant="outline"
          >
            <PowerOffIcon aria-hidden="true" />
            {t("contentTypes.offButton")}
          </Button>
        </CardContent>
      </Card>

      {switchingOff ? (
        <SwitchOffDialog
          collection={collection}
          onClose={() => setSwitchingOff(false)}
          onDone={(result) => {
            setSwitchingOff(false);
            onSwitchedOff(result.collection);
          }}
        />
      ) : null}
    </div>
  );
}

/** The block types of a test-only vertical, `vertical.sample` (ADR-077): what
 *  a product's module writes to bring blocks to the site builder, kept here
 *  so the contract is proven by tests and has one worked example
 *  (docs/architecture/site-block-types.md). No profile composes the module;
 *  the tests compose it themselves.
 *
 *  A product keeps this file in its module (`src/modules/vertical/<name>/
 *  site-blocks.tsx`), its contract in `packages/contracts/site-blocks/
 *  modules/<module id>/`, and lists the set in `src/product/site-blocks.ts`. */

import contract from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/manifest.json";
import recordListV1 from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/vertical.sample.record_list.v1.schema.json";
import recordListV2 from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/vertical.sample.record_list.v2.schema.json";
import recordProfileV1 from "@saas-core/contracts/site-blocks/fixtures/modules/vertical.sample/vertical.sample.record_profile.v1.schema.json";
import {
  defineModuleSiteBlocks,
  plainBlockText,
  type BlockComponentProps,
  type ModuleBlockContract,
} from "@saas-core/site-blocks";

export const SAMPLE_MODULE = "vertical.sample";
export const RECORD_LIST = "vertical.sample.record_list";
export const RECORD_PROFILE = "vertical.sample.record_profile";

type RecordListData = {
  heading: string;
  order?: "name" | "newest";
  intro?: string;
  curator?: string;
  curator_role?: string;
  reviewed_on?: string;
  action?: { label: string; href: string };
};
/** What the module's public source answers for the block (`site_blocks`). */
type RecordListLive = { records: { name: string; href: string }[] };

/** A block a person places. It carries a choice; the records are the
 *  module's live data, so a published page hands them in `live` and the
 *  studio — where nobody answered — draws a sketch of the list. */
function RecordList({ data, editor, live }: BlockComponentProps) {
  const list = data as RecordListData;
  const text = editor?.text ?? plainBlockText;
  const records = (live?.data as RecordListLive | undefined)?.records;
  return (
    <section
      className="site-block site-sample-records"
      data-block-type={RECORD_LIST}
    >
      <h2>{text(["heading"], list.heading)}</h2>
      {list.intro ? <p>{text(["intro"], list.intro)}</p> : null}
      {records ? (
        <ul>
          {records.map((record) => (
            <li key={record.href}>
              <a href={record.href}>{record.name}</a>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="site-sample-records__sketch" aria-hidden="true">
          <li />
          <li />
          <li />
        </ul>
      )}
      {list.curator ? (
        <p className="site-sample-records__curator">
          {text(["curator"], list.curator)}
          {list.curator_role ? (
            <> — {text(["curator_role"], list.curator_role)}</>
          ) : null}
          {list.reviewed_on ? <> · {list.reviewed_on}</> : null}
        </p>
      ) : null}
      {list.action ? (
        <p>
          <a className="site-button" href={list.action.href}>
            {text(["action", "label"], list.action.label)}
          </a>
        </p>
      ) : null}
    </section>
  );
}

type RecordProfileData = {
  name: string;
  summary?: string;
  facts?: { label: string; value: string }[];
  ratings?: { label: string; value: number }[];
  sections?: { heading: string; text: string }[];
  related?: { name: string; href: string }[];
};

/** A block the module builds for a record's own page: nobody edits it, so it
 *  reads no editor and has no form. The page's `<h1>` is the site's (the
 *  page's title), so the record's name here is a second-level heading. */
function RecordProfile({ data }: BlockComponentProps) {
  const record = data as RecordProfileData;
  return (
    <section
      className="site-block site-sample-profile"
      data-block-type={RECORD_PROFILE}
    >
      <h2>{record.name}</h2>
      {record.summary ? <p>{record.summary}</p> : null}
      {record.facts?.length ? (
        <dl>
          {record.facts.map((fact) => (
            <div key={fact.label}>
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {record.ratings?.length ? (
        <ul className="site-sample-profile__ratings">
          {record.ratings.map((rating) => (
            <li key={rating.label}>
              {rating.label}:{" "}
              <meter
                min={0}
                max={5}
                value={rating.value}
                aria-label={rating.label}
              >
                {rating.value}/5
              </meter>
            </li>
          ))}
        </ul>
      ) : null}
      {record.sections?.map((part) => (
        <div key={part.heading}>
          <h3>{part.heading}</h3>
          <p>{part.text}</p>
        </div>
      ))}
      {record.related?.length ? (
        <ul className="site-sample-profile__related">
          {record.related.map((other) => (
            <li key={other.href}>
              <a href={other.href}>{other.name}</a>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export const sampleModuleBlocks = defineModuleSiteBlocks(
  contract as ModuleBlockContract,
  {
    [RECORD_LIST]: {
      schemas: [recordListV1, recordListV2],
      // v2 only added optional fields: v1 data is v2 data.
      migrators: { 1: (data) => ({ ...data }) },
      component: RecordList,
      live: true,
      catalog: {
        category: "offer",
        labelKey: "sampleRecordList",
        fields: [
          { path: ["heading"], kind: "text", labelKey: "sampleHeading" },
          { path: ["intro"], kind: "textarea", labelKey: "sampleIntro" },
          {
            path: ["order"],
            kind: "choice",
            labelKey: "sampleOrder",
            options: ["name", "newest"],
          },
          { path: ["curator"], kind: "text", labelKey: "sampleCurator" },
          {
            path: ["curator_role"],
            kind: "text",
            labelKey: "sampleCuratorRole",
          },
          {
            path: ["action", "label"],
            kind: "text",
            labelKey: "sampleActionLabel",
          },
          {
            path: ["action", "href"],
            kind: "url",
            labelKey: "sampleActionHref",
          },
        ],
      },
    },
    [RECORD_PROFILE]: {
      schemas: [recordProfileV1],
      component: RecordProfile,
    },
  },
);

/** The words the studio shows for the blocks: what the product brings under
 *  `Sites` in `product.messages`. */
export const sampleModuleMessages = {
  pl: {
    Sites: {
      sampleRecordList: "Lista rekordów",
      sampleHeading: "Nagłówek",
      sampleIntro: "Wprowadzenie",
      sampleOrder: "Kolejność",
      sampleOrderOptions: { name: "Według nazwy", newest: "Od najnowszych" },
      sampleCurator: "Opiekun listy",
      sampleCuratorRole: "Rola opiekuna",
      sampleActionLabel: "Tekst przycisku",
      sampleActionHref: "Adres przycisku",
    },
  },
  en: {
    Sites: {
      sampleRecordList: "List of records",
      sampleHeading: "Heading",
      sampleIntro: "Introduction",
      sampleOrder: "Order",
      sampleOrderOptions: { name: "By name", newest: "Newest first" },
      sampleCurator: "Curator",
      sampleCuratorRole: "Curator's role",
      sampleActionLabel: "Button text",
      sampleActionHref: "Button address",
    },
  },
};

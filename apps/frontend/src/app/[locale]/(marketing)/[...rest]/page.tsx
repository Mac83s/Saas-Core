import { notFound } from "next/navigation";

/**
 * An address no route claims, at any depth, gets the site's own 404 — header,
 * footer and the visitor's language — instead of the framework's bare English
 * page. Single segments reach `[slug]`, which does the same.
 */
export default function UnknownAddress() {
  notFound();
}

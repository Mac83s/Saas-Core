"use client";

import { useEffect, useMemo, useState } from "react";
import { getPublicLocales, type PublicLocales } from "@saas-core/api-client";

export type CompanyLocale = { code: string; name: string };

/** The company's content languages in its order, each named in itself
 *  (ADR-071 pkt 5) — what a language picker in the panel offers, never a list
 *  written into the component. `fallback` is offered until the answer comes,
 *  and when it cannot be read. */
export function useCompanyLocales(
  fallback: readonly string[],
): CompanyLocale[] {
  const [state, setState] = useState<PublicLocales>();
  useEffect(() => {
    let mounted = true;
    void getPublicLocales()
      .then((value) => {
        if (mounted) setState(value);
      })
      .catch(() => undefined);
    return () => {
      mounted = false;
    };
  }, []);
  const fallbackKey = fallback.join(",");
  // One array per answer: callers put it in their effects' dependencies.
  return useMemo(
    () => companyLocales(state, fallbackKey.split(",")),
    [state, fallbackKey],
  );
}

export function companyLocales(
  state: PublicLocales | undefined,
  fallback: readonly string[],
): CompanyLocale[] {
  const names = new Map(
    (state?.offered ?? []).map((item) => [item.code, item.native_name]),
  );
  return (state?.public_locales ?? fallback).map((code) => ({
    code,
    name: names.get(code) ?? nativeName(code),
  }));
}

/** A language named in itself ("Deutsch"), as the registry names it, for the
 *  moment before the registry's answer comes. */
function nativeName(code: string): string {
  try {
    const name = new Intl.DisplayNames([code], { type: "language" }).of(code);
    if (name) return name.charAt(0).toLocaleUpperCase(code) + name.slice(1);
  } catch {
    // An unknown code: the code itself is the honest name.
  }
  return code.toUpperCase();
}

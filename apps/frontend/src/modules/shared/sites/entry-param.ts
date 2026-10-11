"use client";

/** The entry open in the side sheet lives in the address as `?entry=<id>`
 *  (PR1g): a reload, a copied link and the browser's Back all land where the
 *  operator was. Opening pushes one history entry, so Back closes the sheet;
 *  closing takes that entry off again rather than stacking a second one.
 *  The native history API, as the site choice does (`writeSiteToAddress`):
 *  Next keeps its own state in step with it. */

import { useCallback, useEffect, useRef, useState } from "react";

export const ENTRY_PARAM = "entry";

function readEntry(): string | undefined {
  try {
    return (
      new URLSearchParams(globalThis.location?.search).get(ENTRY_PARAM) ??
      undefined
    );
  } catch {
    return undefined;
  }
}

function addressWith(id: string | undefined): URL | undefined {
  try {
    const address = new URL(globalThis.location.href);
    if (id) address.searchParams.set(ENTRY_PARAM, id);
    else address.searchParams.delete(ENTRY_PARAM);
    return address;
  } catch {
    return undefined;
  }
}

export function useEntryParam(): {
  entryId: string | undefined;
  open: (id: string) => void;
  close: () => void;
} {
  const [entryId, setEntryId] = useState<string | undefined>(readEntry);
  // Whether this visit added the history entry the sheet stands on.
  const pushed = useRef(false);

  useEffect(() => {
    const follow = () => {
      const asked = readEntry();
      if (!asked) pushed.current = false;
      setEntryId(asked);
    };
    window.addEventListener("popstate", follow);
    return () => window.removeEventListener("popstate", follow);
  }, []);

  const open = useCallback((id: string) => {
    const address = addressWith(id);
    if (address) {
      const history = globalThis.history;
      if (readEntry()) {
        history?.replaceState(history.state, "", address);
      } else {
        history?.pushState(history.state, "", address);
        pushed.current = true;
      }
    }
    setEntryId(id);
  }, []);

  const close = useCallback(() => {
    setEntryId(undefined);
    if (pushed.current) {
      // Back to the address the sheet was opened from.
      pushed.current = false;
      globalThis.history?.back();
      return;
    }
    const address = addressWith(undefined);
    if (address && readEntry()) {
      globalThis.history?.replaceState(globalThis.history.state, "", address);
    }
  }, []);

  return { entryId, open, close };
}

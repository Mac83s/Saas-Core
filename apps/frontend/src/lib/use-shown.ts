import { useState } from "react";

/** What a dialog showed last, kept while it closes. A dialog drawn from state
 *  that is emptied on close reads its empty words on the way out — „Wersja 0”
 *  for a moment (03.10) — so its content comes from here and `open` from the
 *  state itself. */
export function useShown<T>(value: T | null): T | null {
  const [last, setLast] = useState(value);
  if (value !== null && value !== last) setLast(value);
  return value ?? last;
}

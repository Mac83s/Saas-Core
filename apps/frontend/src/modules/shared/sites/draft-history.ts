"use client";

import { useEffect, useState, useRef } from "react";
import type { FieldValues, UseFormReturn } from "react-hook-form";

/** Session-local history. Server loads/saves form a new undo boundary. */
export function useDraftHistory<T extends FieldValues>(form: UseFormReturn<T>) {
  const [availability, setAvailability] = useState({
    canUndo: false,
    canRedo: false,
  });
  const state = useRef({
    past: [] as T[],
    future: [] as T[],
    present: structuredClone(form.getValues()),
    field: "",
    at: 0,
    replaying: false,
  });
  useEffect(() => {
    const subscription = form.watch((_values, event) => {
      const history = state.current;
      if (history.replaying) return;
      const next = structuredClone(form.getValues());
      if (!event.name) {
        history.past = [];
        history.future = [];
        history.field = "";
      } else if (JSON.stringify(next) !== JSON.stringify(history.present)) {
        const now = Date.now();
        if (
          event.type !== "change" ||
          history.field !== event.name ||
          now - history.at > 600
        ) {
          history.past.push(history.present);
          if (history.past.length > 100) history.past.shift();
        }
        history.future = [];
        history.field = event.type === "change" ? event.name : "";
        history.at = now;
      } else return;
      history.present = next;
      setAvailability({
        canUndo: history.past.length > 0,
        canRedo: history.future.length > 0,
      });
    });
    return () => subscription.unsubscribe();
  }, [form]);
  function restore(direction: "past" | "future") {
    const history = state.current;
    const next = history[direction].pop();
    if (!next) return;
    history[direction === "past" ? "future" : "past"].push(history.present);
    history.present = structuredClone(next);
    history.field = "";
    history.replaying = true;
    form.reset(next, { keepDefaultValues: true });
    history.replaying = false;
    setAvailability({
      canUndo: history.past.length > 0,
      canRedo: history.future.length > 0,
    });
  }
  return {
    ...availability,
    undo: () => restore("past"),
    redo: () => restore("future"),
  };
}

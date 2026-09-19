"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { GripVerticalIcon } from "lucide-react";

import { Button } from "#components/button";

const transferType = "application/x-saas-reorder";

/** Reorders existing items only. Touch users can use the caller's move buttons;
 *  keyboard users use ArrowUp/ArrowDown on the handle. Never imports drop data. */
export function ReorderList<T extends { id: string }>({
  items,
  label,
  instructions,
  handleLabel,
  movedLabel,
  onMove,
  children,
  disabled = false,
}: {
  items: readonly T[];
  label: string;
  instructions: string;
  handleLabel: (item: T, index: number) => string;
  movedLabel: (item: T, position: number, count: number) => string;
  onMove: (from: number, to: number) => void;
  children: (item: T, index: number, handle: ReactNode) => ReactNode;
  disabled?: boolean;
}) {
  const scope = useId();
  const order = JSON.stringify(items.map((item) => item.id));
  const dragging = useRef<{ id: string; order: string } | null>(null);
  const handles = useRef(new Map<string, HTMLButtonElement>());
  const [over, setOver] = useState<{
    id: string;
    edge: "before" | "after";
  } | null>(null);
  const [announcement, setAnnouncement] = useState("");
  function move(from: number, to: number) {
    if (disabled || from < 0 || to < 0 || to >= items.length || from === to)
      return;
    const item = items[from];
    onMove(from, to);
    setAnnouncement(movedLabel(item, to + 1, items.length));
    requestAnimationFrame(() => handles.current.get(item.id)?.focus());
  }
  function cancel() {
    dragging.current = null;
    setOver(null);
  }
  function sourceIndex() {
    return !disabled && dragging.current?.order === order
      ? items.findIndex((item) => item.id === dragging.current?.id)
      : -1;
  }
  return (
    <>
      <p id={`${scope}-instructions`} className="sr-only">
        {instructions}
      </p>
      <div role="list" aria-label={label} className="space-y-3">
        {items.map((item, index) => (
          <div
            key={item.id}
            role="listitem"
            data-reorder-id={item.id}
            data-drop-edge={over?.id === item.id ? over.edge : undefined}
            className="relative data-[drop-edge=before]:border-t-4 data-[drop-edge=after]:border-b-4 data-[drop-edge]:border-primary"
            onDragOver={(event) => {
              const from = sourceIndex();
              if (from < 0) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
              setOver(
                from === index
                  ? null
                  : { id: item.id, edge: from < index ? "after" : "before" },
              );
            }}
            onDrop={(event) => {
              const from = sourceIndex();
              if (
                from < 0 ||
                event.dataTransfer.getData(transferType) !== scope
              )
                return;
              event.preventDefault();
              event.stopPropagation();
              cancel();
              move(from, index);
            }}
          >
            {children(
              item,
              index,
              <Button
                ref={(node) => {
                  if (node) handles.current.set(item.id, node);
                  else handles.current.delete(item.id);
                }}
                type="button"
                size="icon-sm"
                variant="outline"
                className="cursor-grab active:cursor-grabbing"
                aria-label={handleLabel(item, index)}
                aria-describedby={`${scope}-instructions`}
                disabled={disabled || items.length < 2}
                draggable={!disabled && items.length > 1}
                onDragStart={(event) => {
                  if (disabled || event.currentTarget.matches(":disabled")) {
                    event.preventDefault();
                    return;
                  }
                  dragging.current = { id: item.id, order };
                  event.dataTransfer.setData(transferType, scope);
                  event.dataTransfer.effectAllowed = "move";
                }}
                onDragEnd={cancel}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    cancel();
                    return;
                  }
                  if (event.key !== "ArrowUp" && event.key !== "ArrowDown")
                    return;
                  event.preventDefault();
                  move(index, index + (event.key === "ArrowUp" ? -1 : 1));
                }}
              >
                <GripVerticalIcon aria-hidden="true" />
              </Button>,
            )}
          </div>
        ))}
      </div>
      <p
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {announcement}
      </p>
    </>
  );
}

"use client";

import { Button } from "@saas-core/ui/components/button";

/** One of a few short options as a row of segments, the chosen one raised:
 *  the control the studio's top bar uses for its mode and its device. Each
 *  segment says whether it is pressed; the fieldset around names the group. */
export function SegmentedOptions<Option extends string>({
  options,
  value,
  label,
  onChange,
}: {
  options: readonly Option[];
  value: Option;
  label: (option: Option) => string;
  onChange: (option: Option) => void;
}) {
  return (
    <div className="studio-segmented flex flex-wrap">
      {options.map((option) => (
        <Button
          key={option}
          type="button"
          variant="ghost"
          size="sm"
          // 44 px on touch, the inspector's 32 px on a mouse.
          className="h-11 flex-auto px-1.5 text-xs pointer-fine:h-8"
          aria-pressed={option === value}
          onClick={() => onChange(option)}
        >
          {label(option)}
        </Button>
      ))}
    </div>
  );
}

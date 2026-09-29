"use client";

import { Slider as SliderPrimitive } from "@base-ui/react/slider";

import { cn } from "#lib/utils";

type SliderProps = SliderPrimitive.Root.Props & {
  /** Names the thumb, which is the focusable range input. */
  "aria-label"?: string;
  "aria-labelledby"?: string;
};

/** A value picked by dragging along a track — one thumb per value. The name
 *  goes on the thumb, because that is the input a screen reader reaches. */
function Slider({
  className,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  value,
  defaultValue,
  ...props
}: SliderProps) {
  const initial = value ?? defaultValue;
  const thumbs = Array.isArray(initial) ? initial.length : 1;
  return (
    <SliderPrimitive.Root
      data-slot="slider"
      className={cn("w-full", className)}
      defaultValue={defaultValue}
      thumbAlignment="edge"
      value={value}
      {...props}
    >
      <SliderPrimitive.Control className="relative flex h-6 w-full touch-none items-center select-none data-[disabled]:opacity-50">
        <SliderPrimitive.Track
          data-slot="slider-track"
          className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted select-none"
        >
          <SliderPrimitive.Indicator
            data-slot="slider-range"
            className="h-full bg-primary select-none"
          />
        </SliderPrimitive.Track>
        {Array.from({ length: thumbs }, (_, index) => (
          <SliderPrimitive.Thumb
            key={index}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            data-slot="slider-thumb"
            className="block size-5 shrink-0 rounded-full border border-primary bg-background shadow-sm ring-ring/50 transition-[color,box-shadow] select-none hover:ring-4 focus-visible:ring-4 focus-visible:outline-hidden data-[disabled]:pointer-events-none"
          />
        ))}
      </SliderPrimitive.Control>
    </SliderPrimitive.Root>
  );
}

export { Slider };

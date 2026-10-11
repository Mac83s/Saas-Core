"use client";

import * as React from "react";
import { MinusIcon } from "lucide-react";
import { OTPInput, OTPInputContext, REGEXP_ONLY_DIGITS } from "input-otp";

import { cn } from "#lib/utils";

/** The slot pattern for a numeric code (an authenticator app's six digits). */
const OTP_DIGITS_PATTERN = REGEXP_ONLY_DIGITS;

/**
 * One-time-code field (shadcn `InputOTP`): a single labelled input drawn as
 * slots. Digits only by default, `autoComplete="one-time-code"`, a pasted code
 * fills every slot. `aria-invalid` on it paints all slots as an error.
 */
function InputOTP({
  className,
  containerClassName,
  maxLength = 6,
  pattern = OTP_DIGITS_PATTERN,
  inputMode = "numeric",
  autoComplete = "one-time-code",
  ...props
}: Omit<React.ComponentProps<typeof OTPInput>, "children" | "render"> & {
  containerClassName?: string;
  children: React.ReactNode;
}) {
  const invalid =
    props["aria-invalid"] === true || props["aria-invalid"] === "true";
  return (
    <div
      className={cn("group/otp inline-flex", containerClassName)}
      data-invalid={invalid ? "true" : undefined}
      data-slot="input-otp-root"
    >
      <OTPInput
        autoComplete={autoComplete}
        containerClassName="flex items-center gap-2 has-disabled:opacity-50"
        className={cn("disabled:cursor-not-allowed", className)}
        data-slot="input-otp"
        inputMode={inputMode}
        maxLength={maxLength}
        pattern={pattern}
        {...props}
      />
    </div>
  );
}

function InputOTPGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex items-center", className)}
      data-slot="input-otp-group"
      {...props}
    />
  );
}

function InputOTPSlot({
  index,
  className,
  ...props
}: React.ComponentProps<"div"> & { index: number }) {
  const context = React.useContext(OTPInputContext);
  const slot = context?.slots[index];
  const { char, hasFakeCaret, isActive } = slot ?? {};
  return (
    <div
      className={cn(
        "relative flex h-11 w-10 items-center justify-center border-y border-r border-input bg-background text-base transition-colors first:rounded-l-lg first:border-l last:rounded-r-lg data-[active=true]:z-10 data-[active=true]:border-ring data-[active=true]:ring-3 data-[active=true]:ring-ring/50 group-data-[invalid=true]/otp:border-destructive group-data-[invalid=true]/otp:data-[active=true]:ring-destructive/20 md:text-sm dark:bg-input/30 dark:group-data-[invalid=true]/otp:data-[active=true]:ring-destructive/40",
        className,
      )}
      data-active={isActive}
      data-slot="input-otp-slot"
      {...props}
    >
      {char}
      {hasFakeCaret ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="h-4 w-px animate-pulse bg-foreground motion-reduce:animate-none" />
        </div>
      ) : null}
    </div>
  );
}

function InputOTPSeparator(props: React.ComponentProps<"div">) {
  return (
    <div data-slot="input-otp-separator" role="separator" {...props}>
      <MinusIcon aria-hidden="true" className="size-4" />
    </div>
  );
}

export {
  InputOTP,
  InputOTPGroup,
  InputOTPSeparator,
  InputOTPSlot,
  OTP_DIGITS_PATTERN,
};

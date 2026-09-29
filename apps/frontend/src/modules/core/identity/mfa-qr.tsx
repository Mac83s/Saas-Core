"use client";

import { useTranslations } from "next-intl";
import QRCode from "react-qr-code";

/**
 * The enrolment URI as a QR code, shared by the two places that turn two-step
 * verification on: the forced setup at sign-in and the account settings card.
 *
 * The white plate is not decoration. The card underneath follows the theme, and
 * on a dark one a black-on-dark code has neither contrast nor the quiet zone a
 * camera looks for, so it does not scan. The secret stays printed next to it —
 * a phone without a camera, or a desktop authenticator, still needs it.
 */
export function MfaQrCode({ value }: { value: string }) {
  const t = useTranslations("Identity");

  return (
    <div
      aria-label={t("qrAlt")}
      className="flex justify-center rounded-lg bg-white p-4"
      role="img"
    >
      <QRCode aria-hidden="true" size={160} value={value} />
    </div>
  );
}

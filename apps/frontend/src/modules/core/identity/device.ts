/**
 * What a session's browser header says about the device, for people:
 * „Chrome 154 · Windows”, not „Mozilla/5.0 (Windows NT 10.0…)” (UX-054).
 */
export type DeviceKind = "desktop" | "phone" | "tablet" | "script";

export type Device = {
  kind: DeviceKind;
  /** „Chrome 154”; empty for a script or an unknown header. */
  browser: string;
  /** „Windows”, „Android”; empty when the header does not say. */
  os: string;
  /** A browser driven by a program (headless). */
  automated: boolean;
};

const SCRIPTS =
  /^(node|undici|axios|python-requests|python-urllib|curl|wget|go-http-client|okhttp|java|postman|insomnia)\b/i;

const BROWSERS: readonly [RegExp, string][] = [
  [/\bEdg(?:e|A|iOS)?\/(\d+)/, "Edge"],
  [/\bOPR\/(\d+)/, "Opera"],
  [/\bSamsungBrowser\/(\d+)/, "Samsung Internet"],
  [/\b(?:Firefox|FxiOS)\/(\d+)/, "Firefox"],
  [/\bHeadlessChrome\/(\d+)/, "Chrome"],
  [/\b(?:Chrome|CriOS)\/(\d+)/, "Chrome"],
  [/\bVersion\/(\d+)[^ ]* (?:Mobile\/\S+ )?Safari\//, "Safari"],
];

const SYSTEMS: readonly [RegExp, string][] = [
  [/\biPad\b/, "iPadOS"],
  [/\b(?:iPhone|iPod)\b/, "iOS"],
  [/\bAndroid\b/, "Android"],
  [/\bCrOS\b/, "ChromeOS"],
  [/\bWindows\b/, "Windows"],
  [/\bMac OS X\b|\bMacintosh\b/, "macOS"],
  [/\bLinux\b/, "Linux"],
];

export function describeDevice(label: string): Device {
  const header = label.trim();
  if (SCRIPTS.test(header))
    return { kind: "script", browser: "", os: "", automated: false };
  const found = BROWSERS.find(([pattern]) => pattern.test(header));
  const version = found ? header.match(found[0])?.[1] : undefined;
  const os = SYSTEMS.find(([pattern]) => pattern.test(header))?.[1] ?? "";
  const kind: DeviceKind =
    /\biPad\b|\bTablet\b/.test(header) ||
    (/\bAndroid\b/.test(header) && !/\bMobile\b/.test(header))
      ? "tablet"
      : /\bMobile\b|\biPhone\b/.test(header)
        ? "phone"
        : "desktop";
  return {
    kind,
    browser: found ? `${found[1]}${version ? ` ${version}` : ""}` : "",
    os,
    automated: /\bHeadless/.test(header),
  };
}

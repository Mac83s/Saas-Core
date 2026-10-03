import { expect, test } from "vitest";

import { describeDevice } from "./device";

test.each([
  [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    { kind: "desktop", browser: "Chrome 154", os: "Windows", automated: false },
  ],
  [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/151.0.0.0 Safari/537.36",
    { kind: "desktop", browser: "Chrome 151", os: "Linux", automated: true },
  ],
  [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    { kind: "phone", browser: "Safari 18", os: "iOS", automated: false },
  ],
  [
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Mobile Safari/537.36",
    { kind: "phone", browser: "Chrome 154", os: "Android", automated: false },
  ],
  [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0",
    { kind: "desktop", browser: "Edge 154", os: "macOS", automated: false },
  ],
  ["node", { kind: "script", browser: "", os: "", automated: false }],
  ["Laptop", { kind: "desktop", browser: "", os: "", automated: false }],
] as const)("%s", (label, device) => {
  expect(describeDevice(label)).toEqual(device);
});

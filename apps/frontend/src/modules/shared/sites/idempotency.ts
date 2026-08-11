import type { MutableRefObject } from "react";

export type MutationReceipt = { signature: string; key: string };

export function mutationKey(
  receipt: MutableRefObject<MutationReceipt | undefined>,
  scope: string,
  payload: object,
): string {
  const signature = JSON.stringify(payload);
  if (receipt.current?.signature !== signature) {
    receipt.current = {
      signature,
      key: `${scope}-${globalThis.crypto.randomUUID()}`,
    };
  }
  return receipt.current.key;
}

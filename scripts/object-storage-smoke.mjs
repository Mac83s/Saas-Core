import { createHash, createHmac } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const endpoint = new URL(
  process.env.SAAS_CORE_S3_URL ?? "http://127.0.0.1:8333",
);
const bucket = process.env.OBJECT_STORAGE_BUCKET ?? "saas-core-local";
const region = process.env.OBJECT_STORAGE_REGION ?? "us-east-1";
const secretsDirectory = resolve(
  process.env.SAAS_CORE_SECRETS_DIR ?? ".runtime/secrets",
);
const accessKeyId = await readSecret("object_storage_access_key_id");
const secretAccessKey = await readSecret("object_storage_secret_access_key");

const target = new URL(`/${encodeRfc3986(bucket)}`, endpoint);
target.searchParams.set("list-type", "2");
target.searchParams.set("max-keys", "1");

const now = new Date();
const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, "");
const dateStamp = amzDate.slice(0, 8);
const payloadHash = sha256("");
const canonicalQuery = [...target.searchParams.entries()]
  .sort(([left], [right]) => left.localeCompare(right))
  .map(([key, value]) => `${encodeRfc3986(key)}=${encodeRfc3986(value)}`)
  .join("&");
const canonicalHeaders =
  `host:${target.host}\n` +
  `x-amz-content-sha256:${payloadHash}\n` +
  `x-amz-date:${amzDate}\n`;
const signedHeaders = "host;x-amz-content-sha256;x-amz-date";
const canonicalRequest = [
  "GET",
  target.pathname,
  canonicalQuery,
  canonicalHeaders,
  signedHeaders,
  payloadHash,
].join("\n");
const credentialScope = `${dateStamp}/${region}/s3/aws4_request`;
const stringToSign = [
  "AWS4-HMAC-SHA256",
  amzDate,
  credentialScope,
  sha256(canonicalRequest),
].join("\n");
const signingKey = hmac(
  hmac(hmac(hmac(`AWS4${secretAccessKey}`, dateStamp), region), "s3"),
  "aws4_request",
);
const signature = hmac(signingKey, stringToSign).toString("hex");

const response = await fetch(target, {
  headers: {
    Authorization:
      `AWS4-HMAC-SHA256 Credential=${accessKeyId}/${credentialScope}, ` +
      `SignedHeaders=${signedHeaders}, Signature=${signature}`,
    "x-amz-content-sha256": payloadHash,
    "x-amz-date": amzDate,
  },
  signal: AbortSignal.timeout(5_000),
});
const body = await response.text();
if (!response.ok || !body.includes("<ListBucketResult")) {
  throw new Error(
    `Object storage smoke nie przeszedł: HTTP ${response.status}`,
  );
}

console.log(`OK object storage: ${response.status}, bucket ${bucket}`);

async function readSecret(name) {
  return (await readFile(resolve(secretsDirectory, name), "utf8")).trim();
}

function encodeRfc3986(value) {
  return encodeURIComponent(value).replace(
    /[!'()*]/g,
    (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function hmac(key, value) {
  return createHmac("sha256", key).update(value).digest();
}

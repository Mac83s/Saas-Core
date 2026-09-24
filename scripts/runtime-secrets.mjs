import { randomBytes } from "node:crypto";
import { chmod, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const secretsDirectory = resolve(
  process.env.SAAS_CORE_SECRETS_DIR ?? ".runtime/secrets",
);
const runtimeDirectory = resolve(".runtime");

await mkdir(secretsDirectory, { recursive: true, mode: 0o700 });
await mkdir(resolve(runtimeDirectory, "backups"), {
  recursive: true,
  mode: 0o700,
});
await mkdir(resolve(runtimeDirectory, "reports"), {
  recursive: true,
  mode: 0o700,
});
await mkdir(resolve(runtimeDirectory, "logs"), {
  recursive: true,
  mode: 0o700,
});
await mkdir(resolve(runtimeDirectory, "emails"), {
  recursive: true,
  mode: 0o700,
});
await ensureSecret("django_secret_key", randomBytes(48).toString("base64url"));
await ensureSecret("postgres_password", "saas_core");
await ensureSecret(
  "postgres_app_password",
  randomBytes(32).toString("base64url"),
);
// ADR-041: the identity role reads the handful of tables that have to be read
// before anybody knows which tenant is asking.
await ensureSecret(
  "postgres_identity_password",
  randomBytes(32).toString("base64url"),
);
await ensureSecret("redis_password", randomBytes(32).toString("base64url"));
await ensureSecret(
  "grafana_admin_password",
  randomBytes(24).toString("base64url"),
);
await ensureSecret(
  "object_storage_access_key_id",
  randomBytes(16).toString("hex").toUpperCase().slice(0, 20),
);
await ensureSecret(
  "object_storage_secret_access_key",
  randomBytes(32).toString("base64url"),
);
// Optional integration: empty files keep the unconfigured service disabled.
await ensureSecret("seo_ssa_service_key", "");
await ensureSecret("seo_ssa_callback_secret", "");
await ensureSecret("image_generation_openai_api_key", "");
await chmod(secretsDirectory, 0o700);

async function ensureSecret(name, value) {
  const path = resolve(secretsDirectory, name);
  try {
    await writeFile(path, `${value}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
    await chmod(path, 0o600);
    console.log(`Utworzono lokalny sekret: ${name}`);
  } catch (error) {
    if (error?.code !== "EEXIST") throw error;
  }
}

console.log(`Sekrety runtime są gotowe w ${secretsDirectory}`);

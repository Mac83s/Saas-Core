import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Customer sites keep the trailing slash of their addresses (ADR-071): the
  // proxy decides per host, so Next must not strip it first — doing that made
  // every canonical address of a customer site answer 308.
  skipTrailingSlashRedirect: true,
  // Under `next dev` a customer site lives two labels below `.localhost`
  // (`<site>.<profile>.localhost`), which the dev server's own allowance
  // (`*.localhost`) does not reach: it refuses the page its dev socket, and
  // the page never hydrates — a contact form or a stay calendar stays dead.
  // Only the dev server reads this; a build does not.
  allowedDevOrigins: ["*.*.localhost"],
  transpilePackages: [
    "@saas-core/ui",
    "@saas-core/api-client",
    "@saas-core/site-blocks",
  ],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default createNextIntlPlugin()(nextConfig);

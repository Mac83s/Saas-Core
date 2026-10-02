import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Customer sites keep the trailing slash of their addresses (ADR-071): the
  // proxy decides per host, so Next must not strip it first — doing that made
  // every canonical address of a customer site answer 308.
  skipTrailingSlashRedirect: true,
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

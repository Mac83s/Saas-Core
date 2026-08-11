import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
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

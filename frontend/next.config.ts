import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-hosted on Azure Container Apps: `next build` emits a minimal Node
  // server plus only the files it traces into .next/standalone, which the
  // Dockerfile copies into a small runtime image (no node_modules, no Vercel).
  output: "standalone",
};

export default nextConfig;

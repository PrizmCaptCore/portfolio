const path = require('path')

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false, // Disabled for BlockNote compatibility
  output: 'export',
  images: {
    unoptimized: true,
  },
  // Add basePath configuration
  basePath: '',
  assetPrefix: '/',

  // Add webpack configuration for Tauri
  webpack: (config, { isServer, dev }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        path: false,
        os: false,
      };

      // @huggingface/transformers is loaded at runtime from
      // /transformers/transformers.web.js (copied into public/ by
      // scripts/copy-transformers-wasm.mjs), so webpack never bundles it.
      // onnxruntime-node is still reachable through its top-level package
      // descriptor during dependency-graph analysis; stub it out so the
      // native .node binaries never enter the build graph.
      config.resolve.alias = {
        ...config.resolve.alias,
        'onnxruntime-node': false,
      };
      config.module.rules.push({
        test: /\.node$/,
        use: 'null-loader',
      });
    }
    return config;
  },
}

module.exports = nextConfig

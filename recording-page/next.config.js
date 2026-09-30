/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  experimental: {
    // proxy.ts buffers request bodies; beyond this limit uploads are silently truncated.
    // 160mb ≈ 80 min of 16kHz mono WAV — keep in sync with MAX_WAV_BYTES in page.tsx.
    proxyClientMaxBodySize: "160mb",
  },
};

module.exports = nextConfig;

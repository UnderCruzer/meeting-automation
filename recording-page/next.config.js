/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // next/image is unused; disabling the optimizer removes an unauthenticated endpoint.
  images: { unoptimized: true },
};

module.exports = nextConfig;

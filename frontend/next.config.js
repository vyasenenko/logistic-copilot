/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/favicon.ico", destination: "/icons/favicon.ico" }];
  },
};

module.exports = nextConfig;

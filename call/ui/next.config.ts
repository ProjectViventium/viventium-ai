import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  devIndicators: false, // no developer badge on the call screen
  distDir: process.env.NEXT_DIST_DIR || '.next', // (tests build beside the running page, never into it)
  // Every page is asked for afresh. A page Next prerenders is sent as cacheable for a year (s-maxage), so a browser
  // can keep showing the previous build. Script filenames change with each build, so scripts keep their cache.
  async headers() {
    return [
      {
        source: '/((?!_next/static|_next/image|favicon).*)',
        headers: [{ key: 'Cache-Control', value: 'no-store, must-revalidate' }],
      },
    ];
  },
};

export default nextConfig;

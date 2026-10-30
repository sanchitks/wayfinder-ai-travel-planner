/** @type {import('next').NextConfig} */

// STATIC_EXPORT=1 builds the GitHub Pages version: plain files in out/, served under
// NEXT_PUBLIC_BASE_PATH (e.g. /wayfinder-ai-travel-planner). Local `npm run dev/build` is unchanged.
const staticExport = process.env.STATIC_EXPORT === "1";
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  ...(staticExport && {
    output: "export",
    distDir: ".next-export", // keeps the local .next build (npm start) untouched
    basePath,
    trailingSlash: true, // GitHub Pages serves /login/ from login/index.html
    images: { unoptimized: true },
  }),
};

export default nextConfig;

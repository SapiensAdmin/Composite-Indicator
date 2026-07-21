/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Data lives in public/data/*.json and is fetched client-side, so the app is
  // fully static-friendly. Vercel builds this natively (root directory = /web).
};

export default nextConfig;

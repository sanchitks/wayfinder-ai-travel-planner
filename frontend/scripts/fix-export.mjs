// After `STATIC_EXPORT=1 next build`, for the GitHub Pages copy:
// 1. Next 16 writes route prefetch data as <route>/__next.<segment>/__PAGE__.txt but the browser asks for
//    <route>/__next.<segment>.__PAGE__.txt. Without a copy under that name those prefetches 404.
// 2. GitHub Pages can't send security headers, so each page gets a Content-Security-Policy <meta> tag.
//    Scripts may only come from this site, plus the page's own inline scripts by their exact SHA-256,
//    so an injected <script> (XSS) won't run and can't steal the login token. Data may only be fetched
//    from this site and the API (NEXT_PUBLIC_API_URL).
// Usage: node scripts/fix-export.mjs <export dir>
import { createHash } from "node:crypto";
import { copyFileSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";

const root = process.argv[2] || ".next-export";
const files = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full);
    else files.push(full);
  }
})(root);

let copied = 0;
for (const full of files) {
  const parts = relative(root, full).split(sep);
  const i = parts.findIndex((p) => p.startsWith("__next."));
  if (i === -1 || i === parts.length - 1) continue; // not inside a __next.<segment>/ folder
  copyFileSync(full, join(root, ...parts.slice(0, i), parts.slice(i).join(".")));
  copied++;
}
console.log(`fix-export: wrote ${copied} prefetch file(s) under the names the browser requests`);

const api = process.env.NEXT_PUBLIC_API_URL ? new URL(process.env.NEXT_PUBLIC_API_URL).origin : "";

function policy(html) {
  const hashes = new Set();
  for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (/\bsrc\s*=/i.test(m[1]) || !m[2]) continue;
    hashes.add(`'sha256-${createHash("sha256").update(m[2], "utf8").digest("base64")}'`);
  }
  return [
    "default-src 'self'",
    `script-src 'self' ${[...hashes].join(" ")}`.trim(),
    "style-src 'self' 'unsafe-inline'", // React style={{...}} attributes and the map library
    "img-src 'self' data: blob: https:", // place, hotel and map-tile photos come from many hosts
    "font-src 'self' data:",
    `connect-src 'self' ${api}`.trim(),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-src 'none'",
    "worker-src 'self' blob:",
    ...(api.startsWith("http:") ? [] : ["upgrade-insecure-requests"]), // not for a local http test API
  ].join("; ");
}

let pages = 0;
for (const full of files.filter((f) => f.endsWith(".html"))) {
  let html = readFileSync(full, "utf8");
  if (html.includes('http-equiv="Content-Security-Policy"')) continue; // already done
  const tags = `<meta http-equiv="Content-Security-Policy" content="${policy(html)}"/><meta name="referrer" content="strict-origin-when-cross-origin"/>`;
  const at = html.search(/<meta charSet="utf-8"\/>/i);
  if (at === -1) throw new Error(`fix-export: no <meta charSet> in ${full}`);
  const end = html.indexOf(">", at) + 1;
  html = html.slice(0, end) + tags + html.slice(end); // right after charset, before any script runs
  writeFileSync(full, html);
  pages++;
}
console.log(`fix-export: added a Content-Security-Policy to ${pages} page(s)${api ? ` (API ${api})` : ""}`);

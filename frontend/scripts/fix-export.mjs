// After `STATIC_EXPORT=1 next build`: Next 16 writes route prefetch data as
// <route>/__next.<segment>/__PAGE__.txt but the browser asks for <route>/__next.<segment>.__PAGE__.txt.
// Without a copy under that name those prefetches 404 (pages still work, just slower to open).
// Usage: node scripts/fix-export.mjs <export dir>
import { copyFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const root = process.argv[2] || ".next-export";
let copied = 0;
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      walk(full);
      continue;
    }
    const parts = relative(root, full).split(sep);
    const i = parts.findIndex((p) => p.startsWith("__next."));
    if (i === -1 || i === parts.length - 1) continue; // not inside a __next.<segment>/ folder
    const flat = join(root, ...parts.slice(0, i), parts.slice(i).join("."));
    copyFileSync(full, flat);
    copied++;
  }
}
walk(root);
console.log(`fix-export: wrote ${copied} prefetch file(s) under the names the browser requests`);

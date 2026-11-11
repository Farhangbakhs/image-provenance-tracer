// Next 16's static export writes route-segment prefetch files as nested folders
// (`__next.cases/$d$id/__PAGE__.txt`) while the client requests them by their flat, dotted
// name (`__next.cases.$d$id.__PAGE__.txt`). Copy each to the flat name so prefetches resolve
// on any static host instead of falling back to full page loads.
import { copyFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const out = process.argv[2] ?? "out";
let copied = 0;

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (!statSync(path).isDirectory()) continue;
    if (name.startsWith("__next.")) flatten(path, dir);
    else walk(path);
  }
}

function flatten(root, parent) {
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) stack.push(path);
      else {
        const flat = relative(parent, path).split(sep).join(".");
        copyFileSync(path, join(parent, flat));
        copied += 1;
      }
    }
  }
}

walk(out);
console.log(`flattened ${copied} prefetch file(s) in ${out}`);

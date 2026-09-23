// Where the demo driver finds Playwright, without a package file or an `npm install` in this repo.
//
// The repo is Python-only; the stage library (`stage.ts`, copied from the npch plugin) imports
// `@playwright/test`, and the driver imports `playwright`. This hook maps those two bare names to an
// installed copy. Loaded with `node --import ./tests/demo/pw.mjs …`; the TypeScript files run on
// Node's own type stripping (Node >= 22.18 / 23.6), so nothing is compiled either.
//
// PLAYWRIGHT_NODE_MODULES points at the node_modules folder holding `playwright` and
// `@playwright/test`. The default is the copy this project was built against.
import { registerHooks } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";
import fs from "node:fs";

const ROOT = process.env.PLAYWRIGHT_NODE_MODULES || "/Users/dong/.hermes/hermes-agent/node_modules";
const MAP = {
  "@playwright/test": path.join(ROOT, "@playwright/test/index.mjs"),
  playwright: path.join(ROOT, "playwright/index.mjs"),
};
for (const [name, file] of Object.entries(MAP)) {
  if (!fs.existsSync(file)) {
    console.error(`[pw] ${name} not found at ${file} — set PLAYWRIGHT_NODE_MODULES to a node_modules folder that has it`);
    process.exit(2);
  }
}

registerHooks({
  resolve(specifier, context, next) {
    const file = MAP[specifier];
    if (file) return { url: pathToFileURL(file).href, shortCircuit: true, format: "module" };
    return next(specifier, context);
  },
});

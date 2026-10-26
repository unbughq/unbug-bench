import fs from "node:fs";
const lock = JSON.parse(fs.readFileSync(new URL("./package-lock.json", import.meta.url)));
const packages = Object.entries(lock.packages).filter(([path]) => /(?:^|\/)node_modules\/@medusajs\/[^/]+$/.test(path));
if (!packages.length) throw new Error("No resolved Medusa packages");
// Upstream admin tooling requires UI 4.2.1; UI has no 2.19.0 release.
const wrong = packages.filter(([path, pkg]) => pkg.version !== (path.endsWith("node_modules/@medusajs/ui") ? "4.2.1" : "2.19.0"));
if (wrong.length) throw new Error(`Medusa version mismatch: ${JSON.stringify(wrong.map(([path, pkg]) => [path, pkg.version]))}`);
console.log(JSON.stringify({medusa_version: "2.19.0", resolved_packages: packages.length, exceptions: {"@medusajs/ui": "4.2.1"}}));

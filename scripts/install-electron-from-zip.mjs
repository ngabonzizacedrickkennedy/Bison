import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";

const version = "43.3.0";
const artifact = `electron-v${version}-win32-x64.zip`;
const zipPath = path.join(process.env.USERPROFILE, "tools", "electron", artifact);

const anchor = path.join(import.meta.dirname, "..", "apps", "desktop", "package.json");
const require = createRequire(anchor);
const packageDir = path.dirname(require.resolve("electron/package.json"));
const distDir = path.join(packageDir, "dist");
const executable = path.join(distDir, "electron.exe");

await stat(zipPath);

console.log("zip    ", zipPath);
console.log("package", packageDir);

await rm(distDir, { recursive: true, force: true });
await mkdir(distDir, { recursive: true });

execFileSync("tar", ["-xf", zipPath, "-C", distDir], { stdio: "inherit" });

await stat(executable);
await writeFile(path.join(packageDir, "path.txt"), "electron.exe", "utf8");

console.log("binary ", executable);

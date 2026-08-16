import { spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const SERVICES_DIR = join(ROOT, "services");

const IGNORED_DIRS = new Set([
  ".venv",
  "node_modules",
  "__pycache__",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
]);

const TASKS = {
  sync: [["sync", "--reinstall-package", "bison-contracts", "--refresh"]],
  lint: [
    ["run", "ruff", "check", "."],
    ["run", "ruff", "format", "--check", "."],
  ],
  typecheck: [["run", "mypy", "."]],
  test: [["run", "pytest", "-q"]],
};

const TOLERATED_EXIT_CODES = {
  test: new Set([0, 5]),
};

function containsPythonSource(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (IGNORED_DIRS.has(entry.name)) continue;
      if (containsPythonSource(join(dir, entry.name))) return true;
    } else if (entry.name.endsWith(".py")) {
      return true;
    }
  }
  return false;
}

function discoverProjects() {
  if (!existsSync(SERVICES_DIR)) return [];
  return readdirSync(SERVICES_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => ({ name: entry.name, dir: join(SERVICES_DIR, entry.name) }))
    .filter((project) => existsSync(join(project.dir, "pyproject.toml")))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function runUv(dir, args) {
  const result = spawnSync("uv", args, {
    cwd: dir,
    stdio: "inherit",
  });
  if (result.error) return { code: 1, reason: result.error.message };
  return { code: result.status ?? 1 };
}

const task = process.argv[2];

if (!Object.hasOwn(TASKS, task)) {
  console.error(`usage: node scripts/py.mjs <${Object.keys(TASKS).join("|")}>`);
  process.exit(1);
}

const projects = discoverProjects();

if (projects.length === 0) {
  console.error("no python projects found under services/");
  process.exit(1);
}

const tolerated = TOLERATED_EXIT_CODES[task] ?? new Set([0]);
const failures = [];

for (const project of projects) {
  if (task !== "sync" && !containsPythonSource(project.dir)) {
    console.log(`skip  ${project.name}  (no python sources)`);
    continue;
  }

  console.log(`\n${task}  ${project.name}`);

  for (const args of TASKS[task]) {
    const { code, reason } = runUv(project.dir, args);
    if (!tolerated.has(code)) {
      failures.push(
        `${project.name}: uv ${args.join(" ")} exited ${code}${reason ? ` (${reason})` : ""}`,
      );
      break;
    }
  }
}

if (failures.length > 0) {
  console.error(`\n${failures.length} failure(s):`);
  for (const failure of failures) console.error(`  ${failure}`);
  process.exit(1);
}

console.log(`\n${task}: ok across ${projects.length} python project(s)`);

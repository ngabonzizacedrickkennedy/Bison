$ErrorActionPreference = 'Stop'

$NodeServices = @(
    'bootstrap-service',
    'gateway-service',
    'engine-session-service',
    'secrets-vault-service',
    'dev-env-service'
)

$PythonServices = @(
    'project-service',
    'analyst-service',
    'mediator-service',
    'inspector-service',
    'router-service',
    'model-broker-service',
    'task-runner-service',
    'automation-service',
    'screen-observer-service',
    'task-store-service'
)

foreach ($name in $NodeServices) {
    $dir = "services/$name"
    New-Item -ItemType Directory -Force -Path "$dir/src" | Out-Null

    @"
{
  "name": "@bison/$name",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "scripts": {
    "build": "tsc --build",
    "typecheck": "tsc --noEmit",
    "clean": "rimraf dist .turbo tsconfig.tsbuildinfo"
  },
  "dependencies": {
    "@bison/contracts": "workspace:*"
  },
  "devDependencies": {
    "@bison/tsconfig": "workspace:*",
    "@types/node": "^22.10.2",
    "rimraf": "^6.0.1",
    "typescript": "^5.7.2"
  }
}
"@ | Set-Content "$dir/package.json" -Encoding utf8

    @"
{
  "extends": "@bison/tsconfig/base.json",
  "compilerOptions": {
    "rootDir": "./src",
    "outDir": "./dist",
    "types": ["node"]
  },
  "include": ["src/**/*.ts"],
  "references": [{ "path": "../../packages/contracts" }]
}
"@ | Set-Content "$dir/tsconfig.json" -Encoding utf8

    "export const SERVICE_NAME = '$name';" |
        Set-Content "$dir/src/index.ts" -Encoding utf8
}

foreach ($name in $PythonServices) {
    $module = $name.Replace('-', '_')
    $dir = "services/$name"
    New-Item -ItemType Directory -Force -Path "$dir/src/$module" | Out-Null
    New-Item -ItemType Directory -Force -Path "$dir/tests" | Out-Null

    @"
[project]
name = "$name"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "bison-contracts",
    "pydantic>=2.10.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/$module"]

[tool.uv.sources]
bison-contracts = { path = "../../packages/contracts-py" }

[dependency-groups]
dev = [
    "ruff>=0.8.0",
    "mypy>=1.13.0",
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "hypothesis>=6.120.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "ASYNC", "S", "RUF"]
ignore = ["S101"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
disallow_any_explicit = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
"@ | Set-Content "$dir/pyproject.toml" -Encoding utf8

    "SERVICE_NAME = `"$name`"" |
        Set-Content "$dir/src/$module/__init__.py" -Encoding utf8

    "" | Set-Content "$dir/tests/__init__.py" -Encoding utf8
}

Write-Host "$($NodeServices.Count) Node and $($PythonServices.Count) Python services scaffolded."

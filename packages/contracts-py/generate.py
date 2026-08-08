import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT.parent / "contracts" / "generated" / "bison-contracts.schema.json"
OUT_DIR = ROOT / "src" / "bison_contracts"
OUT_FILE = OUT_DIR / "models.py"


def main() -> int:
    if not SCHEMA.exists():
        sys.stderr.write(
            f"Schema not found at {SCHEMA}\n"
            "Run `pnpm --filter @bison/contracts build` first.\n"
        )
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "datamodel-codegen",
            "--input", str(SCHEMA),
            "--input-file-type", "jsonschema",
            "--output", str(OUT_FILE),
            "--output-model-type", "pydantic_v2.BaseModel",
            "--target-python-version", "3.12",
            "--use-standard-collections",
            "--use-union-operator",
            "--use-schema-description",
            "--enum-field-as-literal", "one",
            "--collapse-root-models",
            "--disable-timestamp",
            "--formatters", "black", "isort",
        ],
        check=False,
    )

    if result.returncode != 0:
        return result.returncode

    init = OUT_DIR / "__init__.py"
    init.write_text("from bison_contracts.models import *\n", encoding="utf8")

    sys.stdout.write(f"Pydantic models written to {OUT_FILE}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

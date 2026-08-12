import json

from bison_probe.capabilities import run_probes


def main() -> None:
    print(json.dumps(run_probes()))


if __name__ == "__main__":
    main()

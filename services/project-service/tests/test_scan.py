from __future__ import annotations

from pathlib import Path

from project_service.scan import scan_directory
from project_service.secretscan import scan_text


def build(root: Path, files: dict[str, str]) -> None:
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")


def test_ignored_directories_are_pruned(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "src/app.py": "x = 1\n",
            "node_modules/pkg/index.js": "junk\n",
            ".git/config": "junk\n",
            "dist/bundle.js": "junk\n",
        },
    )

    result = scan_directory(tmp_path)

    assert result.file_tree == ["src/app.py"]
    assert result.total_files == 1
    assert result.skipped_directories == [".git", "dist", "node_modules"]


def test_scan_is_deterministic(tmp_path: Path) -> None:
    build(tmp_path, {"b.py": "y = 2\n", "a.py": "x = 1\n", "pkg/c.py": "z = 3\n"})

    assert scan_directory(tmp_path) == scan_directory(tmp_path)


def test_unparseable_file_counts_but_is_not_confirmed(tmp_path: Path) -> None:
    build(tmp_path, {"good.py": "def f():\n    return 1\n", "bad.py": "def f(:\n"})

    languages = {entry.language: entry for entry in scan_directory(tmp_path).languages}

    assert languages["python"].files == 2
    assert languages["python"].parsed == 1


def test_shebang_overrides_missing_extension(tmp_path: Path) -> None:
    build(tmp_path, {"deploy": "#!/usr/bin/env bash\necho hi\n"})

    languages = {entry.language for entry in scan_directory(tmp_path).languages}

    assert languages == {"bash"}


def test_entry_point_requires_a_real_guard_not_a_substring(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "real.py": 'def run():\n    return 1\n\n\nif __name__ == "__main__":\n    run()\n',
            "fake.py": "MESSAGE = \"if __name__ == '__main__'\"\n",
            "nested.py": 'def outer():\n    if __name__ == "__main__":\n        pass\n',
        },
    )

    assert scan_directory(tmp_path).entry_points == ["real.py"]


def test_go_entry_point_detected_from_syntax(tmp_path: Path) -> None:
    build(tmp_path, {"cmd/run.go": "package main\n\nfunc main() {\n}\n"})

    assert scan_directory(tmp_path).entry_points == ["cmd/run.go"]


def test_dependency_manifests_are_parsed_per_ecosystem(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "package.json": '{"dependencies":{"react":"^18"},"devDependencies":{"vite":"^5"}}',
            "pyproject.toml": '[project]\nname="d"\ndependencies=["fastapi>=0.115","httpx"]\n',
            "requirements.txt": "requests==2.31.0\n# note\npydantic[email]>=2\n",
            "go.mod": "module d\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)\n",
        },
    )

    manifests = {entry.path: entry for entry in scan_directory(tmp_path).dependency_manifests}

    assert manifests["package.json"].dependencies == ["react", "vite"]
    assert manifests["pyproject.toml"].dependencies == ["fastapi", "httpx"]
    assert manifests["requirements.txt"].dependencies == ["pydantic", "requests"]
    assert manifests["go.mod"].dependencies == ["github.com/gin-gonic/gin"]


def test_malformed_manifest_is_reported_not_fatal(tmp_path: Path) -> None:
    build(tmp_path, {"package.json": "{not json at all"})

    manifests = scan_directory(tmp_path).dependency_manifests

    assert len(manifests) == 1
    assert manifests[0].ecosystem == "unparsed"
    assert manifests[0].dependencies == []


def test_secret_value_is_never_retained(tmp_path: Path) -> None:
    planted = "a9F3kZ2qLp7XvB1nR4tY"
    build(tmp_path, {"settings.py": f'API_KEY = "{planted}"\n'})

    findings = scan_directory(tmp_path).secret_findings

    assert len(findings) == 1
    assert findings[0].kind == "assigned_api_key"
    assert findings[0].line == 1
    assert planted not in findings[0].preview
    assert str(len(planted)) in findings[0].preview


def test_placeholders_and_environment_lookups_are_not_flagged() -> None:
    lines = [
        'API_KEY = os.environ["API_KEY"]',
        'password = "changeme"',
        'token: "${VAULT_TOKEN}"',
        'secret = "aaaaaaaaaaaa"',
    ]

    assert all(scan_text("f.py", line) == [] for line in lines)


def test_high_signal_literals_are_flagged() -> None:
    assert scan_text("a.txt", "key AKIAIOSFODNN7EXAMPLE")[0].kind == "aws_access_key"
    assert scan_text("k.pem", "-----BEGIN RSA PRIVATE KEY-----")[0].kind == "private_key_block"
    assert scan_text("k.pem", "-----BEGIN RSA PRIVATE KEY-----")[0].preview == "private_key_block"


def test_binary_content_is_not_scanned(tmp_path: Path) -> None:
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    result = scan_directory(tmp_path)

    assert result.total_files == 1
    assert result.secret_findings == []
    assert [entry.language for entry in result.languages] == ["image"]


def test_empty_directory_scans_cleanly(tmp_path: Path) -> None:
    result = scan_directory(tmp_path)

    assert result.total_files == 0
    assert result.total_size_bytes == 0
    assert result.truncated is False

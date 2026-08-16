from __future__ import annotations

from analyst_service.context import (
    AnalystContext,
    AnsweredQuestion,
    Conceive,
    LanguageTally,
    ManifestSummary,
    Material,
    PriorBrief,
    ProjectFacts,
    ScanSummary,
    SecretSighting,
    clip,
    human_bytes,
    render,
)


def facts(**overrides: object) -> ProjectFacts:
    base: dict[str, object] = {
        "name": "Ledger",
        "goal": "Reconcile invoices against payments",
        "project_type": "code",
    }
    base.update(overrides)
    return ProjectFacts(**base)  # type: ignore[arg-type]


def scan(**overrides: object) -> ScanSummary:
    base: dict[str, object] = {
        "total_files": 3,
        "total_size_bytes": 2048,
        "file_tree": ["src/main.py", "src/util.py", "README.md"],
        "languages": [LanguageTally("python", 2, 2)],
        "dependency_manifests": [],
        "entry_points": ["src/main.py"],
        "secret_findings": [],
        "skipped_directories": [],
        "truncated": False,
    }
    base.update(overrides)
    return ScanSummary(**base)  # type: ignore[arg-type]


def context(**overrides: object) -> AnalystContext:
    base: dict[str, object] = {
        "project": facts(),
        "conceive": Conceive(revision_number=0, blocks=[]),
    }
    base.update(overrides)
    return AnalystContext(**base)  # type: ignore[arg-type]


def test_clip_leaves_short_text_alone() -> None:
    assert clip("  hello  ", 20) == "hello"


def test_clip_marks_what_it_removed() -> None:
    trimmed = clip("a" * 40, 10)

    assert trimmed.startswith("a" * 10)
    assert "truncated" in trimmed


def test_human_bytes_scales() -> None:
    assert human_bytes(512) == "512 B"
    assert human_bytes(2048) == "2.0 KB"
    assert human_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_project_facts_are_always_present() -> None:
    rendered = render(context())

    assert "PROJECT" in rendered
    assert "Reconcile invoices against payments" in rendered


def test_empty_conceive_says_so() -> None:
    rendered = render(context())

    assert "CONCEIVE (revision 0)" in rendered
    assert "empty" in rendered


def test_markdown_block_is_rendered() -> None:
    conceive = Conceive(revision_number=3, blocks=[{"type": "markdown", "text": "Match by amount"}])
    rendered = render(context(conceive=conceive))

    assert "CONCEIVE (revision 3)" in rendered
    assert "Match by amount" in rendered


def test_unknown_block_type_is_dropped() -> None:
    conceive = Conceive(revision_number=1, blocks=[{"type": "video", "src": "clip.mp4"}])
    rendered = render(context(conceive=conceive))

    assert "clip.mp4" not in rendered
    assert "video" not in rendered


def test_file_ref_block_carries_its_note() -> None:
    conceive = Conceive(
        revision_number=1,
        blocks=[
            {"type": "file_ref", "material_id": "m1", "path": "src/main.py", "note": "start here"}
        ],
    )
    rendered = render(context(conceive=conceive))

    assert "[file m1:src/main.py]" in rendered
    assert "start here" in rendered


def test_secret_findings_report_location_and_kind() -> None:
    material = Material(
        material_id="m1",
        kind="folder",
        scan=scan(secret_findings=[SecretSighting("config/settings.py", 14, "aws_key")]),
    )
    rendered = render(context(materials=[material]))

    assert "aws_key at config/settings.py:14" in rendered
    assert "1 flagged" in rendered


def test_dependency_lists_are_capped_and_counted() -> None:
    manifest = ManifestSummary("pyproject.toml", "pypi", [f"pkg{n}" for n in range(40)])
    material = Material(material_id="m1", kind="folder", scan=scan(dependency_manifests=[manifest]))
    rendered = render(context(materials=[material]))

    assert "pkg0" in rendered
    assert "pkg39" not in rendered
    assert "(+15 more)" in rendered


def test_link_material_needs_no_scan() -> None:
    material = Material(
        material_id="m2",
        kind="link",
        url="https://example.com/spec",
        note="the invoice format",
    )
    rendered = render(context(materials=[material]))

    assert "https://example.com/spec" in rendered
    assert "the invoice format" in rendered


def test_answers_carry_their_reason() -> None:
    answered = AnsweredQuestion(1, "Which bank?", "the format differs per bank", "Equity")
    rendered = render(context(answers=[answered]))

    assert "the format differs per bank" in rendered
    assert "Equity" in rendered


def test_prior_brief_lists_unresolved_fields() -> None:
    prior = PriorBrief(
        1, "Reconciles invoices", "match invoices to payments", ["target_environment"]
    )
    rendered = render(context(prior=prior))

    assert "PREVIOUS BRIEF" in rendered
    assert "target_environment" in rendered


def test_tree_shrinks_before_anything_else_is_lost() -> None:
    material = Material(
        material_id="m1",
        kind="folder",
        scan=scan(
            total_files=400,
            file_tree=[f"src/module_{n:03d}/handler.py" for n in range(400)],
        ),
    )
    conceive = Conceive(revision_number=2, blocks=[{"type": "markdown", "text": "Match by amount"}])
    ctx = context(materials=[material], conceive=conceive)

    generous = render(ctx)
    squeezed = render(ctx, budget=900)

    assert len(squeezed) <= 900
    assert squeezed.count("handler.py") < generous.count("handler.py")
    assert "CONCEIVE (revision 2)" in squeezed
    assert "Match by amount" in squeezed
    assert "Reconcile invoices against payments" in squeezed


def test_budget_of_zero_still_returns_something() -> None:
    rendered = render(context(), budget=0)

    assert "truncated" in rendered

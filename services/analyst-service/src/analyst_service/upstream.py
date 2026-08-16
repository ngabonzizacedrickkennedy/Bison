from __future__ import annotations

from typing import Any

import httpx

from analyst_service.context import (
    AnsweredQuestion,
    Conceive,
    LanguageTally,
    ManifestSummary,
    Material,
    PriorBrief,
    ProjectFacts,
    ScanSummary,
    SecretSighting,
)

SCANNED_KINDS = frozenset({"folder", "file"})


class UpstreamError(RuntimeError):
    def __init__(self, service: str, detail: str) -> None:
        super().__init__(f"{service}: {detail}")
        self.service = service
        self.detail = detail


class ProjectNotFoundError(UpstreamError):
    def __init__(self, project_id: str) -> None:
        super().__init__("project-service", f"project {project_id} not found")


def text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def whole(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def strings(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def objects(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]


def to_project_facts(payload: dict[str, Any]) -> ProjectFacts:
    return ProjectFacts(
        name=text(payload, "name"),
        goal=text(payload, "goal"),
        project_type=text(payload, "project_type"),
        description=optional_text(payload, "description"),
        target_environment=optional_text(payload, "target_environment"),
        constraints=strings(payload, "constraints"),
        do_not_touch=strings(payload, "do_not_touch"),
        sensitivity_flags=strings(payload, "sensitivity_flags"),
        success_criteria=strings(payload, "success_criteria"),
        referenced_project_ids=strings(payload, "referenced_project_ids"),
    )


def to_scan_summary(payload: dict[str, Any]) -> ScanSummary:
    return ScanSummary(
        total_files=whole(payload, "total_files"),
        total_size_bytes=whole(payload, "total_size_bytes"),
        file_tree=strings(payload, "file_tree"),
        languages=[
            LanguageTally(
                language=text(entry, "language"),
                files=whole(entry, "files"),
                parsed=whole(entry, "parsed"),
            )
            for entry in objects(payload, "languages")
        ],
        dependency_manifests=[
            ManifestSummary(
                path=text(entry, "path"),
                ecosystem=text(entry, "ecosystem"),
                dependencies=strings(entry, "dependencies"),
            )
            for entry in objects(payload, "dependency_manifests")
        ],
        entry_points=strings(payload, "entry_points"),
        secret_findings=[
            SecretSighting(
                path=text(entry, "path"),
                line=whole(entry, "line"),
                kind=text(entry, "kind"),
            )
            for entry in objects(payload, "secret_findings")
        ],
        skipped_directories=strings(payload, "skipped_directories"),
        truncated=payload.get("truncated") is True,
    )


def to_material(payload: dict[str, Any], scan: dict[str, Any] | None) -> Material:
    return Material(
        material_id=text(payload, "id"),
        kind=text(payload, "kind"),
        caption=optional_text(payload, "caption"),
        note=optional_text(payload, "note"),
        url=optional_text(payload, "url"),
        scan=to_scan_summary(scan) if scan is not None else None,
    )


class ProjectClient:
    def __init__(self, base_url: str, timeout_seconds: float, connect_timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._client = httpx.AsyncClient(base_url=self._base_url)

    async def close(self) -> None:
        await self._client.aclose()

    async def project(self, project_id: str) -> ProjectFacts:
        payload = await self._object(f"/projects/{project_id}", project_id)
        return to_project_facts(payload)

    async def conceive(self, project_id: str) -> Conceive:
        payload = await self._object(f"/projects/{project_id}/conceive", project_id)

        return Conceive(
            revision_number=whole(payload, "revision_number"),
            blocks=objects(payload, "blocks"),
        )

    async def materials(self, project_id: str) -> list[Material]:
        payload = await self._array(f"/projects/{project_id}/materials", project_id)
        collected: list[Material] = []

        for entry in payload:
            material_id = text(entry, "id")
            scan = None

            if text(entry, "kind") in SCANNED_KINDS and material_id:
                scan = await self._optional_object(f"/materials/{material_id}/scan")

            collected.append(to_material(entry, scan))

        return collected

    async def answers(self, project_id: str) -> list[AnsweredQuestion]:
        payload = await self._array(f"/projects/{project_id}/clarifications", project_id)
        collected: list[AnsweredQuestion] = []

        for request in payload:
            round_number = whole(request, "round")

            for question in objects(request, "questions"):
                if question.get("answered") is not True:
                    continue

                reply = question.get("answer")

                collected.append(
                    AnsweredQuestion(
                        round=round_number,
                        text=text(question, "text"),
                        why_asked=text(question, "why_asked"),
                        answer=reply if isinstance(reply, str) else "",
                    )
                )

        return collected

    async def prior_brief(self, project_id: str) -> PriorBrief | None:
        path = f"/projects/{project_id}/brief"
        response = await self._fetch(path)

        if response.status_code == httpx.codes.NOT_FOUND:
            return None

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError("project-service", f"{path} responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, dict):
            return None

        return PriorBrief(
            round=whole(parsed, "round"),
            summary=text(parsed, "summary"),
            interpreted_goal=text(parsed, "interpreted_goal"),
            unresolved_fields=strings(parsed, "unresolved_fields"),
        )

    async def store_brief(self, project_id: str, body: dict[str, Any]) -> str:
        try:
            response = await self._client.post(
                f"/projects/{project_id}/briefs", json=body, timeout=self._timeout
            )
        except httpx.HTTPError as error:
            raise UpstreamError("project-service", "storing the brief failed") from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError(
                "project-service", f"storing the brief responded {response.status_code}"
            )

        parsed: Any = response.json()

        return text(parsed, "id") if isinstance(parsed, dict) else ""

    async def _fetch(self, path: str) -> httpx.Response:
        try:
            return await self._client.get(path, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise UpstreamError("project-service", f"{path} unreachable") from error

    async def _object(self, path: str, project_id: str) -> dict[str, Any]:
        response = await self._fetch(path)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProjectNotFoundError(project_id)

        return self._as_object(response, path)

    async def _optional_object(self, path: str) -> dict[str, Any] | None:
        response = await self._fetch(path)

        if response.status_code == httpx.codes.NOT_FOUND:
            return None

        return self._as_object(response, path)

    async def _array(self, path: str, project_id: str) -> list[dict[str, Any]]:
        response = await self._fetch(path)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProjectNotFoundError(project_id)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError("project-service", f"{path} responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, list):
            raise UpstreamError("project-service", f"{path} returned a non-array body")

        return [item for item in parsed if isinstance(item, dict)]

    @staticmethod
    def _as_object(response: httpx.Response, path: str) -> dict[str, Any]:
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError("project-service", f"{path} responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, dict):
            raise UpstreamError("project-service", f"{path} returned a non-object body")

        return parsed

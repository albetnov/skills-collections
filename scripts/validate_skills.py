#!/usr/bin/env python3
"""Validate the published skills in this repository.

Run inside the project's uv virtual environment:

    uv sync --locked
    uv run --locked python scripts/validate_skills.py

Checks strict YAML frontmatter, required fields and naming, local links,
reference reachability, agents/openai.yaml, and README coverage.

Exit codes:
    0  no errors (warnings fail only with --strict)
    1  validation errors
    2  not running inside the project's uv virtual environment
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal
from urllib.parse import unquote

try:
    import yaml
except ModuleNotFoundError:
    print(
        "error: PyYAML is not available; run this check through the project venv:",
        file=sys.stderr,
    )
    print("  uv sync --locked", file=sys.stderr)
    print("  uv run --locked python scripts/validate_skills.py", file=sys.stderr)
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
README = REPO_ROOT / "README.md"

ALLOWED_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
# Client extensions that are valid in some harnesses even though they are not
# part of the portable Agent Skills spec.
EXTENSION_KEYS = {
    "disable-model-invocation",
    "user-invocable",
    "argument-hint",
    "model",
    "context",
    "agent",
    "hooks",
}
OPENAI_INTERFACE_KEYS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TRIGGER_RE = re.compile(
    r"\b(use when|use this when|use for|when the user|when you|triggered when)\b",
    re.IGNORECASE,
)
LOCAL_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
README_ROW_RE = re.compile(r"^\|\s*\[`([^`]+)`\]\((skills/[^)]+)\)\s*\|", re.MULTILINE)

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    path: Path
    message: str
    line: int | None = None

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "severity": self.severity,
            "code": self.code,
            "path": display_path(self.path),
            "message": self.message,
        }
        if self.line is not None:
            data["line"] = self.line
        return data


@dataclass
class SkillReport:
    skill_dir: Path
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(finding.severity == "error" for finding in self.findings)

    @property
    def warnings(self) -> int:
        return sum(finding.severity == "warning" for finding in self.findings)


class FrontmatterError(Exception):
    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of keeping the last."""


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def split_frontmatter(text: str) -> tuple[str, str, int]:
    """Return (yaml_text, body, body_start_line)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("SKILL.md must start with a '---' frontmatter line", 1)

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1 :]), index + 2

    raise FrontmatterError("frontmatter is not closed by a '---' line", 1)


def field_line(yaml_text: str, key: str) -> int:
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for offset, line in enumerate(yaml_text.splitlines()):
        if pattern.match(line):
            return offset + 2
    return 1


def yaml_error(exc: yaml.YAMLError, first_line: int = 1) -> tuple[str, int | None]:
    mark = getattr(exc, "problem_mark", None)
    line = mark.line + first_line if mark is not None else None
    problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    return str(problem).strip(), line


def iter_local_links(text: str) -> Iterable[tuple[int, str]]:
    """Yield (line number, target) for local markdown links, ignoring code fences."""
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        for match in LOCAL_LINK_RE.finditer(line):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "tel:", "data:", "#")):
                continue
            yield number, target


class SkillValidator:
    def __init__(self, skill_dir: Path) -> None:
        self.skill_dir = skill_dir
        self.skill_md = skill_dir / "SKILL.md"
        self.findings: list[Finding] = []

    def error(self, code: str, message: str, path: Path | None = None, line: int | None = None) -> None:
        self.findings.append(Finding("error", code, path or self.skill_md, message, line))

    def warning(self, code: str, message: str, path: Path | None = None, line: int | None = None) -> None:
        self.findings.append(Finding("warning", code, path or self.skill_md, message, line))

    def run(self) -> SkillReport:
        if not self.skill_md.is_file():
            self.error("skill-md-missing", "missing SKILL.md", self.skill_dir)
            return SkillReport(self.skill_dir, self.findings)

        try:
            text = self.skill_md.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            self.error("skill-md-unreadable", f"cannot read SKILL.md: {exc}")
            return SkillReport(self.skill_dir, self.findings)

        try:
            yaml_text, body, body_line = split_frontmatter(text)
        except FrontmatterError as exc:
            self.error("frontmatter-delimiters", str(exc), line=exc.line)
            return SkillReport(self.skill_dir, self.findings)

        data: object = None
        parsed = False
        try:
            data = yaml.load(yaml_text, Loader=UniqueKeyLoader)
            parsed = True
        except yaml.YAMLError as exc:
            problem, line = yaml_error(exc, first_line=2)
            self.error("frontmatter-yaml", f"invalid YAML: {problem}", line=line)

        if parsed:
            if data is None:
                self.error("frontmatter-empty", "frontmatter is empty")
            elif not isinstance(data, dict):
                self.error(
                    "frontmatter-type",
                    f"frontmatter must be a YAML mapping, got {type(data).__name__}",
                )
            else:
                self.check_frontmatter(yaml_text, data)

        self.check_body(body, body_line)
        self.check_links(body, body_line)
        self.check_openai_yaml()
        return SkillReport(self.skill_dir, self.findings)

    def check_frontmatter(self, yaml_text: str, data: dict[object, object]) -> None:
        for key in data:
            if not isinstance(key, str):
                self.error(
                    "frontmatter-key-type",
                    f"frontmatter keys must be strings, got {type(key).__name__}",
                )

        for key in sorted(k for k in data if isinstance(k, str)):
            if key in ALLOWED_KEYS or key in EXTENSION_KEYS:
                continue
            self.warning(
                "frontmatter-unknown-key",
                f"unrecognized frontmatter key {key!r}; remove it or add it to the validator",
                line=field_line(yaml_text, key),
            )

        name = data.get("name")
        if name is None:
            self.error("name-missing", "missing required frontmatter field 'name'")
        elif not isinstance(name, str):
            self.error("name-type", f"'name' must be a string, got {type(name).__name__}")
        else:
            self.check_name(yaml_text, name)

        description = data.get("description")
        if description is None:
            self.error("description-missing", "missing required frontmatter field 'description'")
        elif not isinstance(description, str):
            self.error(
                "description-type",
                f"'description' must be a string, got {type(description).__name__}",
            )
        else:
            self.check_description(yaml_text, description)

        self.check_optional_fields(yaml_text, data)

    def check_name(self, yaml_text: str, name: str) -> None:
        line = field_line(yaml_text, "name")
        if not name.strip():
            self.error("name-empty", "'name' must not be blank", line=line)
            return
        if name != name.strip():
            self.error("name-whitespace", "'name' must not start or end with whitespace", line=line)
        if len(name) > 64:
            self.error("name-length", f"'name' is {len(name)} characters; maximum is 64", line=line)
        if not NAME_RE.fullmatch(name):
            self.error(
                "name-format",
                "'name' must be lowercase kebab-case (a-z, 0-9, single hyphens), "
                "with no leading, trailing, or consecutive hyphens",
                line=line,
            )
        if name != self.skill_dir.name:
            self.error(
                "name-directory-mismatch",
                f"'name' is {name!r} but the directory is {self.skill_dir.name!r}",
                line=line,
            )

    def check_description(self, yaml_text: str, description: str) -> None:
        line = field_line(yaml_text, "description")
        if not description.strip():
            self.error("description-empty", "'description' must not be blank", line=line)
            return
        if len(description) > 1024:
            self.error(
                "description-length",
                f"'description' is {len(description)} characters; maximum is 1024",
                line=line,
            )
        if "<" in description or ">" in description:
            self.warning(
                "description-angle-brackets",
                "'description' contains '<' or '>'; some harnesses reject angle brackets",
                line=line,
            )
        if not TRIGGER_RE.search(description):
            self.warning(
                "description-trigger",
                "'description' has no trigger phrase such as 'Use when ...'",
                line=line,
            )
        if len(description) < 50:
            self.warning(
                "description-short",
                f"'description' is only {len(description)} characters; state the capability and its triggers",
                line=line,
            )

    def check_optional_fields(self, yaml_text: str, data: dict[object, object]) -> None:
        license_value = data.get("license")
        if license_value is not None and not isinstance(license_value, str):
            self.error(
                "license-type",
                f"'license' must be a string, got {type(license_value).__name__}",
                line=field_line(yaml_text, "license"),
            )

        compatibility = data.get("compatibility")
        if compatibility is not None:
            line = field_line(yaml_text, "compatibility")
            if not isinstance(compatibility, str):
                self.error(
                    "compatibility-type",
                    f"'compatibility' must be a string, got {type(compatibility).__name__}",
                    line=line,
                )
            elif len(compatibility) > 500:
                self.error(
                    "compatibility-length",
                    f"'compatibility' is {len(compatibility)} characters; maximum is 500",
                    line=line,
                )

        metadata = data.get("metadata")
        if metadata is not None:
            line = field_line(yaml_text, "metadata")
            if not isinstance(metadata, dict):
                self.error(
                    "metadata-type",
                    f"'metadata' must be a mapping, got {type(metadata).__name__}",
                    line=line,
                )
            else:
                for key, value in metadata.items():
                    if not isinstance(key, str) or not isinstance(value, str):
                        self.warning(
                            "metadata-value-type",
                            "'metadata' keys and values should be strings",
                            line=line,
                        )
                        break

        allowed_tools = data.get("allowed-tools")
        if allowed_tools is not None:
            line = field_line(yaml_text, "allowed-tools")
            if isinstance(allowed_tools, list) and all(
                isinstance(item, str) for item in allowed_tools
            ):
                self.warning(
                    "allowed-tools-list",
                    "'allowed-tools' is a list; prefer a space-separated string for portability",
                    line=line,
                )
            elif not isinstance(allowed_tools, str):
                self.error(
                    "allowed-tools-type",
                    "'allowed-tools' must be a space-separated string",
                    line=line,
                )

        for key in ("disable-model-invocation", "user-invocable"):
            value = data.get(key)
            if value is not None and not isinstance(value, bool):
                self.error(
                    f"{key}-type",
                    f"'{key}' must be a boolean, got {type(value).__name__}",
                    line=field_line(yaml_text, key),
                )

    def check_body(self, body: str, body_line: int) -> None:
        if not body.strip():
            self.error("skill-body-empty", "SKILL.md has no body after the frontmatter")
            return
        stripped = body.lstrip()
        if not stripped.startswith("# "):
            self.warning(
                "body-heading",
                "SKILL.md body should start with a level-1 heading",
                line=body_line,
            )
        line_count = len(body.splitlines())
        if line_count > 500:
            self.warning(
                "body-length",
                f"SKILL.md body is {line_count} lines; split detail into references/",
            )

    def check_links(self, body: str, body_line: int) -> None:
        reachable: set[Path] = set()
        visited: set[Path] = set()
        queue: deque[tuple[Path, str, int]] = deque([(self.skill_md, body, body_line)])
        skill_root = self.skill_dir.resolve()

        while queue:
            source, text, line_offset = queue.popleft()
            source_resolved = source.resolve()
            if source_resolved in visited:
                continue
            visited.add(source_resolved)

            for number, target in iter_local_links(text):
                file_line = line_offset + number - 1
                clean = unquote(target.split("#", 1)[0])
                if not clean:
                    continue
                resolved = (source.parent / clean).resolve()
                if not resolved.is_relative_to(skill_root):
                    self.error(
                        "link-escapes-skill",
                        f"link target escapes the skill directory: {target}",
                        source,
                        file_line,
                    )
                    continue
                if not resolved.is_file():
                    self.error(
                        "link-missing",
                        f"link target does not exist: {target}",
                        source,
                        file_line,
                    )
                    continue
                reachable.add(resolved)
                if resolved.suffix.lower() in {".md", ".markdown"} and resolved not in visited:
                    try:
                        reference_text = resolved.read_text(encoding="utf-8-sig")
                    except (OSError, UnicodeDecodeError) as exc:
                        self.error(
                            "reference-unreadable",
                            f"cannot read linked reference: {exc}",
                            resolved,
                        )
                    else:
                        queue.append((resolved, reference_text, 1))

        for subdir in ("references", "assets", "scripts"):
            root = self.skill_dir / subdir
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if path.resolve() not in reachable:
                    self.warning(
                        "orphan-file",
                        f"{path.relative_to(self.skill_dir).as_posix()} is never linked "
                        "from SKILL.md or a reachable reference",
                        path,
                    )

    def check_openai_yaml(self) -> None:
        path = self.skill_dir / "agents" / "openai.yaml"
        if not path.is_file():
            self.warning("openai-yaml-missing", "agents/openai.yaml is missing", path)
            return
        try:
            data = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=UniqueKeyLoader)
        except (OSError, UnicodeDecodeError) as exc:
            self.error("openai-yaml-unreadable", f"cannot read agents/openai.yaml: {exc}", path)
            return
        except yaml.YAMLError as exc:
            problem, line = yaml_error(exc)
            self.error("openai-yaml-invalid", f"invalid YAML: {problem}", path, line)
            return

        if not isinstance(data, dict):
            self.error("openai-yaml-type", "agents/openai.yaml must be a mapping", path)
            return
        interface = data.get("interface")
        if not isinstance(interface, dict):
            self.error("openai-yaml-interface", "agents/openai.yaml needs an 'interface' mapping", path)
            return

        unknown = sorted(
            key for key in interface if isinstance(key, str) and key not in OPENAI_INTERFACE_KEYS
        )
        for key in unknown:
            self.warning(
                "openai-yaml-unknown-key",
                f"unrecognized interface key {key!r}",
                path,
            )

        display = interface.get("display_name")
        short = interface.get("short_description")
        if not isinstance(display, str) or not display.strip():
            self.error("openai-yaml-display-name", "interface.display_name must be a non-empty string", path)
        if not isinstance(short, str) or not short.strip():
            self.error(
                "openai-yaml-short-description",
                "interface.short_description must be a non-empty string",
                path,
            )
        elif not 25 <= len(short) <= 64:
            self.warning(
                "openai-yaml-short-description-length",
                f"interface.short_description is {len(short)} characters; expected 25-64",
                path,
            )

        default_prompt = interface.get("default_prompt")
        if isinstance(default_prompt, str) and default_prompt:
            if f"${self.skill_dir.name}" not in default_prompt:
                self.warning(
                    "openai-yaml-default-prompt",
                    f"interface.default_prompt should mention ${self.skill_dir.name}",
                    path,
                )


def check_readme(skill_names: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    if not README.is_file():
        return [
            Finding(
                "warning",
                "readme-missing",
                README,
                "README.md is missing; the published skill index cannot be checked",
            )
        ]

    text = README.read_text(encoding="utf-8-sig")
    rows: dict[str, tuple[str, int]] = {}
    for match in README_ROW_RE.finditer(text):
        name, target = match.group(1), match.group(2)
        line = text.count("\n", 0, match.start()) + 1
        rows[name] = (target, line)
        expected = f"skills/{name}/SKILL.md"
        if target != expected:
            findings.append(
                Finding(
                    "error",
                    "readme-row-target",
                    README,
                    f"row for {name!r} links to {target!r}; expected {expected!r}",
                    line,
                )
            )
        if not (REPO_ROOT / target).is_file():
            findings.append(
                Finding(
                    "error",
                    "readme-row-missing",
                    README,
                    f"row for {name!r} points to a missing file: {target}",
                    line,
                )
            )

    for name, (_, line) in rows.items():
        if name not in skill_names:
            findings.append(
                Finding(
                    "error",
                    "readme-stale-skill",
                    README,
                    f"README lists {name!r}, but skills/{name}/ does not exist",
                    line,
                )
            )
    for name in sorted(skill_names - rows.keys()):
        findings.append(
            Finding(
                "warning",
                "readme-missing-row",
                README,
                f"README has no row for skill {name!r}",
            )
        )
    return findings


def require_project_venv() -> None:
    expected = (REPO_ROOT / ".venv").resolve()
    active = os.environ.get("VIRTUAL_ENV")
    if active and Path(active).resolve() == expected:
        return
    print("error: run this check inside the project's uv virtual environment", file=sys.stderr)
    print("  uv sync --locked", file=sys.stderr)
    print("  uv run --locked python scripts/validate_skills.py", file=sys.stderr)
    raise SystemExit(2)


def print_finding(finding: Finding) -> None:
    location = display_path(finding.path)
    if finding.line is not None:
        location += f":{finding.line}"
    print(f"  {finding.severity:<7} {finding.code:<30} {location} - {finding.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the published skills in this repository.")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    require_project_venv()

    if not SKILLS_DIR.is_dir():
        print(f"error: skills directory not found: {display_path(SKILLS_DIR)}", file=sys.stderr)
        return 1

    skill_dirs = sorted(
        path for path in SKILLS_DIR.iterdir() if path.is_dir() and not path.name.startswith(".")
    )
    reports = [SkillValidator(skill_dir).run() for skill_dir in skill_dirs]
    readme_findings = check_readme({report.skill_dir.name for report in reports})
    all_findings = [finding for report in reports for finding in report.findings]
    all_findings.extend(readme_findings)

    errors = sum(finding.severity == "error" for finding in all_findings)
    warnings = sum(finding.severity == "warning" for finding in all_findings)
    failed = sum(report.errors > 0 for report in reports)
    ok = errors == 0 and not (args.strict and warnings > 0)

    if args.json:
        payload = {
            "ok": ok,
            "strict": args.strict,
            "summary": {
                "skills": len(reports),
                "failed": failed,
                "errors": errors,
                "warnings": warnings,
            },
            "findings": [finding.as_dict() for finding in all_findings],
        }
        print(json.dumps(payload, indent=2))
        return 0 if ok else 1

    for report in reports:
        status = "FAIL" if report.errors else ("WARN" if report.findings else "OK")
        print(f"{status:<4} {display_path(report.skill_dir)}")
        for finding in report.findings:
            print_finding(finding)

    if readme_findings:
        status = "FAIL" if any(f.severity == "error" for f in readme_findings) else "WARN"
        print(f"{status:<4} {display_path(README)}")
        for finding in readme_findings:
            print_finding(finding)

    print()
    print(f"{len(reports)} skills checked: {failed} failed, {len(reports) - failed} passed")
    print(f"{errors} errors, {warnings} warnings")
    if warnings:
        if args.strict:
            print("warnings fail the check because --strict is set")
        elif ok:
            print("warnings do not fail the check; use --strict to gate them")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# AGENTS.md

Read the `writing-for-agents` skill before writing or editing a skill, this file, or the README. It owns the writing rules; this file records only repository-specific mechanics.

## Repository

- `skills/` is the published surface. Everything else is internal.
- Each skill is `skills/<name>/SKILL.md`; the directory name equals the frontmatter `name`.
- The README table is the human index; add or remove a skill there in the same change.

## Skill mechanics

- Frontmatter requires `name` and `description`; quote any value containing `: ` or `#`.
- Link reference files from the SKILL.md router table. Every file under `references/`, `assets/`, and `scripts/` must be reachable from SKILL.md or a reachable reference.
- `agents/openai.yaml` mirrors the skill: `interface.display_name` plus a 25-64 character `interface.short_description`.

## Checks

Python tooling runs only through the project venv:

```bash
uv sync --locked
uv run --locked python scripts/validate_skills.py
```

`--strict` fails on warnings; `--json` prints machine-readable findings.

## Dependency changes

Edit `pyproject.toml`, then review the lock diff and audit the result:

```bash
uv lock
uv audit --preview-features audit
```

Installs use the versions and hashes in `uv.lock`. For the opt-in sync-time malware check:

```bash
UV_MALWARE_CHECK=1 uv sync --locked
```

`exclude-newer = "7 days"` keeps newly uploaded releases out of fresh resolutions.

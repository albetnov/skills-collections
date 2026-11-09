# Skills Collections

My personal collection of agent skills. A skill is a folder of instructions an AI coding agent loads when a task matches its description.

Only [`skills/`](skills/) is published here. Everything else in the repository is internal.

## Skills

| Skill | Use when |
| --- | --- |
| [`android-app-architecture`](skills/android-app-architecture/SKILL.md) | Laying out feature modules and layers, placing UI/domain/data code, Metro graphs and bindings, scoping, or Compose ViewModel injection. |
| [`android-data-layer`](skills/android-data-layer/SKILL.md) | Wiring an offline-first cache: Store5 streams, Room source of truth, Retrofit fetchers, write outbox, error mapping. |
| [`android-viewmodel-state`](skills/android-viewmodel-state/SKILL.md) | Choosing vanilla snapshot State or Orbit MVI for a screen, exposing immutable ViewModel state, one-shot events, or container tests. |
| [`backend-upload-verifier`](skills/backend-upload-verifier/SKILL.md) | Designing or reviewing upload admission: magic bytes and dimension limits, presigned S3/R2/GCS policies, checksums, and safe serving of user files. |
| [`client-compute-architect`](skills/client-compute-architect/SKILL.md) | Designing browser-native image/video processing, client PDF/CSV exports, and direct-to-storage uploads with hashing, retry, and offline queues. |
| [`fiber-v3`](skills/fiber-v3/SKILL.md) | Writing, reviewing, or debugging Fiber v3 code: routing, middleware, `Ctx` lifetime, concurrency, binding, app lifecycle, the Fiber client. |
| [`fiber-v3-architecture`](skills/fiber-v3-architecture/SKILL.md) | Designing or restructuring a Fiber v3 app: feature modules, REST contracts, status codes, error envelopes, pagination, idempotency, OpenAPI. |
| [`solid-v2`](skills/solid-v2/SKILL.md) | Writing, reviewing, or debugging Solid 2.0 code: signals, effects, stores, async boundaries, SSR, routing, server functions, forms, and tests. |

## Install

Skills are installed with the [`skills`](https://skills.sh) CLI, no install needed:

```bash
# Every skill in this repo
npx skills add albetnov/skills-collections

# A single skill
npx skills add albetnov/skills-collections --skill fiber-v3

# For specific agents
npx skills add albetnov/skills-collections --skill fiber-v3 -a claude-code -a opencode

# Available across all projects
npx skills add albetnov/skills-collections -g
```

The CLI detects your coding agents and asks which skills and agents to install to. Skills go into the current project by default.

## Use without installing

```bash
npx skills use albetnov/skills-collections@fiber-v3

# Launch an agent directly with the skill
npx skills use albetnov/skills-collections@fiber-v3 --agent claude-code
```

## Manage

```bash
npx skills list              # Show installed skills
npx skills check             # Check for updates
npx skills update            # Update installed skills
npx skills remove fiber-v3   # Remove a skill
```

## Acknowledgements

The `android-app-architecture`, `android-data-layer`, and `android-viewmodel-state` skills were initially derived from [awesome-android-agent-skills](https://github.com/new-silvermoon/awesome-android-agent-skills), then substantially rewritten for a modern pure-Android stack. See [LICENSE](LICENSE) for the Apache-2.0 terms and attribution notice.

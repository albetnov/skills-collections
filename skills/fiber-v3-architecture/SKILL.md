---
name: fiber-v3-architecture
description: Fiber v3 application architecture and REST API contracts. Use when designing or restructuring a Fiber v3 project: feature-module layout, route grouping and versioning, REST resource design, HTTP status/header conventions, error envelopes, pagination, idempotency, or OpenAPI specs.
---

# Fiber v3 architecture

Prescriptive architecture for new or restructured Fiber v3 applications. Runtime correctness lives in the `fiber-v3` skill; use it for Ctx lifetime, concurrency, binding, middleware mechanics, and shutdown details.

## Core decisions

- Organize by feature module. A module owns its routes, handlers, service, repository, DTOs, and models.
- One dependency direction: handler -> service -> repository. Handlers speak HTTP; services own business rules; repositories own persistence.
- Register modules into `/api/v1` route groups. A new major version gets a new group, not a version branch inside a handler.
- Success responses return the resource or collection directly. Errors use one nested envelope: `{"error": {"code", "message", "request_id", "details"}}`.
- Install a custom `fiber.Config.ErrorHandler` that emits the envelope, preserves `Allow` on `405`, and hides panic details. Framework 404/405 responses use it; `501` for an unknown method is sent before middleware and bypasses it.
- `400` means malformed, `422` means field validation, `404` means missing, `409` means state conflict. Do not collapse client errors into `400`.
- `Authorization: Bearer`, `X-Request-ID`, `Idempotency-Key` for retryable unsafe writes, `Location` on `201`, `Retry-After` on `429`/`503`, and `X-RateLimit-*` on rate-limited APIs.
- Paths are plural `kebab-case`; JSON fields and query parameters are `snake_case`. IDs are opaque strings.
- OpenAPI 3.1 lives at `api/openapi.yaml` and is the contract. Change the spec before or with the handler.
- Inject dependencies at startup. No package-level `app`, `db`, or logger globals.
- Pass `c.Context()` as the base context and derive cancellation/deadlines explicitly; it is `context.Background()` unless `SetContext` was called. Pass identity explicitly as an actor/tenant/request-ID value. `c.Context()` does not carry `Locals` unless `PassLocalsToContext` is enabled.

## Reference router

| Task | Read |
|---|---|
| Folder structure, feature modules, wiring, boundaries | [project-layout](references/project-layout.md) |
| Resources, status codes, envelope, headers, versioning, pagination, idempotency | [http-contract](references/http-contract.md) |
| OpenAPI 3.1 workflow and naming | [openapi](references/openapi.md) |
| Starter spec | [assets/openapi.yaml](assets/openapi.yaml) |

For runtime rules — Ctx lifetime, goroutines, channels, mutexes, binding, middleware errors — use the `fiber-v3` skill.

## Before returning an architecture

- Every feature has one module folder; no cross-module imports of another module's internals.
- Every handler parses, calls one service method, and maps one result or error.
- Every service accepts `context.Context` plus explicit identity/tenant values and returns domain values/errors, not Fiber types.
- Every repository is hidden behind an interface owned by the consumer.
- Every endpoint is in the OpenAPI spec, including error responses.
- All errors that reach the app error handler use the envelope and a contract status; framework 404/405 and recovered panics are included, and the pre-middleware `501` is the exception.
- Every module registers into a version group; version branching stays out of handlers.
- Startup wires dependencies; shutdown closes every owned resource.

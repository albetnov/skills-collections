---
name: fiber-v3
description: "Fiber v3 Go web framework. Use when writing, reviewing, or debugging Fiber v3 code: routes and handlers, middleware and errors, Ctx lifetime and zero allocation, goroutines/channels/mutexes in handlers, binding and validation, app lifecycle, or the Fiber client."
---

# Fiber v3

Target current `github.com/gofiber/fiber/v3` only. Every rule here is for v3 code. The skill follows the current v3 docs; a project pinned to an older v3 release should verify newer APIs, behavior, and storage formats.

## Core invariants

- `fiber.Ctx` is request-scoped and pooled. Read it inside the handler. Copy a value before it escapes, or set `Immutable: true`. Values decoded by `Bind` still alias request buffers.
- A handler is `func(c fiber.Ctx) error`. Return errors; let the app's error handler write the response.
- Middleware continues with `c.Next()`. Returning before `c.Next()` stops the chain on purpose.
- `c` implements `context.Context` but never cancels. Work that may outlive the handler receives `c.Context()`.
- Register routes before `Listen`. `RebuildTree`, `RemoveRoute`, `RemoveRouteByName`, and `RemoveRouteFunc` are not thread-safe.
- Protect shared mutable state with a mutex, atomic, or channel. `app.State()` is process-local; prefork workers do not share it.
- Retain neither `*fasthttp.Request`/`*fasthttp.Response` nor Ctx-backed slices, maps, or strings after the handler returns.

## Reference router

| Task | Read |
|---|---|
| Ctx values, aliasing, pooling, release, streams | [context-lifetime](references/context-lifetime.md) |
| Goroutines, channels, mutexes, worker pools, allocation | [concurrency-performance](references/concurrency-performance.md) |
| Routes, params, constraints, groups, mounts, HEAD | [routing-handlers](references/routing-handlers.md) |
| Middleware order, `Next`, errors, panic recovery | [middleware-errors](references/middleware-errors.md) |
| Config, listen, shutdown, services, state, sessions/cache cleanup | [app-lifecycle](references/app-lifecycle.md) |
| Bind, validate, extractors | [request-binding](references/request-binding.md) |
| Fiber client pools and lifecycle | [client](references/client.md) |
| Request flow, context pool, route tree, prefork internals | [internals](references/internals.md) |

For feature-module layout, REST contracts, status/header/versioning conventions, and OpenAPI, use the `fiber-v3-architecture` skill.

## Before returning code

- The import path is `github.com/gofiber/fiber/v3`.
- Every handler returns `error`; every continuing middleware calls `c.Next()`.
- No Ctx-derived value escapes the handler without a copy or `Immutable`.
- Every goroutine has `c.Context()` or a derived context, copied inputs, and a stop path.
- Shared state has one synchronization strategy; prefork state is externalized when workers need it.
- Startup and shutdown are symmetric: listeners, services, storage, worker pools, and file handles close.
- The route table is complete before the server starts.

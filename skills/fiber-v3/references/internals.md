# Internals

This file explains why the lifetime and routing rules exist. Read it when a rule seems surprising or when debugging framework-level behavior.

## App structure

A Fiber app owns:

- `Config` — body limits, timeouts, routing behavior, TLS, services, storage.
- A context pool — recycles `DefaultCtx` or a custom `Ctx`.
- The router stack — registered routes and groups.
- Mount fields — sub-app prefixes and merged routes.
- Hooks — route registration, listen, fork, mount, shutdown.

The pool is the reason Ctx is request-scoped. Reusing contexts avoids allocating one per request and is the basis of the zero-allocation design.

## Request flow

1. fasthttp receives the request.
2. `App.Handler` acquires a Ctx from the pool.
3. The Ctx is reset with the new `fasthttp.RequestCtx`.
4. The router matches method and normalized path.
5. The middleware and route handler chain runs.
6. Errors go to the app error handler.
7. The response is written.
8. The Ctx is released back to the pool.

The release step is why `c.Request()` and `c.Response()` return `nil` after the handler, and why a goroutine must not touch `c`.

## Routing and path parsing

`parseRoute` decomposes a pattern into constant segments, parameter segments, and constraints. Constraints are stored with the route and checked during matching.

Before matching, the request path is normalized as RFC 3986 Section 6.2.2 describes: percent-encoded unreserved characters are decoded, `.` and `..` segments are removed, and other escapes remain encoded with uppercase hex digits. The detection path is lowercased unless `CaseSensitive`, and trailing slashes are trimmed unless `StrictRouting`.

## Route matching

Fiber builds a `treeStack` keyed by a prefix of the route path. Before walking a route's segments, cheap checks discard candidates: leading constant bytes, slash-count bounds, and a probe constant after a parameter. Constant segments compare exactly; parameter segments extract values; constraints validate them.

Within a group, routes keep registration order. The first registered match wins. That is why fixed paths belong before parameterized paths.

## Middleware chain

Handlers run sequentially in registration order. Each handler calls `c.Next()` to invoke the next matching handler. A handler that returns without `Next` ends the chain. Errors returned by `Next` propagate back through the chain to the error handler.

## Mounting and grouping

A group is virtual: its prefix is flattened into the routes at registration. A mounted sub-app is merged into the parent router; its mount fields record the prefix. The top-level app's routing settings apply to all nested routes.

The sub-app's own error handler and views are found only under a literal mount path because the lookup compares the request path with the mount path as text. Under a parameterized mount, the nearest literal enclosing mount or the top-level app supplies them.

## Route tree rebuilds

Routes registered before startup are built into the tree once. `RebuildTree` publishes routes added since the last build and generates automatic HEAD routes. It mutates the router without synchronization, which is why runtime route changes are development-only.

## Context lifecycle

Acquire → reset → handle → error handling → release. The same Ctx object can serve another request immediately after release. `Abandon` keeps a Ctx out of the pool while a handler outlives the request; `ScheduleReclaim` returns it once both the handler and Fiber's request path are done.

A custom Ctx type that embeds `DefaultCtx` does not signal reclaim to `ReleaseCtx`. Under timeout middleware, each timed-out request with such a Ctx is not returned to the pool.

## Prefork

The master spawns children, each with `GOMAXPROCS(1)`. On Linux children use `SO_REUSEPORT`; Windows falls back to `SO_REUSEADDR`, which is not equivalent. Each child has its own memory, State, services, and in-memory storage. Cross-worker data needs `SharedStorage` or an external store.

Prefork relaxes single-owner socket assumptions. Use a dedicated service identity and an isolated trust boundary; skip prefork when strict single-owner port semantics are required.

## Redirect and flash messages

Redirect objects are pooled. Flash messages and old input are serialized into the `fiber_flash` cookie. The cookie is `HttpOnly`, `Secure` only when the redirect request arrived over TLS, and hex-encoded rather than encrypted or signed. Treat its contents as visible to the client. It is cleared on every read, including a malformed payload.

## Hooks and error lifecycle

Hooks run at defined lifecycle points. Route registration and listen hooks panic on error; startup-message hooks log and skip; shutdown and fork hooks log and continue. The app's error handler runs for handler errors and for requests fasthttp rejects before routing, except a timed-out request: timeout middleware answers without running `ErrorHandler`. Panics reach the error handler only when a recover middleware is mounted.

## Why the rules matter

- Ctx-backed values are views into reusable buffers, not owned memory.
- Route order is matching order.
- The Ctx pool is why cancellation must come from `c.Context()`.
- Prefork isolation is why in-memory state is not shared.
- Shutdown waits for in-flight handlers, so every long-lived worker needs an exit path.

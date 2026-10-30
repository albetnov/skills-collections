# Routing and handlers

## Registration basics

A route is an HTTP method plus a path plus one or more handlers.

```go
app.Get("/users/:id", func(c fiber.Ctx) error {
    return c.SendString(c.Params("id"))
})
```

- `Get`, `Post`, `Put`, `Patch`, `Delete`, `Head`, `Options`, `Connect`, `Trace`, and `Query` match one method at an exact path.
- `All` matches every method at an exact path.
- `Add` registers the same handlers on several methods.
- `Use` registers middleware on a prefix, on every method. A prefix matches the exact path or stops at a `/` boundary; `/api` matches `/api` and `/api/users`, not `/apiv2`. `Use` without a path matches every request.
- Multiple handlers in one call run in declaration order. Each handler calls `c.Next()` to continue.

`RouteChain` declares several methods on one path:

```go
app.RouteChain("/events").
    All(func(c fiber.Ctx) error { return c.Next() }).
    Get(func(c fiber.Ctx) error { return c.SendString("GET /events") }).
    Post(func(c fiber.Ctx) error { return c.SendString("POST /events") })
```

Inside a chain, `All` registers prefix-matched middleware like `Use`, not exact-path `App.All`.

## Registration order

Routes match in registration order; the first match wins. Register fixed paths before parameterized paths.

```go
app.Get("/users/me", currentUser)
app.Get("/users/:id", userByID)
```

Middleware runs in registration order. `app.Use` middleware registered before a route runs before that route's handlers.

Define the route table before `Listen`. `RebuildTree`, `RemoveRoute`, `RemoveRouteByName`, and `RemoveRouteFunc` are not thread-safe and are performance-intensive; use them in development only.

## Path semantics

By default the router ignores letter case and a trailing slash: `/about` also answers `/About` and `/about/`. Set `CaseSensitive` or `StrictRouting` to distinguish them.

Before matching, the path is normalized as RFC 3986 Section 6.2.2 describes: percent-encoded unreserved characters are decoded, `.` and `..` segments are resolved, and other escapes stay encoded with uppercase hex digits. `%2F` does not split a segment. `UnescapePath` decodes every escape.

`c.Path()` returns the normalized path. `c.OriginalURL()` returns the request target as sent. A route parameter keeps the escapes the router kept unless `UnescapePath` is enabled; decode it yourself only when the target accepts that.

## Parameters

```go
app.Get("/user/:name", handler)          // named
app.Get("/user/:name?", handler)         // optional value
app.Get("/user/+", handler)              // greedy, required
app.Get("/user/*", handler)              // greedy, optional
```

Retrieve named parameters with `c.Params("name")`. Retrieve several wildcard or plus segments positionally with `c.Params("*1")`, `c.Params("*2")`, `c.Params("+1")`, and so on.

Adjacent named parameters with no literal separator split deterministically: every parameter except the last takes one character, and the last takes the rest. Put a literal delimiter between parameters when you need a multi-character split.

An optional parameter makes only its value optional, not the text around it: `/user/:name?/books` matches `/user//books` but not `/user/books`. At the end of a path, `/user/:name?` also matches `/user`. Adjacent optional parameters may retry as empty, at most 16 retries per route.

### Constraints

Constraints are matching rules, not input validation. A failed constraint means the route does not match, which returns `404 Not Found`.

```go
app.Get("/users/:id<int>", handler)
app.Get("/files/:name<minLen(1);maxLen(64)>", handler)
app.Get("/date/:value<regex(\\d{4}-\\d{2}-\\d{2})>", handler)
```

Built-ins include `int`, `bool`, `guid`, `float`, `minLen`, `maxLen`, `len`, `betweenLen`, `min`, `max`, `range`, `alpha`, `datetime`, and `regex`.

- A missing or malformed argument makes the route never match.
- A misspelled constraint name is ignored, leaving the parameter unconstrained.
- An invalid `regex()` pattern panics at registration.
- Escape routing characters with `\\` inside a `datetime` layout.
- Custom constraints must be registered before the routes that use them. A custom constraint overrides a built-in with the same name.
- Constraint names and arguments are taken from the pattern as written; built-in names match case-insensitively, custom names match exactly.
- Validate request values separately when a value must produce a client error rather than a 404.

## Groups and mounts

`Group` creates a virtual prefix; routes flatten into the app in declaration order.

```go
api := app.Group("/api")
v1 := api.Group("/v1")

users := v1.Group("/users")
users.Get("", listUsers)
users.Get("/:id", getUser)
```

A group prefix follows the same slash-boundary rule as `Use`. Accessing the bare group path returns 404 unless a route or handler covers it. A group handler must call `c.Next()` to continue.

`Route` is shorthand for a group declared inside one callback:

```go
app.Route("/api/v1", func(r fiber.Router) {
    r.Get("/users", listUsers).Name("users.list")
}, "v1.")
```

`Domain` scopes routes to a hostname and keeps the group prefix.

### Mounting a sub-app

Use `app.Use("/prefix", subApp)` to mount a Fiber app. Fiber does not strip the mount prefix: inside the sub-app, `c.Path()` is still the full path, and `c.MountPath()` returns the prefix.

The top-level app's routing settings apply at every nesting depth: `CaseSensitive`, `StrictRouting`, and `UnescapePath`. Runtime settings such as `JSONEncoder`, `StructValidator`, `PassLocalsToViews`, and `BodyLimit` also come from the top-level app.

A sub-app's own `ErrorHandler`, `Views`, and `ViewsLayout` apply only when the whole mount path is literal. Under a parameterized mount such as `/t/:tenant`, the nearest literal enclosing mount or the top-level app supplies them.

Mount deepest apps first when `MountPath()` must report the full chain. Mounting an app onto itself panics. Passing handlers and a sub-app in one `Use` call panics; register middleware in a separate call.

## Automatic HEAD routes

Fiber registers a `HEAD` route for every `GET` route. The generated chain mirrors the `GET` chain and suppresses the body. A dedicated `Head` route overrides the generated route for the same path and domain.

- `DisableHeadAutoRegister` opts out globally.
- A mounted sub-app that disables HEAD or omits `HEAD` from `RequestMethods` gets no generated HEAD routes for its routes.
- Generated HEAD routes appear in `app.Stack()` after startup or after `RebuildTree`.

## Handler types

Fiber accepts 17 handler shapes and converts them to `func(fiber.Ctx) error`:

- Fiber-native: `func(fiber.Ctx) error` and `func(fiber.Ctx)`.
- Express-style: `func(fiber.Req, fiber.Res, ...)`, optionally with a `next` callback.
- `net/http`: `http.HandlerFunc`, `http.Handler`, and `func(http.ResponseWriter, *http.Request)`.
- fasthttp: `fasthttp.RequestHandler` and `func(*fasthttp.RequestCtx) error`.

Registration panics for an unsupported signature or a `nil` handler.

Express-style `next` continues the chain; a non-nil error short-circuits. Fiber has no four-argument Express error handler; errors go to the app's `ErrorHandler`.

Adapted `net/http` handlers do not receive `fiber.Ctx`, cannot call `c.Next()`, and always terminate the chain. They also add compatibility overhead. Use native Fiber handlers when Fiber APIs or throughput matter.

fasthttp handlers manage the response directly. The error-returning variant propagates its error; otherwise Fiber does not inspect the context state.

## Runtime route changes

`RebuildTree` publishes routes added since the last build and generates HEAD routes. `RemoveRoute*` removes routes but needs a later rebuild. All of these mutate the router without synchronization.

Use them only during startup or in development. For runtime feature flags, prefer a stable route with a handler that checks configuration.

## Checklist

- Fixed paths are registered before parameterized paths.
- `Use` is used for prefix middleware; `Get`/`All` are exact-path routes.
- Constraints handle matching; validation handles client errors.
- Custom constraints are registered before their routes.
- Module boundaries use `Group`/`Router`; sub-apps are mounted only when isolation is needed.
- The route table is complete before `Listen`.

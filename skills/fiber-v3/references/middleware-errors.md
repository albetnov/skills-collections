# Middleware and errors

## The chain

A handler chain runs in registration order. Each handler decides whether the rest runs:

```go
app.Use(func(c fiber.Ctx) error {
    start := time.Now()
    err := c.Next()
    log.Printf("%s %s %s", c.Method(), c.Path(), time.Since(start))
    return err
})
```

- `c.Next()` runs the next matching handler and returns its error.
- Returning before `c.Next()` short-circuits the chain.
- Returning the error from `c.Next()` propagates it to the app's error handler.
- A middleware stops the chain by returning without calling `c.Next()`. Writing a response alone does not stop it; a middleware can write and still call `c.Next()`.

Middleware registered with `Use` runs for requests that match no route as well, unless `SkipUnmatchedRoutes` is enabled; CORS preflight requests are exempt and still run. That makes `Use` the right place for guards that must cover 404s and 405s.

## Returning errors

Fiber centralizes error responses. Return an error from a handler or middleware:

```go
app.Get("/users/:id", func(c fiber.Ctx) error {
    user, err := store.Get(c.Params("id"))
    if err != nil {
        return fiber.NewError(fiber.StatusNotFound, "user not found")
    }
    return c.JSON(user)
})
```

- `fiber.NewError(code, message...)` creates a `*fiber.Error` carrying a status.
- `fiber.NewErrorf` formats the message.
- `fiber.ErrNotFound`, `fiber.ErrUnauthorized`, `fiber.ErrBadRequest`, and the other package errors are ready-made `*fiber.Error` values.
- A status outside 100–999 logs an error and sends `500`.
- Returning a validation or binding error as-is usually produces `500`; map client-caused errors to an appropriate 4xx status.

`errors.As` retrieves the status from a wrapped error:

```go
var e *fiber.Error
if errors.As(err, &e) {
    return c.Status(e.Code).JSON(...)
}
```

## Error handler

The default error handler sends `500` for generic errors and uses a `*fiber.Error`'s status and message when present. Set a custom handler in config:

```go
app := fiber.New(fiber.Config{
    ErrorHandler: func(c fiber.Ctx, err error) error {
        code := fiber.StatusInternalServerError
        message := "internal server error"

        var e *fiber.Error
        if errors.As(err, &e) {
            code = e.Code
            message = e.Message
        }

        return c.Status(code).JSON(fiber.Map{"error": message})
    },
})
```

Call `fiber.DefaultErrorHandler(c, err)` to fall back to the default response for errors you do not handle.

A mounted sub-app's `ErrorHandler` applies only when the whole mount path from the top-level app down is literal. Under a parameterized mount such as `/t/:tenant`, the nearest literal enclosing mount or the top-level app supplies the handler. A `Domain` mount matches a parameterized path as a pattern and keeps its own handler.

## Errors before a handler runs

The error handler also answers requests that never reach a route:

| Cause | Response |
|---|---|
| No route | `404 Not Found` |
| Path exists for another method | `405 Method Not Allowed` with `Allow` |
| Headers exceed `ReadBufferSize` | `431 Request Header Fields Too Large` |
| Body exceeds `BodyLimit` | `413 Request Entity Too Large` |
| `GETOnly` rejects the method | `405 Method Not Allowed` |
| Unsupported transfer coding | `501 Not Implemented` |
| Read timeout or network error | `408` or `502` |
| Other malformed request | `400 Bad Request` |

For a known method that `GETOnly` does not reject, the `Use` chain runs first and sees the mapped status; route handlers are skipped. Cache, idempotency, proxy, and static middleware do not act on such a request.

An unknown method, or a known method in the wrong letter case, answers `501 Not Implemented` without running middleware or the error handler.

## Panics

Fiber does not recover panics by default. Add the recover middleware:

```go
import "github.com/gofiber/fiber/v3/middleware/recover"

app.Use(recover.New())
```

A recovered panic reaches the error handler as an ordinary error. The default handler answers `500` with the panic message. If the panic value is a `*fiber.Error`, its status is kept. Use `PanicHandler` to return a generic error instead of exposing the panic message.

A panic in a goroutine outside the handler chain is not caught by `recover.New()`. Recover inside that goroutine.

## Response ownership

- After `c.Next()`, check `c.Written()` before writing a response. A streamed body counts as written without being drained.
- `c.Res().Body()` is the live response buffer, not a copy. It is invalidated by the next write.
- `c.ResetBody()` discards a partially written body while keeping status and headers. Use it before replacing an error page or half-rendered view.
- `c.End()` flushes and closes the connection, and blocks later writes. It does not work in streaming mode or on a hijacked connection.
- Do not write through `c` inside a `SendStreamWriter` callback or an SSE stream handler. Those run outside the normal handler window.

## Middleware order

A practical order:

1. `recover`
2. request ID
3. logger / metrics / tracing
4. CORS
5. compression and cache (cache outside session when both are used)
6. authentication and authorization
7. rate limiting / idempotency
8. route-specific validation and handlers

Order is behavior, not cosmetics. Cache must sit outside middleware that writes cookies during its post-`c.Next()` phase, or personalized responses get shared. Authentication must run before handlers that assume an identity. Rate limiting should run before expensive work.

## Checklist

- Every middleware that continues calls `c.Next()` and returns its error.
- Every client-caused error is mapped to a 4xx status.
- Panic policy is explicit; `recover.New()` is mounted when handlers may panic.
- Goroutine panics are recovered in the goroutine.
- Middleware order matches the cache/session and auth/rate-limit requirements.
- No response is overwritten after `c.Written()` or after the connection is ended.

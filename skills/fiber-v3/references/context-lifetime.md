# Context lifetime

The rule: a `fiber.Ctx` and the values read through it live until the handler returns. Fiber pools the Ctx and reuses the request buffers for the next request on the connection.

## What escapes the handler

Every request getter can return data backed by the request buffer: `Params`, `Query`, `Cookies`, `Get`, `GetAll`, `FormValue`, `OriginalURL`, `Authorization`, `Bearer`, and the header-map getters. Strings decoded by `Bind` alias the same buffers.

Copy at the boundary:

```go
id := strings.Clone(c.Params("id"))
body := bytes.Clone(c.Body())
```

`string(c.Body())` also makes a copy. Use `bytes.Clone` when the caller needs a byte slice.

`Immutable` makes Ctx getters return detached values:

```go
app := fiber.New(fiber.Config{Immutable: true})
```

With `Immutable` enabled, `app.GetString` and `app.GetBytes` return detached copies. With it disabled they return the input unchanged, so copy yourself. `Immutable` does not cover values decoded by `Bind`.

## Ctx, Context, and RequestCtx

| Call | Lifetime | Cancellation |
|---|---|---|
| `c` | Until the handler returns | Never: `Done()` is `nil`, `Deadline()` reports none, `Err()` is `nil` |
| `c.Context()` | Safe after the handler | Only what you derive with `WithCancel`/`WithTimeout` |
| `c.RequestCtx()` | The underlying fasthttp request | `Done()` closes on server shutdown, not on client disconnect |

`c` can be passed where a `context.Context` is expected for value lookup, but it cannot carry cancellation. For anything cancellation-aware or potentially outliving the handler:

```go
ctx := c.Context()
work(ctx)
```

`SetContext` changes what `Context()` returns for the rest of the request. It does not make `c` cancelable.

`c.Context()` is not canceled when graceful shutdown starts. `c.RequestCtx().Done()` is the shutdown signal for long-lived streams. Neither fires on a client disconnect by itself.

## Request-scoped values

`c.Locals(key, value)` and `c.SetLocal(key, value)` store values for the rest of the request. They are removed after the request completes. If a stored value implements `io.Closer`, Fiber calls `Close` before removal.

`SetLocal` avoids the one-element slice that `Locals` allocates through the interface. Use `SetLocal` on hot paths; boxing the value can still allocate.

`fiber.StoreInContext` and `fiber.ValueFromContext` are the generic helper pair. `StoreInContext` always writes to `Locals`; it also writes to `c.Context()` only when `PassLocalsToContext` is enabled (default `false`).

A session pointer is not a value to retain. `session.FromContext` stops resolving after the request ends. Pass the session ID to a goroutine and reopen the session through the store pattern.

## Pool and release

Fiber acquires a Ctx per request and releases it back to the pool. When you run a Fiber handler yourself instead of going through `app.Handler`, do the same:

```go
func serve(app *fiber.App, fctx *fasthttp.RequestCtx, handler fiber.Handler) {
    c := app.AcquireCtx(fctx)
    defer app.ReleaseCtx(c)

    if err := handler(c); err != nil {
        _ = app.ErrorHandler(c, err)
    }
}
```

`ReleaseCtx` does not pool an abandoned Ctx. Do not use a Ctx after releasing it; the next request can reuse it immediately.

`Ctx.Request()` and `Ctx.Response()` return `nil` after the Ctx has been released.

### Abandon and reclaim

`Abandon` marks the Ctx as outside the normal pool return. It is for middleware that lets a handler outlive the request, such as timeout and SSE.

- `ScheduleReclaim(handlerDone, cancel)` is the race-free option. It abandons the Ctx, calls `cancel` when `handlerDone` closes, and returns the Ctx to the pool only after both the handler goroutine and Fiber's request path are done.
- `ForceRelease` is only safe after every goroutine that touches the Ctx has finished, including Fiber's own handler and error handler.
- Only `*fiber.DefaultCtx` signals `ReleaseCtx` that reclaim is armed. A custom Ctx type that embeds it never gets that signal, so the Ctx is never reclaimed. The timeout middleware uses `Abandon` alone for custom types.

Most applications never call these methods directly. Use them only in advanced middleware; otherwise prefer `c.Context()`.

## Request body and uploads

`Body` and `BodyRaw` return request-buffer slices. `Body` may decompress according to `Content-Encoding`, bounded by `BodyLimit`. Copy the result if it leaves the handler.

`BodyStream` is non-`nil` only with `StreamRequestBody` enabled and an unbuffered body. Reading it consumes the body, so a later `Body` call sees nothing. It is the only way to read a body larger than `BodyLimit`.

`MultipartForm` and `FormFile` parse within `BodyLimit`. `FormValue` searches the query string first, then the url-encoded body, then the multipart form. On a form request, `FormValue` and `MultipartForm` lowercase parts of the request's own `Content-Type`; copy a `Content-Type` value you read earlier if it must survive the call.

## Response and stream ownership

- `Send` uses the slice without a copy. Do not mutate it after the call.
- `SendString` sets a string body.
- `SendStream` runs asynchronously after the handler returns. If the reader implements `io.Closer`, fasthttp closes it after the response or on error. Pass the size when known; unknown-size streams use chunked framing even for HTTP/1.0 clients.
- `SendStreamWriter` runs the writer on its own goroutine, which may run after the handler returns. Copy everything it needs from the Ctx before calling it; do not touch `c` inside the writer.
- `SendFile` caches file handlers per config. A config created per request, such as a fresh `fs.Sub` pointer, churns that cache; create file systems once. A file name built from request input is served wherever it points, so confine it with `os.OpenRoot` and `FS`.
- `Hijack` runs after the response is written, on its own goroutine. The Ctx is pooled and reused, so the hijack handler must not touch it.
- `End` flushes the response and closes the connection, and blocks further writes. It does not work in streaming mode or on a hijacked connection.
- `Res().Body()` is the response's live buffer, not a copy. It is invalidated by the next write to the response. Copy it if it must survive.
- `Written` reports whether the body has anything written, including a stream. It lets middleware avoid overwriting a streamed response.

## Middleware that changes the lifetime

Timeout middleware abandons the Ctx when the deadline passes. The handler keeps running in its own goroutine, so it must stop using the Ctx once `c.Context()` is done. A custom Ctx leaks one Ctx per timed-out request; a `*fiber.DefaultCtx` is reclaimed once both sides finish.

SSE `Handler` runs in its own goroutine after the response body starts. The Ctx remains the stream's own request while `Handler` and `OnClose` run, but write through `stream`, not through `c`. `stream.Context()` is canceled when the stream ends or a write fails; `stream.Done()` is the stream-local stop signal, including a client that has gone away.

## Checklist

- Every Ctx-derived value that outlives the handler is copied or covered by `Immutable`.
- Every acquired Ctx is released, and no Ctx is used after release.
- Every goroutine, stream writer, and hijack handler has its inputs copied and does not touch `c`.
- Every stream-owned `io.Closer` is closed or handed to fasthttp.
- Every request-scoped `io.Closer` stored in `Locals`/`SetLocal` is cleaned up by Fiber.

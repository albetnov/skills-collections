# App lifecycle

## Construction and config

```go
app := fiber.New(fiber.Config{
    Immutable:          false,
    BodyLimit:          4 * 1024 * 1024,
    StreamRequestBody:  false,
    PassLocalsToContext: false,
    ReadTimeout:        10 * time.Second,
    WriteTimeout:       10 * time.Second,
    IdleTimeout:        60 * time.Second,
})
```

Config fields that change behavior most often:

- `Immutable` — Ctx getters return detached values. Costs throughput; use when many values must outlive handlers. `Bind` results still alias request buffers.
- `BodyLimit` — caps request bodies and decompression, multipart parsing, and adaptor body reads.
- `StreamRequestBody` — lets `BodyStream` read a body larger than `BodyLimit`; buffered body APIs still refuse it.
- `PassLocalsToContext` — makes `StoreInContext` also write to `c.Context()`. Default `false`.
- `SkipUnmatchedRoutes` — answers unmatched routes before the middleware chain. Middleware, logging, metrics, rate limiting, static, proxy, and catch-all 404 pages stop seeing those requests. CORS preflight still runs.
- `ReadBufferSize` — per-connection read buffer and maximum header size.
- `ReadTimeout`, `WriteTimeout`, `IdleTimeout` — connection deadlines. A non-zero `ReadTimeout` prevents a preconnect from holding shutdown forever.
- `RequestMethods` — the methods the router accepts. Registering a route for an unlisted method panics.
- `StrictRouting`, `CaseSensitive`, `UnescapePath` — routing semantics.
- `TrustProxy` and `TrustProxyConfig` — read client IP and scheme from proxy headers only for trusted proxies. `ProxyHeader` alone has no effect; an empty `TrustProxyConfig` trusts no peer. Broad trust such as `Private`, `Loopback`, or `LinkLocal` lets clients spoof headers.
- `EnableIPValidation` — validates `c.IP()`/`c.IPs()`; needed when a proxy header can contain a chain.
- `Services` and `SharedStorage` — lifecycle-owned dependencies.

`app.Config()` returns a read-only copy of the config.

## Listen and startup

```go
log.Fatal(app.Listen(":3000"))
```

`Listen` creates and serves a fasthttp server. `Listener` serves a `net.Listener` you supply; it ignores TLS, prefork, and listener-address fields from `ListenConfig`.

`ListenConfig` lifecycle fields:

- `GracefulContext` — starts shutdown when the context is done.
- `ShutdownTimeout` — bounds the built-in graceful shutdown path.
- `BeforeServeFunc` — runs after the listener is bound; it is not called when `EnablePrefork` is enabled on `Listen`.
- `EnablePrefork` — starts child processes.

On the built-in graceful path, `Listen` returns only after shutdown finishes outside the prefork master. A prefork master keeps supervising children, and each process needs its own shutdown signal.

## Shutdown

```go
ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
defer cancel()

if err := app.ShutdownWithContext(ctx); err != nil {
    log.Printf("shutdown: %v", err)
}
```

- `Shutdown` closes listeners and waits indefinitely for in-flight handlers, including `SendStream` and `SendStreamWriter` responses.
- `ShutdownWithTimeout` and `ShutdownWithContext` stop waiting at the deadline but do not close connections that are still active.
- Call shutdown from a separate goroutine while `Listen` runs, and keep the process alive until it returns.
- Long-lived streams end when `c.RequestCtx().Done()` closes.
- `OnPreShutdown` runs before the server stops accepting connections; `OnPostShutdown` runs after shutdown, even on failure.
- Shutdown hooks run once per shutdown. They do not run when `Listen` cannot bind its address.

## Services

```go
type Service interface {
    Start(ctx context.Context) error
    String() string
    State(ctx context.Context) (string, error)
    Terminate(ctx context.Context) error
}
```

- `fiber.New` starts services in `Config.Services` order and registers each in `app.State()`.
- Startup panics on a nil service, duplicate names, a failing `Start`, or a canceled startup context.
- Shutdown terminates services in reverse start order.
- A `Terminate` error is logged and the remaining services still run. A failed service stays registered for a later shutdown.
- Once the shutdown context is done, remaining services are not terminated.
- With prefork, every process runs `fiber.New` and starts its own copy of every service. Design services for per-process ownership.
- `ServicesStartupContextProvider` and `ServicesShutdownContextProvider` are called each time a context is needed. Build deadlines inside the provider; a pre-built context may already be expired.

## State

`app.State()` is a thread-safe `sync.Map` for process-local dependencies and runtime data.

- With prefork, each worker has its own State.
- `State.Reset()` removes all keys, including service keys, but does not stop the services. Fiber still terminates them at shutdown.
- `State.Delete(key)` removes one key.

`app.SharedState()` is for prefork/multi-process sharing and requires `SharedStorage`. Without it, every method returns `ErrSharedStorageNotConfigured`.

- An empty key is ignored. A TTL of `0` stores without expiration.
- `SharedState.Reset()` resets the whole configured storage, not only keys written through SharedState.
- `SharedState.Close()` closes the storage. Fiber calls it on shutdown after terminating services, so every other user of that storage loses it too.
- An in-memory SharedStorage is still process-local; use Redis, a database, or another shared backend for cross-worker state.

## Hooks

Hooks run at lifecycle points:

- `OnRoute`, `OnName`, `OnGroup`, `OnGroupName` — route/group registration and naming.
- `OnListen`, `OnPreStartupMessage`, `OnPostStartupMessage` — startup.
- `OnFork` — prefork child creation, in the master.
- `OnPreShutdown`, `OnPostShutdown` — shutdown.
- `OnMount` — sub-app mount.

Error behavior:

- `OnRoute`, `OnName`, `OnGroup`, `OnGroupName`, `OnMount`, and `OnListen` panic on error.
- `OnPreStartupMessage` and `OnPostStartupMessage` log the error and skip remaining hooks of that kind.
- `OnPreShutdown`, `OnPostShutdown`, and `OnFork` log the error and run the remaining hooks.

`OnName`, `OnRoute`, `OnGroup`, and `OnGroupName` are mount-sensitive: they report paths with the mount prefix for routes registered after the mount. Parent hooks do not run for a sub-app's routes.

## Middleware lifecycle

### Session

- Middleware pattern: automatic save and cleanup; no manual lifecycle.
- Store pattern: `store.Get`/`GetByID` returns a session that requires `defer sess.Release()` and an explicit `sess.Save()`.
- `Destroy` deletes the session and expires the cookie; `Reset` changes the ID and clears data; `Regenerate` changes the ID and keeps data.
- `IdleTimeout` and `AbsoluteTimeout` are enforced by the storage layer.
- A session is stored under `session:<id>`. `store.Reset` clears the whole storage, including other middleware's entries.
- External storage processes are not coordinated across instances; use a server-side revocation marker when logout must hold across instances.
- A session pointer is valid only during the request. Pass the session ID to a goroutine and use the store pattern.

### Cache

- Default `cache.New()` allows 1 MB. A `Config` that leaves `MaxBytes` unset means no limit.
- `Expiration` is the fallback lifetime; response `Cache-Control` and `Expires` override it.
- Response directives `no-store`, `private`, and `no-cache`, a response with `Vary: *` or `Set-Cookie`, and a request carrying `Authorization` (unless the response permits shared caching) keep the response out of the shared cache.
- `MaxBytes` evicts entries closest to expiry. A streamed response may be passed through instead of stored; verify cacheability.
- Register cache outside middleware that writes cookies after `c.Next()` — notably session — or a personalized response can be stored for other clients.
- `Storage` can be shared, but entries are namespaced by a key-format version.

### Limiter, idempotency, CSRF

- Limiter keeps counters for `Expiration`. A custom `Storage` receives a key copy; the built-in store copies keys. A positive duration below one second is one second.
- Idempotency stores responses under `idempotency:<key>` for `Lifetime` (default 30 minutes).
- CSRF stores tokens under `csrf:<token>` for `IdleTimeout` (default 30 minutes). `DeleteToken` on logout invalidates a token explicitly.

### Static and logger

- Static `CacheDuration` controls the file-handler cache; use a negative duration to disable it.
- Static roots on disk are confined: absolute symlinks and links that leave the root are treated as missing unless `AllowSymlinksOutsideRoot` is set.
- An access log file you pass to the logger middleware must be closed. Custom streams may need their own locking.

## Prefork

- The master process spawns children; each child sets `GOMAXPROCS(1)` and listens on the shared port.
- Linux uses `SO_REUSEPORT`; Windows falls back to `SO_REUSEADDR`, which is not equivalent load distribution or isolation.
- Each child has its own State, services, and in-memory storage.
- Prefork is safest with a dedicated service identity and an isolated trust boundary. Use `SharedStorage` for cross-worker data.

## Checklist

- Every long-lived resource has an owner and a close path: listener, service, storage, worker, file, log.
- Shutdown has a deadline and waits for in-flight handlers.
- Prefork-visible state is externalized.
- Session store access releases and saves explicitly.
- Cache sits outside cookie-writing middleware.
- Static and logger caches/files have a lifecycle.

# Concurrency and performance

Read [context-lifetime](context-lifetime.md) first. This file assumes the Ctx boundary is understood.

## The safe handoff

A goroutine never receives `fiber.Ctx`. It receives a real context and copied values:

```go
type job struct {
    ctx context.Context
    id  string
}

func (h *Handler) enqueue(c fiber.Ctx) error {
    j := job{
        ctx: c.Context(),
        id:  strings.Clone(c.Params("id")),
    }

    select {
    case h.jobs <- j:
        return c.SendStatus(fiber.StatusAccepted)
    default:
        return fiber.ErrServiceUnavailable
    }
}
```

The bounded channel supplies backpressure. The copied ID and `c.Context()` keep the job independent of the pooled Ctx.

If the goroutine needs a deadline:

```go
ctx, cancel := context.WithTimeout(c.Context(), 2*time.Second)
defer cancel()
```

Pass `ctx` to database clients, HTTP clients, and other cancellation-aware calls. Derive from `c.Context()`, not from `c`; `c` never cancels.

## Goroutines

- Give every goroutine an owner and a stop condition.
- Bound concurrency with a worker pool, semaphore, or `errgroup` from `golang.org/x/sync/errgroup`. One unbounded goroutine per request is a denial-of-service path.
- Recover panics inside the goroutine. The `recover` middleware only protects the handler chain; a panic in another goroutine still terminates the process.
- Do not share the Ctx, `*fasthttp.Request`, `*fasthttp.Response`, or Ctx-backed slices across goroutines.
- Prefer `context.WithCancel`, `context.WithTimeout`, and `select` on `ctx.Done()` over ad-hoc stop flags.
- Avoid `time.Sleep` in request paths. Use timers with context cancellation when a delay is required.
- Use `sync.WaitGroup` for fan-out where every result is needed; use a buffered result channel when results may arrive after cancellation so workers do not block forever.

```go
func (h *Handler) fanOut(ctx context.Context, ids []string) ([]Result, error) {
    g, ctx := errgroup.WithContext(ctx)
    results := make([]Result, len(ids))

    for i, id := range ids {
        i, id := i, id
        g.Go(func() error {
            r, err := h.fetch(ctx, id)
            if err != nil {
                return err
            }
            results[i] = r
            return nil
        })
    }

    return results, g.Wait()
}
```

## Channels

- A channel has one logical owner. The sender closes it; the receiver never closes it.
- Close only when no more sends can happen. Use `sync.Once` if several paths can trigger the close.
- Buffer for handoff and throughput; leave unbuffered for synchronization. A bounded buffer is a backpressure mechanism, not a queue you can grow forever.
- Always include `<-ctx.Done()` in a blocking send or receive that can outlive the request.
- Do not send Ctx-backed values through a channel. Copy strings and bytes before enqueueing.
- For fan-out, give every subscriber its own channel. A single shared channel load-balances messages across clients instead of broadcasting them.
- On shutdown, stop accepting work, close the input, and wait for workers to drain. Do not close a channel while a sender may still use it.

```go
for {
    select {
    case <-ctx.Done():
        return ctx.Err()
    case msg, ok := <-input:
        if !ok {
            return nil
        }
        if err := handle(msg); err != nil {
            return err
        }
    }
}
```

## Mutexes and shared state

- Protect every mutable map, counter, cache, and connection pool shared across requests.
- Use `sync.Mutex` for exclusive updates and `sync.RWMutex` for read-heavy data. Keep the critical section short.
- Never hold a lock across network I/O, database I/O, a channel send, or a call that may block. Copy the data out, release the lock, then do the slow work.
- Never copy a mutex after first use. Pass `*sync.Mutex` and `*sync.RWMutex`; `go vet` catches copied locks.
- Prefer `atomic.Int64`, `atomic.Bool`, and `atomic.Pointer` for simple counters, flags, and immutable snapshots.
- Use `sync.Map` only for stable, largely disjoint key sets such as `app.State()`. It is not a general replacement for a guarded map.
- Request-scoped data belongs in `Locals`/`SetLocal`, not in a package-level map.

`app.State()` is a thread-safe `sync.Map`, but it is process-local. With prefork, each worker has its own State. Use `SharedStorage`/`SharedState`, a database, or Redis when workers must see the same value.

```go
type counter struct {
    mu sync.Mutex
    n  int64
}

func (c *counter) inc() {
    c.mu.Lock()
    c.n++
    c.mu.Unlock()
}
```

## Allocation and throughput

- Copy only data that actually escapes. A value used inside the handler can stay on the request buffer.
- `SetLocal` avoids the variadic slice allocation of `Locals`. Boxing the value can still allocate.
- `Immutable` trades throughput for simpler retention. Enable it when many values must outlive handlers; otherwise copy at the boundary.
- Preallocate slices and maps when the size is known.
- Use `sync.Pool` for scratch buffers, encoders, and temporary byte slices. Reset before reuse, and never pool a Ctx-backed slice or a Ctx itself.
- `Send` avoids a body copy. Use `SendStream` or `SendFile` for large responses instead of buffering them in memory.
- Tune `BodyLimit`, `ReadBufferSize`, and `WriteBufferSize` to the workload. `ReduceMemoryUsage` trades CPU for memory.
- `StreamRequestBody` avoids buffering large uploads; only `BodyStream` can read such a body. Once read, the body is consumed.
- Route regexes compile at registration. A custom `RegexHandler` matcher is reused across requests, so it must be safe for concurrent use.

## Background work and shutdown

- Put long-lived workers behind a `fiber.Service` with `Start` and `Terminate`, or start them in `main` and stop them in a shutdown hook.
- A service's `Start` context is a startup context, not a shutdown signal; stop its workers in `Terminate` or through your own cancellation path. The `Terminate` context is the shutdown context.
- Workers receive a context that is canceled when you cancel it. Wait for them to exit.
- For SSE, use `stream.Context()` and `stream.Done()`. The stream handler owns its goroutine; write through `stream`, not `c`.
- For timeout middleware, the handler may keep running after the client gets a response. Stop on `c.Context().Done()` and do not touch the Ctx afterwards.
- Avoid fire-and-forget goroutines that can outlive the process without a shutdown path.

## Checklist

- Every goroutine has an owner, a cancellation path, and bounded concurrency.
- Every channel has one close owner, and every blocking operation selects on `ctx.Done()`.
- Every shared mutable value has one synchronization strategy.
- Every lock is released before I/O or channel work.
- Every request-scoped value crossing a goroutine or channel is copied first.
- Every background worker is stopped and waited for during shutdown.

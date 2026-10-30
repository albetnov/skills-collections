# Project layout

## Target tree

```text
cmd/api/main.go                 # config, dependency wiring, signal handling, shutdown
internal/
  app/app.go                    # fiber.New, global middleware, version groups, module registration
  config/config.go              # env parsing, validation, defaults
  platform/
    database/                   # database client
    cache/                      # cache client
    logging/                    # logger and trace setup
  shared/
    identity/
      actor.go                  # request actor and tenant identity
    httpx/
      error.go                  # error envelope and domain-error mapping
      response.go               # success helpers
      pagination.go             # cursor/page helpers
    middleware/                 # auth, request ID, rate limit, recovery
  modules/
    user/
      module.go                 # constructor and Register(router)
      handler.go                # HTTP parsing and response mapping
      service.go                # business rules and consumer-owned interfaces
      repository.go             # persistence adapter
      dto.go                    # request/response structs
      model.go                  # domain model
    order/
      module.go
      handler.go
      service.go
      repository.go
      dto.go
      model.go
api/
  openapi.yaml                  # OpenAPI 3.1 contract
```

A feature's handler, service, repository, DTOs, and model stay together. Global `controllers/`, `services/`, and `repositories/` trees scatter one feature across the codebase and make boundary changes expensive.

## Feature module

A module owns its registration:

```go
package user

import "github.com/gofiber/fiber/v3"

type Module struct {
    service *Service
    baseURL string
}

func New(repo Repository, baseURL string) *Module {
    return &Module{service: NewService(repo), baseURL: baseURL}
}

func (m *Module) Register(r fiber.Router) {
    g := r.Group("/users")

    g.Get("", m.list)
    g.Post("", m.create)
    g.Get("/:id", m.get)
    g.Patch("/:id", m.update)
    g.Delete("/:id", m.delete)
}
```

The handler is thin:

```go
func (m *Module) create(c fiber.Ctx) error {
    var in CreateUserRequest
    if err := c.Bind().Body(&in); err != nil {
        var be *fiber.BindError
        if errors.As(err, &be) {
            return httpx.BadRequest(c, "invalid_body", err)
        }
        return httpx.Validation(c, err)
    }

    actor := identity.From(c)
    u, err := m.service.Create(c.Context(), actor, in)
    if err != nil {
        return httpx.Error(c, err)
    }

    c.Set(fiber.HeaderLocation, m.baseURL+"/users/"+url.PathEscape(u.ID))
    return c.Status(fiber.StatusCreated).JSON(u)
}
```

The service signature carries identity explicitly:

```go
func (s *Service) Create(ctx context.Context, actor identity.Actor, in CreateUserRequest) (User, error)
```

`cfg.PublicBaseURL` is the public origin without a trailing slash, so the module's `baseURL` is the origin plus the version group.

`c.Context()` is the base context. It is `context.Background()` unless `SetContext` was called, so derive deadlines and cancellation explicitly and do not expect it to cancel on client disconnect or graceful shutdown. It does not carry `Locals` unless `PassLocalsToContext` is enabled, so identity, tenant, and request ID travel as explicit arguments. The service consumes bound DTO values synchronously or copies them; bound strings alias the request buffers.

The handler does four things: parse, validate, call one service method, map the result or error. It does not open a transaction, build SQL, or apply business rules.

## Wiring

`internal/app/app.go` builds the Fiber app and registers modules:

```go
func New(cfg config.Config, deps Dependencies) *fiber.App {
    app := fiber.New(fiber.Config{
        ErrorHandler: httpx.ErrorHandler,
    })

    app.Use(recoverer.New(recoverer.Config{
        PanicHandler: func(c fiber.Ctx, _ any) error {
            return fiber.ErrInternalServerError
        },
    }))
    app.Use(requestid.New())
    app.Use(middleware.RateLimit(deps.Limiter))

    api := app.Group("/api")
    v1 := api.Group("/v1")

    user.New(deps.UserRepository, cfg.PublicBaseURL+"/api/v1").Register(v1)
    order.New(deps.OrderRepository, cfg.PublicBaseURL+"/api/v1").Register(v1)

    return app
}
```

`httpx.ErrorHandler` emits the error envelope, maps domain errors, preserves `Allow` on `405`, and falls back to a generated request ID when `requestid.FromContext` is empty. The recover `PanicHandler` returns a generic 500 so panic text never reaches the client. A `501` for an unknown method is generated before middleware and is the documented exception.

`cmd/api/main.go` owns process lifetime:

```go
func main() {
    cfg := config.MustLoad()

    db := database.MustOpen(cfg.Database)
    defer db.Close()

    fiberApp := app.New(cfg, app.Dependencies{
        UserRepository: user.NewRepository(db),
        OrderRepository: order.NewRepository(db),
    })

    signalCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
    defer stop()

    errCh := make(chan error, 1)
    go func() { errCh <- fiberApp.Listen(cfg.HTTPAddr) }()

    select {
    case err := <-errCh:
        log.Printf("listen: %v", err)
    case <-signalCtx.Done():
        shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
        defer cancel()

        if err := fiberApp.ShutdownWithContext(shutdownCtx); err != nil {
            log.Printf("shutdown: %v", err)
        }
        <-errCh
    }
}
```

The app does not know how a repository is built. `main` wires concrete adapters into module constructors. `defer db.Close()` runs because the process returns instead of calling `log.Fatal` inside the listen goroutine.

## Dependency direction

```text
handler -> service -> repository interface
                ^
                |
        repository implementation
```

- **Handler** imports Fiber, DTOs, and the module service. It maps HTTP to service calls and domain errors to HTTP responses.
- **Service** imports the domain model, `context`, and the interfaces it needs. It never imports `fiber.Ctx`.
- **Repository** implements the interface declared by the service. It accepts `context.Context` and returns domain values and domain errors. It never imports Fiber.
- **Module constructor** receives concrete repositories from `main` and passes them to the service.
- **Cross-module calls** go through a small exported service interface, never through another module's repository or handler.

Interfaces live with the consumer. The service declares what it needs from persistence; the repository type supplies the implementation. The module's files are one Go package at first. If a module grows, split it into `handler/`, `service/`, and `repository/` subpackages under the module folder; cross-module imports still go through the exported service interface.

## Boundaries

- `internal/platform` owns database, cache, and logging clients. Modules receive them through constructors.
- `internal/shared` owns generic HTTP helpers, identity, middleware, and pagination. It contains no business rules.
- A module does not import `internal/app`.
- A module does not import another module's unexported handler, repository, or model.
- Cross-module calls go through an exported service interface.
- `cmd/` contains wiring and process concerns only.
- No package-level mutable state: no global app, database handle, logger, or config singleton.

## Route grouping and versioning

- Each module registers into the version router it receives.
- Global middleware applies before the version group.
- Authentication and tenant resolution apply at the version or module group.
- Authorization stays close to the route or in the service, depending on whether it is an HTTP concern or a business rule.
- Prefer `Group`/`Router` over mounted sub-apps. If you mount a sub-app, remember that Fiber does not strip the mount prefix, the top-level app's routing and runtime config wins, and the sub-app's own error handler/views apply only under a literal mount path — except a `Domain` mount, which keeps its own handler and views under a parameterized path. Use mounted sub-apps only when a separate app boundary is real.

A new major version gets a new group:

```go
v1 := api.Group("/v1")
v2 := api.Group("/v2")

user.New(deps.UserRepository, cfg.PublicBaseURL+"/api/v1").Register(v1)
userV2.New(deps.UserRepository, cfg.PublicBaseURL+"/api/v2").Register(v2)
```

Do not put `if version == "v2"` inside a handler.

## Error mapping

Define domain errors in the service layer and map them once in `shared/httpx`:

```go
var (
    ErrNotFound  = errors.New("not found")
    ErrConflict  = errors.New("conflict")
    ErrForbidden = errors.New("forbidden")
)
```

The mapper translates domain errors to the HTTP contract:

| Domain error | Status |
|---|---|
| validation failure | `422 Unprocessable Entity` |
| malformed input | `400 Bad Request` |
| not found | `404 Not Found` |
| conflict / duplicate | `409 Conflict` |
| forbidden | `403 Forbidden` |
| unauthenticated | `401 Unauthorized` |

Handlers return the mapped error. `httpx.ErrorHandler`, installed in `fiber.Config.ErrorHandler`, is the fallback for anything that escaped mapping. It emits the envelope, preserves `Allow` on `405`, uses `requestid.FromContext` with a generated fallback, and hides panic details. A `501` for an unknown method is generated before middleware, so it cannot use the envelope or the request-ID pipeline; document that exception.

## Testing

- Handler tests use `app.Test` with real route registration.
- Service tests are table-driven and replace repository interfaces.
- Repository tests run against the real database or a container.
- Contract tests compare registered routes and response shapes with `api/openapi.yaml`.
- Filter Fiber's automatic `HEAD` routes when comparing routes to the spec; register `OPTIONS` explicitly if the spec promises it.
- Test the error envelope and status code for every failure path.

## Checklist

- One feature module owns its routes, handler, service, repository, DTOs, and model.
- The handler contains HTTP parsing and mapping only.
- The service accepts `context.Context` plus explicit identity and does not import Fiber.
- The repository implements a consumer-owned interface.
- Cross-module calls go through exported service interfaces.
- `main` owns config, concrete dependencies, and shutdown.
- Framework 404/405 and recovered panics use the error envelope; `501` is the pre-middleware exception.
- `Group`/`Router` scopes modules; mounted sub-apps are reserved for real app boundaries.
- The route table and OpenAPI spec describe the same endpoints, excluding generated HEAD routes.

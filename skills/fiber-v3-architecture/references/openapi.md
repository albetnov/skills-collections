# OpenAPI

## File and version

- One contract per live major version: `api/openapi.yaml` for v1, or `api/openapi.v1.yaml` / `api/openapi.v2.yaml` when two versions are served at once.
- OpenAPI `3.1.0`.
- `servers` contains the base path, for example `/api/v1`.
- `info.version` is the service's semantic version, for example `1.4.0`.
- The path major version and the OpenAPI major version are separate decisions: URL `/api/v2` does not imply OpenAPI 2.x.

## Spec-first workflow

1. Change `api/openapi.yaml` first: path, operation, schemas, status codes, headers, examples.
2. Review the contract with the handler owner.
3. Implement the handler and service against it.
4. Add the automated checks below; they fail when a registered route or response shape is missing from the spec.
5. Keep generated types or clients derived from the spec; do not hand-edit generated output.

The spec is the source of truth for paths, request/response schemas, status codes, and shared headers. Internal implementation details stay out.

## Code-first alternative

[`huma`](https://github.com/danielgtaylor/huma) generates an OpenAPI 3.1 spec from registered operations; its `humafiber` adapter imports `github.com/gofiber/fiber/v3`. The [Fiber recipe](https://docs.gofiber.io/recipes/openapi/) demonstrates the wiring, though its snippets still show the v2 import.

Choose code-first only if the generated spec is committed as `api/openapi.yaml` and every CI check below still runs. Generation removes hand-written spec drift only for operations registered through Huma: `fiber.Config.ErrorHandler` responses (`404`/`405`, recovered panics) and the pre-middleware `501` bypass it, so the route-parity check still applies. The spec-first workflow above is the default.

## Naming

- `operationId`: `<module>_<action>`, for example `users_list`, `users_get`, `users_create`, `users_update`, `users_delete`.
- Tags: one per feature module, for example `users`, `orders`.
- Schema names: domain nouns, for example `User`, `UserCreate`, `UserUpdate`, `UserList`.
- Reusable parameters: `Limit`, `Cursor`, `Sort`, `PathID`, `IdempotencyKey`, `RequestID`.
- Reusable headers: `XRequestID`, `Location`, `XRateLimitLimit`, `XRateLimitRemaining`, `XRateLimitReset`, `RetryAfter`, `ETag`, `Allow`.
- Reusable responses: `BadRequest`, `Unauthorized`, `Forbidden`, `MethodNotAllowed`, `NotFound`, `Conflict`, `PreconditionFailed`, `UnprocessableEntity`, `UnsupportedMediaType`, `TooManyRequests`, `InternalServerError`, `ServiceUnavailable`.

## Components

- Every error that reaches the app error handler references the same `ErrorResponse` schema; the pre-middleware `501` is the framework exception.
- Every list endpoint references the same pagination schema.
- Every authenticated operation uses the same `bearerAuth` security scheme.
- Shared headers live under `components.headers`, not repeated inline.
- Shared parameters live under `components.parameters`.
- Examples are part of the contract; include at least one success and one validation error per module.

## Security

```yaml
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
```

Apply `security` globally and override with `security: []` only on explicitly public endpoints.

## Validation in CI

Four checks, all machine-verifiable. Wire them into one `make api-check` target and run it on every pull request.

### Route parity

Preferred: generate the server from the spec with `oapi-codegen` (`fiber-v3-server`, `generate.strict-server: true`). `RegisterHandlers` registers exactly the documented operations; `ServerInterface` fails to compile while an operation lacks a handler; typed response structs make an undocumented response body a compile error.

Codegen proves spec -> code only. Keep a reverse check that catches ad-hoc `app.Get` routes: build the router without listening and diff `app.GetRoutes(true)` (middleware filtered out) against the spec. Join spec paths with `servers[0].url`, normalize Fiber `:id` and `*` to OpenAPI `{id}`/`{path}`, and fail if either side has a leftover. Ignore mount placeholders and the `HEAD` routes Fiber synthesizes for every `GET`; a `GET` operation covers `HEAD`. Run it as a normal Go test.

### Spec and examples

- `vacuum lint -d -e api/openapi.yaml` fails the build on errors; add rules for the `operationId` pattern, one tag per operation, an `ErrorResponse` reference on every error response, and `bearerAuth` on every protected operation.
- Vacuum's `oas3-valid-media-example`, `oas3-valid-parameter-example`, and `oas3-valid-schema-example` validate every example against its schema. Redocly's `no-invalid-media-type-examples` covers the same when the project already uses Node.

### Runtime responses

- `github.com/oapi-codegen/fiber-v3-middleware` validates each request against the spec in-process.
- Validate responses with `openapi3filter.ValidateResponse` in tests, or run `schemathesis run api/openapi.yaml --url <test-server> --checks all` against a seeded instance. Schemathesis derives cases from the spec, so response drift fails without hand-written fixtures.

### Breaking changes and generated artifacts

- `oasdiff breaking --fail-on ERR <merge-base>.yaml api/openapi.yaml` fails when a change breaks clients; the fix is a new path major version, not a spec edit.
- Regenerate clients/types and run `git diff --exit-code` so stale generated output fails the build.

## Versioning and deprecation

- A breaking API change creates a new path major version and a new spec section or a new spec file if the versions diverge enough.
- Do not mark a field deprecated in the spec while still requiring it.
- Mark deprecated operations with `deprecated: true` and describe the replacement.
- Pair deprecation with the `Deprecation: @<unix-seconds>`, `Sunset: <HTTP-date>`, and `Link` response headers from the HTTP contract.

## Starter spec

Copy [`assets/openapi.yaml`](../assets/openapi.yaml) into `api/openapi.yaml` and replace the example `users` resource. Keep the shared error, pagination, header, and security components.

## Checklist

- The spec is OpenAPI 3.1 and lives at `api/openapi.yaml` (or one spec file per live major version).
- The base path matches the version group, for example `/api/v1`.
- Every operation has an `operationId`, tag, success response, and documented error responses.
- Every error references the shared `ErrorResponse`.
- Every authenticated operation uses `bearerAuth`.
- Shared headers and parameters are components, not inline copies.
- The spec lints cleanly, route parity passes, and the contract tests pass.
- Deprecated operations carry `deprecated: true` and a replacement path.

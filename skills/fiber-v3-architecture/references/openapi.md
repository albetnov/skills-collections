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
4. Add a contract test that fails when a registered route or response shape is missing from the spec.
5. Keep generated types or clients derived from the spec; do not hand-edit generated output.

The spec is the source of truth for paths, request/response schemas, status codes, and shared headers. Internal implementation details stay out.

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

- Lint the spec (for example with Spectral) and fail on errors.
- Validate that every registered Fiber route appears in the spec and vice versa.
- Validate request/response examples against their schemas.
- Run contract tests against the real handler for the main success path and every documented error status.
- Treat an undocumented endpoint as a failing build.

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
- The spec lints cleanly and contract tests pass.
- Deprecated operations carry `deprecated: true` and a replacement path.

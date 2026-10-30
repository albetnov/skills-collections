# HTTP contract

This is the external API contract. Runtime details such as `fiber.NewError`, `Bind`, and Ctx lifetime belong to the `fiber-v3` skill.

## Resource paths

- Collections use plural nouns: `/users`, `/orders`.
- Items use an opaque identifier: `/users/{id}`.
- Subresources stay shallow: `/users/{id}/orders`.
- Paths use `kebab-case`.
- IDs are opaque strings in JSON and paths. Never expose auto-increment database IDs as the public identifier.
- Prefer a resource over an RPC verb. When no resource fits a state transition, use a small action endpoint such as `POST /users/{id}/suspend`; keep it rare and document it.

## Methods and status codes

| Operation | Success |
|---|---|
| `GET` collection | `200 OK` |
| `GET` item | `200 OK` |
| `POST` create | `201 Created` + `Location` |
| `PUT` replace | `200 OK` or `204 No Content` |
| `PATCH` partial update | `200 OK` or `204 No Content` |
| `DELETE` | `204 No Content`; `202 Accepted` for async deletion |
| `HEAD` | Same status as `GET`, no body |
| `OPTIONS` | `204 No Content` when CORS or an explicit `OPTIONS` route handles it; otherwise `405` |

Client and server errors:

| Status | Use |
|---|---|
| `400 Bad Request` | Malformed syntax, unparseable body, invalid JSON |
| `401 Unauthorized` | Missing or invalid credentials |
| `403 Forbidden` | Authenticated but not allowed |
| `404 Not Found` | Missing resource, or a resource hidden from this caller |
| `405 Method Not Allowed` | Path exists for another method; include `Allow` |
| `409 Conflict` | Duplicate, stale version, or state conflict |
| `412 Precondition Failed` | `If-Match` or another precondition failed |
| `415 Unsupported Media Type` | Unsupported request content type |
| `422 Unprocessable Entity` | Syntactically valid but semantically invalid; field validation |
| `429 Too Many Requests` | Rate limit exceeded; include `Retry-After` |
| `500 Internal Server Error` | Unhandled server failure |
| `501 Not Implemented` | Unknown method token or method not in `RequestMethods`; generated before middleware |
| `502 Bad Gateway` | Upstream returned an invalid response |
| `503 Service Unavailable` | Temporarily unavailable; include `Retry-After` |
| `504 Gateway Timeout` | Upstream timed out |

Use `400` for syntax and `422` for validation. Use `409` for state or uniqueness conflicts, not `400`. Use `404` rather than `403` when revealing existence would leak information.

## Success shapes

A single resource is returned directly:

```json
{
  "id": "usr_01J...",
  "email": "ada@example.com",
  "name": "Ada",
  "status": "active",
  "created_at": "2026-10-30T12:00:00Z",
  "updated_at": "2026-10-30T12:00:00Z"
}
```

A collection uses cursor pagination:

```json
{
  "items": [],
  "next_cursor": "eyJpZCI6..."
}
```

- `limit` defaults to 20 and is capped at 100.
- `cursor` is opaque. Clients pass it back unchanged.
- `next_cursor` is `null` on the last page.
- Do not return `total` by default; add it only when the count is cheap and useful.
- `POST` returns the created resource and a `Location` header.
- `DELETE` returns an empty body with `204`.

## Error envelope

Every error that reaches the app error handler uses the same shape:

```json
{
  "error": {
    "code": "user_not_found",
    "message": "User not found",
    "request_id": "req_01J...",
    "details": [
      {
        "field": "email",
        "issue": "must be a valid email address"
      }
    ]
  }
}
```

- `code` is a stable, machine-readable `snake_case` identifier.
- `message` is a human-readable summary.
- `request_id` is always present on envelope errors; the pre-middleware `501` is the exception.
- `details` is optional and appears for validation or multi-field failures.
- Do not put stack traces, SQL, upstream URLs, or internal identifiers in the response.
- Do not add a second error shape for a special endpoint.
- A `501` for an unknown method is generated before middleware; document it as the one response that does not use the envelope or the request-ID pipeline.

## Naming and formats

- JSON fields and query parameters: `snake_case`.
- Paths: plural `kebab-case`.
- Enum values: `lower_snake_case`.
- Timestamps: RFC 3339 in UTC, for example `2026-10-30T12:00:00Z`.
- Dates: `YYYY-MM-DD`.
- Durations: integer seconds with a `_seconds` suffix, for example `retry_after_seconds`.
- Money: integer minor units plus an ISO 4217 currency code, for example `amount_cents` and `currency`.
- IDs: strings, even when the underlying value is numeric.
- Booleans: `true`/`false`; do not use `0`/`1` or `"yes"`/`"no"`.
- Return every field declared in the schema. Use `null` for an absent optional value rather than omitting fields ad hoc.

## Headers

### Request

- `Authorization: Bearer <token>` for authenticated endpoints.
- `Content-Type: application/json` for JSON bodies.
- `Accept: application/json`.
- `X-Request-ID` from the client when it has one; generate one otherwise.
- `Idempotency-Key` on retryable unsafe writes that create or charge.
- `If-Match` for optimistic concurrency on update/delete.
- `If-None-Match` for conditional reads.
- `Accept-Language` when localized messages are supported.

### Response

- `Content-Type` matching the body.
- `X-Request-ID` echoing or returning the generated ID.
- `Location` on `201 Created`; emit an absolute URI or a valid relative reference.
- `ETag` on cacheable representations.
- `Cache-Control` and `Vary` on cacheable responses.
- `Retry-After` on `429` and `503`.
- `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` on rate-limited APIs. `X-RateLimit-Reset` is seconds until the window resets.
- `Deprecation: @<unix-seconds>`, `Sunset: <HTTP-date>`, and `Link` on deprecated endpoints.

## Versioning

- Major version in the path: `/api/v1`.
- `info.version` in OpenAPI uses semantic versioning, for example `1.4.0`.
- Non-breaking changes: add an optional field, add an endpoint, relax validation, add a new optional query parameter.
- Breaking changes: remove or rename a field, change a type, add a required field, change a status code, change semantics, change authentication, or remove an endpoint.
- A breaking change creates `/api/v2` and a new module registration. Do not branch on a version header inside one handler.
- Deprecate an endpoint with `Deprecation: @<unix-seconds>`, `Sunset: <HTTP-date>`, and a `Link` to the replacement. Keep the old version working through its announced sunset date.
- Treat adding an enum value as potentially breaking for strict clients; document it and prefer a new field when clients may reject unknown values.

## Idempotency

Use `Idempotency-Key` on unsafe requests that must be safe to retry, especially create and payment operations.

- The client sends a unique key per logical operation.
- The server stores the key, a fingerprint of method/path/body, and the response for 24 hours.
- Repeating the same key with the same fingerprint replays the stored response.
- Repeating the same key with a different fingerprint returns `409 Conflict`.
- Mark a replayed response with `Idempotency-Replayed: true`.
- Scope keys per authenticated principal.

Fiber's built-in idempotency middleware defaults to `X-Idempotency-Key`, a 30-minute lifetime, and keys by the key alone. To match this contract, configure `KeyHeader: "Idempotency-Key"`, `Lifetime: 24*time.Hour`, and a `KeyScope` that identifies the caller. The built-in middleware does not compare method/path/body and does not emit `Idempotency-Replayed`; add a fingerprint wrapper or custom middleware when the strict `409` and replay header behavior is required.

## Pagination, filtering, sorting

- Cursor pagination is the default: `limit`, `cursor`, `next_cursor`.
- Offset pagination is acceptable only for admin or reporting APIs where page numbers are part of the contract.
- Filters are flat query parameters: `status=active`, `created_after=2026-01-01`.
- Sorting uses comma-separated fields: `sort=created_at,-name`; a leading `-` means descending.
- Validate every sort field against an allowlist.
- Reject unknown filters rather than silently ignoring them.

## Caching and conditional requests

- `GET` representations may carry `ETag`.
- `If-None-Match` matching the current `ETag` returns `304 Not Modified`.
- `If-Match` that does not match returns `412 Precondition Failed`. Fiber's `etag` middleware covers `304`; implement the `412` precondition check in the handler or service.
- `Cache-Control: private` for per-user responses; `public` only for genuinely shared responses.
- `Vary` lists every request header that changes the representation.
- Never cache a response that sets a cookie or depends on `Authorization` unless the response explicitly permits shared caching.

## Rate limiting

- Return `429 Too Many Requests` with `Retry-After`.
- Include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` on every rate-limited response. Fiber's limiter emits these by default; a gateway that emits `RateLimit-*` should be normalized.
- Document the limit and window in OpenAPI.
- Keep rate-limit keys stable and do not expose raw credentials in headers or logs.

## Checklist

- Paths are plural, shallow, and `kebab-case`.
- Methods and status codes follow the tables above.
- Every error that reaches the app error handler uses the nested envelope; the pre-middleware `501` is the exception.
- JSON is `snake_case`; timestamps are RFC 3339 UTC; money uses minor units.
- Request and response headers follow the conventions above.
- `Location` is an absolute URI or a valid relative reference.
- Rate-limit headers are `X-RateLimit-*`.
- Deprecation uses a structured-field date, not a boolean.
- The major version is in the path; breaking changes create a new version.
- Retryable writes accept `Idempotency-Key`.
- Collections use cursor pagination unless there is a documented reason not to.
- Every contract change is reflected in `api/openapi.yaml`.

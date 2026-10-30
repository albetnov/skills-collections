# Request binding

## Binding sources

`Bind().All` fills a struct from five sources, in this precedence order:

1. URI parameters
2. Request body
3. Query parameters
4. Request headers
5. Cookies

The first source that provides a non-zero value for a field wins. A zero value from an earlier source does not block a later source. A non-zero value you set on the destination before the call is never overwritten.

The body is a source only when the request has a non-empty body and a non-empty `Content-Type`. Without `Content-Type`, the body is not read, so a streamed body stays available to `BodyStream`.

A nested struct, slice, or map set by an earlier source is kept as a whole; later sources do not fill its remaining zero fields.

`All` requires a non-nil pointer to a struct. A map or other destination returns `fiber.ErrUnprocessableEntity`.

Override precedence with a `binding_source` tag on a top-level field:

```go
type Request struct {
    Name string `binding_source:"query,header,cookie,body,uri" query:"name" header:"X-Name" json:"name"`
}
```

- Valid names are `uri`, `body`, `query`, `header`, and `cookie`.
- A partial list disables the omitted sources.
- The tag is read only from top-level fields, and only one is allowed.
- An invalid name or duplicate tag returns a plain error, not a `*BindError`, and becomes a 500 by default.

## Destination rules

- `Bind().Body`, `JSON`, `XML`, `MsgPack`, `CBOR`, `Form`, `Query`, `Header`, `Cookie`, `URI`, and `All` take a pointer destination.
- Pointer fields distinguish missing from empty: `*string`, `*[]string`, and `*Preferences` are `nil` when the source has no value.
- A nil map passed by value fails; pass a pointer and Fiber allocates the map.
- A nil pointer to a map also fails.
- Struct destinations run the configured `StructValidator`; maps and other non-struct destinations skip validation.

## Lifetime

Bound string values alias the request buffers. They are valid only within the handler. `Immutable` does not apply to bound values.

```go
type User struct {
    ID   string `json:"id"`
    Tags []string `json:"tags"`
}

func (h *Handler) create(c fiber.Ctx) error {
    var in User
    if err := c.Bind().Body(&in); err != nil {
        return err
    }

    user := User{
        ID:   strings.Clone(in.ID),
        Tags: append([]string(nil), in.Tags...),
    }
    return h.service.Create(c.Context(), user)
}
```

Copy every string, byte slice, and nested slice that escapes the handler. Copy the fields before starting a goroutine or storing the struct in a cache.

On a form request, `Form`, `FormValue`, and `MultipartForm` lowercase parts of the request's own `Content-Type`. A value read earlier with `Get(HeaderContentType)` can change during the call; copy it first.

A deeply nested key can make a bind allocate large intermediate slices. Bound nesting depth and input size, not just total bytes.

## Validation

Fiber does not bundle a validator. Implement `fiber.StructValidator`:

```go
type StructValidator interface {
    Validate(out any) error
}
```

```go
app := fiber.New(fiber.Config{
    StructValidator: &structValidator{validate: validator.New()},
})
```

- Validation runs after binding succeeds, on the value passed to the bind method.
- `All` validates once, on the merged struct.
- A validator error is returned as-is, not wrapped in `BindError`. Returned to the default error handler, it becomes a 500. Map it to a client status yourself.
- `WithAutoHandling` converts a validation error to `400 Bad Request` only for `Bind().All`.
- `SkipValidation` bypasses the validator for the rest of the request until `SkipValidation(false)`.
- `StructValidator` runs only for struct destinations or pointers to structs.

Field tags support `default:` and `required`:

```go
type Search struct {
    Term  string   `query:"term,required"`
    Page  int      `query:"page,default:1"`
    Tags  []string `query:"tags,default:go|fiber"`
}
```

- Defaults apply to `query`, `form`, `header`, `cookie`, `respHeader`, and `uri` tags, not JSON/XML/CBOR/MsgPack bodies.
- A present-but-empty key does not get the default.
- A `uri` parameter always gets a value when the route declares it, so a default applies only to an undeclared name.
- `required` and `default` cannot be combined.

## Bind errors

`BindError` wraps binding failures; validator errors are separate.

```go
if err := c.Bind().Body(&in); err != nil {
    var be *fiber.BindError
    if errors.As(err, &be) {
        // malformed or missing input
        return fiber.NewError(fiber.StatusBadRequest, be.Error())
    }
    return fiber.NewError(fiber.StatusUnprocessableEntity, err.Error())
}
```

Use `BindError` to distinguish source errors. Use the configured validator's error type for field-level validation details.

## Extractors

The `extractors` package is shared by authentication, session, and CSRF middleware.

- `FromHeader`, `FromAuthHeader`, `FromCookie`, `FromParam`, `FromForm`, `FromQuery`, and `FromCustom` read one source.
- `Chain` tries children in order; an error moves to the next child, and the last error is returned if none succeeds.
- `Resolve(e, c)` returns `(Result, error)`; `Result.Value` is the extracted value. Trust `Result.Source` only when `Result.Resolved` is true and `err == nil`. When `Resolved` is false, a chain's own `Extract` answered and `Key`/`Source` are declared first-child metadata, not provenance. Error paths may return static or last-child metadata; make security decisions only on resolved success.
- `FromForm` reads through `FormValue`, so the query string wins over the form body.
- `FromParam` decodes exactly once, independent of `UnescapePath`.
- `FromAuthHeader` returns `ErrNotFound` when multiple `Authorization` lines make the credential ambiguous.
- Put credential sources in security order: header first, cookie next, query last. Query credentials leak into logs, history, and referrers.
- A session-ID extractor that validates an ID must return the ID unchanged; the same value is written back and used for lookup.

## Checklist

- Every destination is a non-nil pointer to a struct for `All`.
- The body has a `Content-Type` when body binding is expected.
- Every bound value that escapes the handler is copied.
- Validation errors are mapped to a client status.
- `SkipValidation` is scoped to the request and restored when needed.
- Credential extraction prefers headers and avoids query strings.

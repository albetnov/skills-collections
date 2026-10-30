# Fiber client

The client is a separate lifecycle from the server. Its rules are about pooled requests, pooled responses, and connection reuse.

## Client concurrency

A configured `Client` can send requests from many goroutines at once. Changing its configuration while requests are in flight needs your own synchronization.

Set TLS, base URL, timeout, and transport settings before the first request. fasthttp copies TLS configuration for a host when it first connects there; later `SetTLSConfig` or `SetCertificates` calls do not reach an existing host entry.

## REST helpers

`client.Get`, `Post`, `Put`, `Patch`, `Delete`, `Head`, `Options`, and `Query` acquire a request internally. `Response.Close` releases both the response and the request the helper created.

```go
resp, err := client.Get("https://example.com/users")
if err != nil {
    return err
}
defer resp.Close()
```

When a helper returns an error, there is no response to close; the helper already released its request.

## Requests and responses

### Acquired requests

```go
req := client.R()
defer client.ReleaseRequest(req)
```

`AcquireRequest` and `client.R()` return a pooled request that you own. Release it with `ReleaseRequest`; never use it afterward. A request you acquired stays yours even when a response is closed.

Request headers, query parameters, path parameters, and files are valid only until the request is released. Copy values you need later.

### Acquired responses

```go
resp, err := client.Do(req)
if err != nil {
    return err
}
defer resp.Close()
```

- `Response.Close` releases the response back to the pool and releases a helper-created request.
- `AcquireResponse`/`ReleaseResponse` are for manual pooling; do not use a response after release.
- `Response.Reset` clears the response for reuse.
- `Response.Header` returns a copy that survives release. `Response.Headers` and `Response.Cookies` are valid only until release.

### Streaming

Enable streaming for large bodies or SSE:

```go
client.SetStreamResponseBody(true)

resp, err := client.Get(url)
if err != nil {
    return err
}
defer resp.Close()

_, err = io.Copy(dst, resp.BodyStream())
```

`BodyStream` consumes the body as it is read. A later `Body()` call may return an empty slice. A client timeout also ends reads from the stream.

## Cookie jar

```go
jar := client.AcquireCookieJar()
defer client.ReleaseCookieJar(jar)

client.SetCookieJar(jar)
```

- A `CookieJar` is safe for concurrent use except `Release`, which must not run concurrently with other methods.
- `ReleaseCookieJar` empties the jar and returns it to the pool. Do not use the jar afterward.
- The jar stores its own copies. Cookies returned by `CookieJar.Get` can be released with `fasthttp.ReleaseCookie`.

## Response size

`MaxResponseBodySize` limits buffered bodies. A client from `New` starts at 100 MiB; a client wrapped around a `fasthttp.Client`, `HostClient`, or `LBClient` keeps that client's limit.

Set the limit before the first request. fasthttp allocates from the declared `Content-Length` or chunk size before the body arrives; without a limit, a malicious server can cause a fatal allocation that `recover` cannot catch. A streamed body is not buffered and not limited.

## Redirects and sensitive headers

`SetRedirectSensitiveHeaders` names headers that must not follow a redirect to another host, such as `X-API-Key`. They are dropped together with `Authorization`, `Proxy-Authorization`, `Proxy-Authenticate`, `WWW-Authenticate`, `Cookie`, and `Cookie2` when the target is neither the original hostname (on any port) nor one of its subdomains. A redirect to a subdomain, or to the same host on another port, keeps them.

`Response.Close` is not a redirect policy; configure `SetMaxRedirects` explicitly.

## Hooks

Request and response hooks run once per request and may run concurrently. Mutate the `Request` or `Response` the hook receives, not the `Client`. Changing the client configuration while requests are in flight changes what other requests read.

## Transport reuse

`NewWithClient`, `NewWithHostClient`, and `NewWithLBClient` wrap an existing fasthttp transport so connection pools, dialers, and load balancing are reused. `CloseIdleConnections` closes idle keep-alive connections without interrupting active ones.

`Do`, `DoTimeout`, `DoDeadline`, and `DoRedirects` bypass Fiber's request pipeline: base URL, default headers, query/path params, cookies, hooks, client timeout, and retry configuration are not applied. Transport settings and response streaming still apply.

## Checklist

- Every helper response calls `Close`.
- Every acquired request calls `ReleaseRequest`.
- Every acquired response calls `ReleaseResponse`; a helper response uses `Close`.
- Every cookie jar calls `ReleaseCookieJar`.
- No pooled request, response, jar, header iterator, or body stream is used after release/close.
- TLS and response-size settings are set before the first request.
- Hooks do not mutate the shared client.

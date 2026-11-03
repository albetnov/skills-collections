# Serving and limits

Upload validation and response hardening are separate controls. A file that passed admission is still dangerous if it is served with a client-chosen type, inline on the app origin, or from a server that buffered an unbounded body.

## Response contract

| Header | Value | Reason |
|---|---|---|
| `Content-Type` | Server map from sniffed format to MIME | Stored metadata is another client claim |
| `X-Content-Type-Options` | `nosniff` | Stops browsers from reinterpreting bytes |
| `Content-Disposition` | `inline` only for raster images; `attachment` for PDF, SVG, office, unknown | Direct navigation to active content is stored XSS |
| `Content-Security-Policy` | `default-src 'none'; sandbox` on the media origin | Neutralizes script in anything served inline |
| `Cache-Control` | `public, max-age=31536000, immutable` for content-addressed keys; `private, no-store` otherwise | Immutability is safe only when the key changes with the bytes |
| `Cross-Origin-Resource-Policy` | `cross-origin` when the app embeds it, otherwise `same-site` | Keeps other origins from embedding private media |
| `Accept-Ranges` | `bytes` | Large media seeks and resumes |
| `ETag` | Storage ETag | Conditional requests; not a content hash for multipart |

Build the disposition from a server-side display name, never the uploaded filename. Strip CR, LF, quotes, and control characters, then RFC 5987-encode non-ASCII. A filename is data, not a header.

```ts
function contentDisposition(name: string) {
	const ascii = name.replace(/[^\x20-\x7e]|["\\\r\n]/g, "_");
	return `inline; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(name)}`;
}
```

SVG and PDF use `attachment`, not `inline`. If the product previews PDFs inline, put them behind a viewer that fetches them from the media origin, not by navigating the app origin to the file.

## Origin isolation

Serve user content from an origin that holds no application authority:

- A dedicated media host (at minimum a separate hostname; a separate registrable domain is stronger).
- No `Set-Cookie` on that host, ever.
- App session cookies are `__Host-` prefixed, host-only, `Secure`, `SameSite=Lax` or stricter. A cookie with `Domain=.example.com` is sent to every subdomain, including the media host.
- App CSP restricts `img-src` and `frame-src` to the media origin.
- Private media is served through a short-TTL signed URL or an authenticated proxy that checks authorization before signing. An unguessable key is not authorization.

## Caps at every layer

| Layer | Control |
|---|---|
| Proxy / CDN | `client_max_body_size`, body timeout, header timeout; reject `Transfer-Encoding` together with `Content-Length` |
| Framework | Body limit and multipart limits: file size, file count, field count, field size, part count |
| Application | Counted stream cap and per-file cap; reject before decode |
| Storage | POST `content-length-range`, PUT signed length, or provider-specific range |
| Decoder | Pixel/edge cap, page/animation cap, timeout, concurrency limit |
| Archive | Expanded bytes, entry count, compression ratio, nesting depth |

The effective cap is the smallest one the request must pass. A 100 MB gateway in front of a 2 MB policy is a 2 MB service; a 2 MB framework limit in front of a 100 MB policy is a 2 MB service that wastes bandwidth. Set one number and keep the layers consistent.

## Archives and active documents

- Never decompress untrusted archives on the request path. If the product needs it, do it in a sandboxed worker with expanded-size, ratio, entry-count, and depth caps, plus a wall-clock timeout.
- Reject absolute paths, `..` traversal, symlinks, and duplicate entry names before extraction.
- PDF and office parsers are attack surface. Store them, scan them, and serve them as attachments; do not parse them inline.
- A file that is only ever downloaded does not need a decoder, but it still needs a type allowlist, a size cap, a scan, and a disposition.

## Publish pipeline

1. Upload lands under a private `uploads/` prefix, owned by a pending row.
2. Finalize verifies size, type, and digest; a worker decodes and records dimensions.
3. A malware scan runs in the queue; the object stays quarantined until it passes.
4. Publish copies or promotes to the immutable media prefix and updates the row; the private key is deleted or expired.
5. Lifecycle aborts incomplete multipart uploads and expires pending objects that never finalized.

Do not scan on the request thread, and do not publish before the scan. Both failure modes turn a queue into a timeout or a bypass.

## Logging

Log the reject code, byte count, sniffed format, key, user, and request id. Do not log the presigned URL (a bearer token), raw file bytes, or EXIF. Logging the client's claimed MIME next to the sniffed one is how you find clients that need a fallback path.

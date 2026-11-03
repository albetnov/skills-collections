# Upload handoff

The browser produced the final bytes; now it hands them to storage without making the app server a media proxy. The server issues a policy, the client uploads directly, and the server finalizes. The server-side half of this contract is the `backend-upload-verifier` skill.

## Flow

1. Client has the final blob and metadata: byte length, MIME type, SHA-256, width, height.
2. `POST /uploads` with that metadata. The server checks ranges, creates a pending row, and returns a presigned target.
3. Client uploads directly to storage. Progress comes from the transport; the server is not in the data path.
4. Client calls `POST /uploads/:id/complete` with the upload id only.
5. Server verifies the stored object, decodes it, and marks it ready.

The client never sends the destination key, the expected size, or the expected digest at step 4. Those are server-side expectations from step 2; a client that restates them can pass its own check.

## Presign contract

```json
{
  "mime": "image/webp",
  "bytes": 482913,
  "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "width": 1600,
  "height": 1200
}
```

```json
{
  "uploadId": "01J...",
  "method": "POST",
  "url": "https://bucket.s3.us-east-1.amazonaws.com/",
  "fields": { "key": "uploads/...", "Policy": "...", "X-Amz-Signature": "..." },
  "expiresAt": "2026-11-03T12:15:00Z"
}
```

For a PUT target, return `method: "PUT"`, no `fields`, and a `headers` object containing the headers the signature covers (`Content-Type`; any checksum header the provider requires in the request; never `Content-Length`). The checksum may instead be embedded in the signed URL by the SDK; return exactly what the client must send, and nothing it must not.

The digest encoding is part of the contract. Lowercase hex is the simplest for the client; the server converts once at the provider boundary (S3 checksum fields are base64, GCS content hashes are hex). State the encoding in the API schema; "SHA-256" alone is ambiguous at the boundary.

Presign with `blob.type`, not the type you asked the encoder for. A WebP request that fell back to JPEG must request a JPEG policy; a policy pinned to `image/webp` will reject the upload at the provider before the server ever sees it.

## Upload

POST with a form is the browser default: the policy travels in form fields, and S3 validates the size range and checksum.

```ts
function uploadForm(
	target: { url: string; fields: Record<string, string> },
	blob: Blob,
	onProgress: (fraction: number) => void,
	signal: AbortSignal,
) {
	return new Promise<void>((resolve, reject) => {
		const body = new FormData();
		for (const [name, value] of Object.entries(target.fields)) body.append(name, value);
		body.append("file", blob, "upload");

		const xhr = new XMLHttpRequest();
		xhr.open("POST", target.url);
		xhr.upload.onprogress = (event) => {
			if (event.lengthComputable) onProgress(event.loaded / event.total);
		};
		xhr.onload = () => {
			if (xhr.status >= 200 && xhr.status < 300) resolve();
			else reject(new Error(`upload failed: ${xhr.status}`));
		};
		xhr.onerror = () => reject(new Error("upload network error"));
		xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
		signal.addEventListener("abort", () => xhr.abort(), { once: true });
		if (signal.aborted) {
			reject(new DOMException("aborted", "AbortError"));
			return;
		}
		xhr.send(body);
	});
}
```

The file is the last field. Do not set `Content-Type` on the request; the browser must add the multipart boundary. The policy's `Content-Type` is a form field.

PUT is simpler, but `fetch` has no upload-progress event; use XHR when progress matters, and send exactly the signed headers:

```ts
function uploadPut(
	target: { url: string; headers?: Record<string, string> },
	blob: Blob,
	onProgress: (fraction: number) => void,
	signal: AbortSignal,
) {
	return new Promise<void>((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		xhr.open("PUT", target.url);
		for (const [name, value] of Object.entries(target.headers ?? {})) {
			xhr.setRequestHeader(name, value);
		}
		xhr.upload.onprogress = (event) => {
			if (event.lengthComputable) onProgress(event.loaded / event.total);
		};
		xhr.onload = () => {
			if (xhr.status >= 200 && xhr.status < 300) resolve();
			else reject(new Error(`upload failed: ${xhr.status}`));
		};
		xhr.onerror = () => reject(new Error("upload network error"));
		xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
		signal.addEventListener("abort", () => xhr.abort(), { once: true });
		if (signal.aborted) {
			reject(new DOMException("aborted", "AbortError"));
			return;
		}
		xhr.send(blob);
	});
}
```

A checksum hoisted into the URL needs no header. A checksum signed as a header must be sent byte-for-byte; computing it over a re-encoded blob is a mismatch waiting to happen.

## Progress

There are two phases and they should look different in the UI:

- Transfer: bytes uploaded / total bytes, from `xhr.upload.onprogress`.
- Commit: "verifying" while finalize runs. A large object may spend seconds decoding and scanning; a progress bar that sits at 100% during that time looks stuck.

Do not derive progress from a timer, and do not show a percentage when `lengthComputable` is false.

## Retry

| Response | Action |
|---|---|
| Network error, timeout | Retry with backoff and jitter; the same blob and upload id |
| `408`, `429`, `5xx` | Retry; honor `Retry-After` |
| `403` from an expired URL | Request a fresh presign for the same pending row; do not retry the expired URL |
| `400`, `413`, `415` | Stop; the policy or the file is wrong |
| Checksum failure | Stop; the bytes changed between hashing and upload |

Backoff starts around 500 ms, doubles, caps at 30 s, and adds jitter. Five attempts is enough; a retry loop that outlives the presigned URL is a spinner with extra steps.

A failed POST or single PUT is atomic at S3: no partial object is published. A failed multipart upload leaves parts until the server aborts it, so the abort path is part of retry, not cleanup.

## Large files and resumable uploads

- Below roughly 10 MB, one request is simpler.
- Above that, S3 multipart: the server creates the multipart upload, presigns each part, the client slices the blob into 8–16 MB parts, retries each part, and returns `{ partNumber, etag }`; the server completes. Complete is not the client's call: the server validates the final checksum and size.
- `tus` is an alternative when the storage provider does not offer multipart. It needs its own server endpoint and a resumable protocol on both ends.
- Browser-side "resume" that only remembers a byte offset is not resumable unless the server accepts ranged PUTs and tracks the offset. Do not advertise resume without that.

## Offline queue

```ts
type Queued = {
	id: string;
	blob: Blob;
	mime: string;
	sha256: string;
	bytes: number;
	attempts: number;
	createdAt: number;
};
```

- Store the blob and metadata in IndexedDB (structured clone supports `Blob`). Do not store the presigned URL: it expires. Presign at send time.
- Request persistence with `navigator.storage.persist()` and warn when `navigator.storage.estimate()` shows the queue near the quota.
- Retry on `online`, on `visibilitychange` to visible, and at app start. Background Sync is Chromium-only; it is an optimization, not the only drain path.
- Bound the queue by count and total bytes. A 2 GB queue that the browser evicts is worse than a visible failure.
- Keep the queue item until the server marks the upload ready, not until bytes finish transferring.

## Cancel and CORS

- `signal.abort()` / `xhr.abort()` stops the transfer. Tell the server to delete the pending object or abort the multipart upload; otherwise it waits for lifecycle expiry.
- `keepalive` is not a large-upload feature; its payload limit is small.
- The bucket CORS policy must allow the app origin, the method, and every header the signature covers; expose only the response headers the client reads. Presigned requests do not need credentials, so `credentials: "omit"`.
- Never log the presigned URL or store it in analytics; it is a bearer token.

## Metadata at the boundary

The client sends a display name, not a key. The server derives the key, sanitizes the display name, and returns it with the media record. Width, height, and format are hints from the client until the server decodes the stored object; keep them out of authorization decisions.

# Storage policies

Presigning moves enforcement from this process to the provider. Pin every property the provider can enforce, and verify at finalize the ones it cannot. A presigned URL is a bearer token: anyone holding it can upload until it expires, so short expiry and a server-chosen key are part of the policy.

## What each provider can pin

| Provider | Upload form | Size | Exact content type | Digest | Notes |
|---|---|---|---|---|---|
| S3 | POST policy | `content-length-range` (range) | `Content-Type` condition | `x-amz-checksum-algorithm` + `x-amz-checksum-sha256` (base64) | Best browser path; key can be pinned exactly |
| S3 | presigned PUT | signed `content-length` (exact only) | signed `Content-Type` | hoisted into the signed URL by the JS SDK | No range; one key per attempt |
| R2 | presigned PUT | not expressible in the URL | signed `Content-Type` | not part of the documented policy surface | **POST is not supported**; verify at finalize |
| GCS | presigned PUT | `x-goog-content-length-range: MIN,MAX` (signed header) | signed `Content-Type` | signed `Content-MD5` | Header must be sent by the client; exact `content-length` also works |
| GCS | policy document | `content-length-range` | `starts-with` / exact condition | `Content-MD5` if signed | The form-upload equivalent; more moving parts |
| GCS | resumable session | `x-upload-content-length` at initiation | metadata at initiation | `Content-MD5` on completion | Server initiates the session and hands over the URI |

An exact-size PUT is a real control: SigV4 signs `content-length`, so a body of any other size fails the signature. It cannot express "up to 2 MB"; use a POST policy when the size is not known before the presign request.

## S3 POST: the default browser path

The client sends a hash of the final encoded blob; the server signs it into the policy. The upload fails if the type, size range, key, or digest differs.

```ts
import { createPresignedPost } from "@aws-sdk/s3-presigned-post";
import { S3Client } from "@aws-sdk/client-s3";
import { randomUUID } from "node:crypto";

const s3 = new S3Client({ region: process.env.AWS_REGION });
const MAX_BYTES = 2 * 1024 * 1024;
const ALLOWED_MIME = new Set(["image/webp", "image/jpeg", "image/png"]);

export async function authorizeUpload(
	userId: string,
	req: { bytes: number; mime: string; sha256: string },
) {
	if (!Number.isInteger(req.bytes) || req.bytes < 1 || req.bytes > MAX_BYTES) {
		throw new Reject("TOO_LARGE");
	}
	if (!ALLOWED_MIME.has(req.mime)) throw new Reject("FORMAT");
	if (!/^[0-9a-f]{64}$/.test(req.sha256)) throw new Reject("CHECKSUM");

	const key = `uploads/${userId}/${randomUUID()}`;
	const checksumB64 = Buffer.from(req.sha256, "hex").toString("base64");
	const { url, fields } = await createPresignedPost(s3, {
		Bucket: process.env.BUCKET!,
		Key: key,
		Expires: 300,
		Conditions: [
			["content-length-range", 1, MAX_BYTES],
			["eq", "$key", key],
			["eq", "$Content-Type", req.mime],
			["eq", "$x-amz-checksum-algorithm", "SHA256"],
			["eq", "$x-amz-checksum-sha256", checksumB64],
		],
		Fields: {
			"Content-Type": req.mime,
			"x-amz-checksum-algorithm": "SHA256",
			"x-amz-checksum-sha256": checksumB64,
		},
	});

	const uploadId = await db.uploads.insert({
		key,
		userId,
		bytes: req.bytes,
		mime: req.mime,
		checksumB64,
		digestHex: req.sha256,
		status: "pending",
		expiresAt: new Date(Date.now() + 60 * 60_000), // row outlives the URL
	});
	return {
		uploadId,
		key,
		url,
		fields,
		expiresAt: new Date(Date.now() + 300_000).toISOString(),
	};
}
```

`createPresignedPost` returns a `fields` object containing the policy, signature, key, and the form fields above. The browser appends every field, then the file last. Do not set a `Content-Type` header on the `fetch` request: the browser must generate the multipart boundary, and the form field carries the type.

The API contract carries the digest as lowercase hex; S3 form fields are base64. Convert once at the provider boundary and store the value the provider will return for `HeadObject`. A hex digest in `x-amz-checksum-sha256` is a different string and fails the exact-match condition.

The policy pins the declared form field, not the bytes. A PNG announced as `image/webp` satisfies every condition and lands in the bucket; the decode is what rejects it. That split is deliberate: storage enforces the envelope, the server enforces the content.

## S3 PUT

Use PUT when the browser client already has a presigned-URL flow, or when the file is large enough to need multipart. Sign the exact length; a range needs POST.

```ts
import { PutObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const checksumBase64 = Buffer.from(sha256Hex, "hex").toString("base64");
const url = await getSignedUrl(
	s3,
	new PutObjectCommand({
		Bucket: process.env.BUCKET!,
		Key: key,
		ContentType: mime,
		ContentLength: bytes, // signed: any other body length fails
		ChecksumSHA256: checksumBase64, // hoisted into the signed query
	}),
	{
		expiresIn: 300,
		signableHeaders: new Set(["content-type", "content-length"]),
	},
);
```

The client sends `Content-Type` and a body of exactly `bytes`; the browser sets `Content-Length` from the blob. Do not return `content-length` in the presign response's client header list: it is a forbidden request header, and the browser sets it automatically to the signed value. The checksum arrives in the URL, so the client does not send a checksum header. Keep the key unique per attempt: a reusable PUT URL can overwrite the object until it expires.

## R2 and GCS

**R2** supports presigned GET, HEAD, PUT, and DELETE; browser multipart-form POST is not supported. Use a PUT, sign `Content-Type`, keep the key unique, and do the size and digest checks at finalize. Do not assume the S3 POST recipe transfers.

**GCS** enforces a size range through a signed header:

```ts
const md5Base64 = Buffer.from(md5Hex, "hex").toString("base64");
const [url] = await storage.bucket(process.env.BUCKET!).file(key).getSignedUrl({
	version: "v4",
	action: "write",
	expires: Date.now() + 10 * 60_000,
	contentType: mime,
	extensionHeaders: {
		"x-goog-content-length-range": `0,${MAX_BYTES}`,
		"content-md5": md5Base64,
	},
});
```

The browser must send both extension headers; the signature covers them, so a missing or changed header fails. `md5Base64` is the base64 MD5 of the final bytes, not the hex digest. For resumable uploads, initiate the session server-side with `x-upload-content-length` and hand the session URI to the client; the URI is a bearer token with the same rules.

## Finalize

Finalize is the commit point. The client sends only the upload id; the server reads the expected key, size, type, and digest from its own pending row. A client that could restate those values at finalize could pass its own check.

```ts
export async function finalize(userId: string, uploadId: string) {
	const row = await db.uploads.findOwned(uploadId, userId);
	if (!row) throw new Reject("NOT_FOUND");
	if (row.status === "ready") return row.public; // idempotent

	const head = await s3
		.send(
			new HeadObjectCommand({
				Bucket: process.env.BUCKET!,
				Key: row.key,
				ChecksumMode: "ENABLED",
			}),
		)
		.catch(() => {
			throw new Reject("NOT_FOUND");
		});

	if (head.ContentLength !== row.bytes) throw new Reject("SIZE_MISMATCH");
	if (head.ContentType !== row.mime) throw new Reject("TYPE_MISMATCH");
	if (head.ChecksumSHA256 !== row.checksumB64) throw new Reject("CHECKSUM");

	// Small files: fetch the bounded object and run canonicalize() here.
	// Large files: enqueue a job; publish only after it records decoded dimensions.
	await db.uploads.markReady(uploadId);
	return db.uploads.publicView(uploadId);
}
```

`HeadObject` with checksums returns the stored digest for a single-part upload. For multipart, the checksum may be a composite; compare the type S3 reports, and verify the full object in the worker that can read it. The `ContentType` comparison is meaningful only because the policy pinned it; otherwise it is another client claim.

Validation and canonicalization are different commit shapes. If finalize writes canonical bytes, it publishes a new object with a new size, type, and digest; derive every published field from the encoder output and write it under the final key, not the upload key. If finalize only verifies, it must not re-encode, and the original bytes are what gets published with the policy-pinned type. Do not mix the two: a HEAD that validates the upload followed by a silent re-encode leaves the database describing bytes that no longer exist.

Repeated finalize returns the same state. If a later upload lands on the same key, the object is no longer the one that was authorized; unique keys make that impossible, and the pending row is the authority on which key was issued to which user.

## Expiry, replay, and cleanup

- Presigned URL: 5–15 minutes. The client requests a fresh one on failure; it does not extend.
- Pending row: expires within the hour; a sweeper deletes the object and the row.
- Bucket lifecycle: abort incomplete multipart uploads after a day; expire an `uploads/` prefix that never finalized.
- URL reuse: the same presigned URL can be replayed until expiry. The key is already bound to one user, and finalize is idempotent; do not issue a URL for a key that another row owns.

## CORS

Allow the app origin exactly, the methods the flow uses, and the headers the provider needs:

```
AllowedOrigins: https://app.example.com
AllowedMethods: POST, PUT
AllowedHeaders: content-type, x-amz-checksum-algorithm, x-amz-checksum-sha256,
                x-goog-content-length-range, content-md5
ExposeHeaders: ETag, x-amz-checksum-sha256
MaxAgeSeconds: 3600
```

Send `credentials: "omit"`; presigned requests need no cookies. Expose only the headers the client reads. The finalize endpoint is authoritative even when the client never sees an ETag.

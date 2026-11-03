# Verification

A control without a failing fixture is a comment. Build the fixture set from the ways the control can fail, then assert the exact reject code, not just "not 200": a test that accepts any error cannot tell a pixel bomb from a truncated file, and will keep passing after the check that mattered is deleted.

## Fixture matrix

| Fixture | Construction | Expected |
|---|---|---|
| Valid PNG, JPEG, WebP, GIF | Real encoder output | Accepted; decoded dimensions recorded |
| Wrong magic | HTML renamed `.png` | `FORMAT` |
| Truncated | Valid file cut at 60% | `TRUNCATED` or `DECODE` |
| Header bomb | 100000×100000 IHDR, one row of pixel data | `PIXELS`, before decode |
| Edge strip | 1×100000 PNG | `PIXELS` |
| Oversized | `MAX_BYTES + 1` random bytes | `TOO_LARGE` |
| Short upload | Presign for 2 MB, upload 1 MB | `SIZE_MISMATCH` at finalize |
| SVG | `<svg onload=...>` named `.png` | `FORMAT` |
| Declared-type mismatch | Presign `image/webp`, upload PNG bytes with the same form field | `FORMAT` at decode |
| Form-type mismatch | Presign `image/webp`, send `Content-Type: image/png` | Provider signature/policy failure |
| Checksum mismatch | Presign digest A, upload bytes B | Provider `BadDigest`, or `CHECKSUM` at finalize |
| Key substitution | Upload to a key the policy did not sign | Provider 403 |
| Expired URL | Use the URL after expiry | Provider 403 |
| Polyglot | Valid GIF followed by `<script>...` | Rejected, or canonical output does not contain the marker |
| EXIF orientation | JPEG tagged orientation 6 | Canonical dimensions match the rotated view |

The declared-type row is the one that catches a common mistake: the storage policy pins the form field, not the bytes. A PNG announced as `image/webp` passes the policy and fails the decode.

## Make the malicious fixtures

```python
# fixtures/bomb.py -> fixtures/bomb.png
import struct, zlib

def chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

ihdr = struct.pack(">IIBBBBB", 100_000, 100_000, 8, 6, 0, 0, 0)
idat = zlib.compress(b"\x00" + b"\x00" * 4)  # one filter byte and one RGBA pixel
png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", ihdr)
    + chunk(b"IDAT", idat)
    + chunk(b"IEND", b"")
)
open("fixtures/bomb.png", "wb").write(png)
```

```bash
head -c 60 fixtures/valid.webp > fixtures/truncated.webp
printf '<html><script>alert(1)</script>' > fixtures/not-an-image.png
head -c 2097153 /dev/urandom > fixtures/oversized.bin
printf '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>' > fixtures/active.png
```

A real encoder gives the happy-path files (`magick` or `sharp`), including one WebP per bitstream: lossy VP8, lossless VP8L, and alpha VP8X. All three parse through different branches of the sniffer.

## Unit tests

Keep the decoder and fixture reads local; no network in this layer.

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { sniff, checkPixels } from "../src/admission";

const happy = ["png.png", "jpg.jpg", "webp-lossy.webp", "webp-lossless.webp", "webp-alpha.webp", "gif.gif"];
for (const name of happy) {
	const bytes = new Uint8Array(readFileSync(`fixtures/${name}`));
	assert.equal(sniff(bytes).ok, true, name);
}

const unsupported = sniff(new Uint8Array(readFileSync("fixtures/not-an-image.png")));
assert.equal(unsupported.ok, false);
if (!unsupported.ok) assert.equal(unsupported.reason, "unsupported");

const short = sniff(new Uint8Array(readFileSync("fixtures/png.png")).subarray(0, 20));
assert.equal(short.ok, false);
if (!short.ok) assert.equal(short.reason, "truncated");

const bomb = { ok: true as const, format: "png" as const, width: 100_000, height: 100_000 };
assert.equal(checkPixels(bomb, 40_000_000, 12_000), "pixels");
```

Keep the reject codes in one runtime array and derive the type from it:

```ts
export const REJECT_CODES = [
	"TOO_LARGE", "FORMAT", "TRUNCATED", "DECODE", "PIXELS",
	"CHECKSUM", "TYPE_MISMATCH", "SIZE_MISMATCH",
] as const;
export type RejectCode = (typeof REJECT_CODES)[number];
```

After the unit and integration suites, assert the union is exhausted:

```ts
const exercised = new Set<RejectCode>(["FORMAT", "TRUNCATED", "PIXELS"]);
// add TOO_LARGE, DECODE, CHECKSUM, TYPE_MISMATCH, and SIZE_MISMATCH
// from the cap, decode, and finalize suites
assert.deepEqual(REJECT_CODES.filter((code) => !exercised.has(code)), []);
```

Assert the code, not the HTTP status: a shared 400 satisfies `assert.notEqual(res.status, 200)` and hides which control fired.

## Presign policy test

Sign with test credentials and inspect the policy before involving a bucket. This is deterministic and catches a dropped condition.

```ts
const { fields } = await createPresignedPost(s3, options);
const policy = JSON.parse(Buffer.from(fields.Policy, "base64").toString("utf8"));

assert.ok(policy.conditions.some((c: unknown) =>
	Array.isArray(c) && c[0] === "content-length-range" && c[1] === 1 && c[2] === MAX_BYTES));
assert.ok(policy.conditions.some((c: unknown) =>
	Array.isArray(c) && c[0] === "eq" && c[1] === "$key" && c[2] === key));
assert.ok(policy.conditions.some((c: unknown) =>
	Array.isArray(c) && c[0] === "eq" && c[1] === "$x-amz-checksum-sha256" && c[2] === checksum));
```

For a PUT, parse `X-Amz-SignedHeaders` and assert it contains `content-length` and `content-type`.

## End-to-end against a bucket

Use a local S3-compatible service or a dedicated test bucket. Upload through the real policy, then repeat with one property changed.

```ts
const form = new FormData();
for (const [name, value] of Object.entries(fields)) form.append(name, value);
form.append("file", new Blob([bytes], { type: mime }), "upload.webp");

const ok = await fetch(url, { method: "POST", body: form });
assert.equal(ok.status, 204);
```

Then:

- Upload larger than the range: expect the provider to reject.
- Upload with a different form `Content-Type`: expect 403.
- Upload valid bytes under the wrong claimed type: expect 204, then `FORMAT` at decode.
- Upload bytes whose digest differs: expect `BadDigest`.
- Finalize twice: second call returns the ready state, no duplicate row.

Store the presign `fields` object in the test artifact, not the signed URL; it is a bearer capability until expiry. The decoded policy is the fastest way to see which condition fired.

## Publish headers

```bash
curl -sI "$MEDIA_URL" | grep -Ei \
  '^(content-type|x-content-type-options|content-disposition|cache-control|accept-ranges):'
```

Assert the type is the server's mapped value, `nosniff` is present, PDF/SVG are `attachment`, and the origin sets no cookie. Request the file through a direct navigation, not only through an `<img>`, and confirm the disposition holds.

Finally, run one request above the proxy cap and one above the application cap. Both must be rejected before the decoder runs; a log line from `canonicalize` during either test means the outermost cap is not effective.

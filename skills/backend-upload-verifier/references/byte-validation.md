# Byte validation

Header checks reject cheaply; the decode admits. A magic prefix is a router, not a verdict: it tells you which parser to trust with the bytes, and nothing about whether those bytes are safe, complete, or the only content in the file.

## Admission order

1. **Cap the body.** Count bytes as they arrive; stop at `MAX_BYTES + 1` and reject `TOO_LARGE`. The cap is the number the proxy, framework, and storage policy agree on. Done when no reader can hand the parser more than that.
2. **Sniff a prefix.** Read enough bytes to identify the container (12 for the common raster formats; up to 1 MiB for a JPEG whose first SOF follows a large EXIF block). Reject unknown formats with `FORMAT`. Done when every accepted format has an explicit branch.
3. **Read header dimensions.** Parse width and height without decoding pixels. Reject non-positive values, an edge over `MAX_EDGE`, a pixel product over `MAX_PIXELS`, or an aspect ratio over 20:1 with `PIXELS`. Done when the check runs before any decoder allocates.
4. **Decode fully.** Use a maintained decoder with an independent pixel limit and error-on-truncation setting. Failure is `TRUNCATED` or `DECODE`. Done when the output is a complete frame, at the dimensions you checked.
5. **Canonicalize.** Re-encode to the format you will serve, apply EXIF orientation, drop metadata and trailing bytes, and use the decoded dimensions. Done when the stored bytes differ from the uploaded bytes and the output has no payload beyond what the encoder wrote.
6. **Record.** Persist the decoded width, height, format, byte length, and digest. Done when every published field comes from step 5, not from the upload request.

## Prefix table

| Format | Prefix test | Dimensions without a full decode | Bound |
|---|---|---|---|
| PNG | `89 50 4E 47 0D 0A 1A 0A` | IHDR at offset 12; width/height are big-endian `uint32` at 16 and 20 | 24 bytes |
| JPEG | `FF D8 FF` | walk markers to the first SOF (`C0`–`C3`, `C5`–`C7`, `C9`–`CB`, `CD`–`CF`); height at `+5`, width at `+7` of the segment | 1 MiB (EXIF can precede SOF) |
| GIF | `GIF87a` or `GIF89a` | logical screen width/height, little-endian `uint16` at 6 and 8 | 10 bytes |
| WebP | `RIFF` at 0 and `WEBP` at 8 | `VP8X` canvas at payload `+4`/`+7`; `VP8 ` at `+6`/`+8`; `VP8L` packed at `+1` | 30 bytes |
| AVIF/HEIC | `ftyp` at 4, brand at 8 (`avif`, `avis`, `heic`, `mif1`) | `ispe` box inside `meta`; needs a box walk | full box header |
| PDF | `%PDF-` at 0 | none (not an image); separate allowlist and attachment disposition | 5 bytes |
| ZIP/OOXML | `PK 03 04` | none; treat as an archive bomb surface | 4 bytes |

AVIF and HEIC are decode-support decisions before they are validation decisions. If the server's decoder cannot decode the format, the allowlist does not include it. The sniffer below implements the four raster formats; the remaining rows are explicit rejections, or parsers you add with the same admission order.

## Sniffer

Read a bounded prefix and classify it. Return `truncated` separately from `invalid` so the caller can read more or reject for the right reason.

```ts
export type Format = "png" | "jpeg" | "webp" | "gif";

export type Sniff =
	| { ok: true; format: Format; width: number; height: number }
	| { ok: false; reason: "unsupported" | "truncated" | "invalid" };

const ascii = (b: Uint8Array, at: number, text: string) =>
	text.split("").every((ch, i) => b[at + i] === ch.charCodeAt(0));

const be16 = (b: Uint8Array, at: number) => (b[at] << 8) | b[at + 1];
const be32 = (b: Uint8Array, at: number) =>
	((b[at] << 24) | (b[at + 1] << 16) | (b[at + 2] << 8) | b[at + 3]) >>> 0;
const le16 = (b: Uint8Array, at: number) => b[at] | (b[at + 1] << 8);
const le24 = (b: Uint8Array, at: number) => b[at] | (b[at + 1] << 8) | (b[at + 2] << 16);

// SOF0-3, SOF5-7, SOF9-11, SOF13-15 carry frame dimensions.
const SOF = new Set([
	0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
	0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf,
]);

function png(b: Uint8Array): Sniff {
	if (b.length < 24) return { ok: false, reason: "truncated" };
	if (!ascii(b, 12, "IHDR")) return { ok: false, reason: "invalid" };
	const width = be32(b, 16);
	const height = be32(b, 20);
	return width && height
		? { ok: true, format: "png", width, height }
		: { ok: false, reason: "invalid" };
}

function gif(b: Uint8Array): Sniff {
	if (b.length < 10) return { ok: false, reason: "truncated" };
	const width = le16(b, 6);
	const height = le16(b, 8);
	return width && height
		? { ok: true, format: "gif", width, height }
		: { ok: false, reason: "invalid" };
}

function jpeg(b: Uint8Array): Sniff {
	let i = 2;
	while (i + 4 <= b.length) {
		if (b[i] !== 0xff) return { ok: false, reason: "invalid" };
		const marker = b[i + 1];
		if (marker === 0xff) {
			i += 1; // fill byte
			continue;
		}
		if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
			i += 2;
			continue;
		}
		if (marker === 0xd9 || marker === 0xda) return { ok: false, reason: "invalid" };
		const length = be16(b, i + 2);
		if (length < 2) return { ok: false, reason: "invalid" };
		if (SOF.has(marker)) {
			if (i + 9 > b.length) return { ok: false, reason: "truncated" };
			const height = be16(b, i + 5);
			const width = be16(b, i + 7);
			return width && height
				? { ok: true, format: "jpeg", width, height }
				: { ok: false, reason: "invalid" };
		}
		i += 2 + length;
	}
	return { ok: false, reason: "truncated" };
}

function webp(b: Uint8Array): Sniff {
	if (b.length < 20) return { ok: false, reason: "truncated" };
	let off = 12;
	while (off + 8 <= b.length) {
		const fourcc = String.fromCharCode(...b.subarray(off, off + 4));
		const size =
			(b[off + 4] | (b[off + 5] << 8) | (b[off + 6] << 16) | (b[off + 7] << 24)) >>> 0;
		const data = off + 8;
		if (data + size > b.length) return { ok: false, reason: "truncated" };
		if (fourcc === "VP8X" && size >= 10) {
			return {
				ok: true,
				format: "webp",
				width: le24(b, data + 4) + 1,
				height: le24(b, data + 7) + 1,
			};
		}
		if (fourcc === "VP8 " && size >= 10) {
			if (b[data + 3] !== 0x9d || b[data + 4] !== 0x01 || b[data + 5] !== 0x2a) {
				return { ok: false, reason: "invalid" };
			}
			return {
				ok: true,
				format: "webp",
				width: le16(b, data + 6) & 0x3fff,
				height: le16(b, data + 8) & 0x3fff,
			};
		}
		if (fourcc === "VP8L" && size >= 5) {
			if (b[data] !== 0x2f) return { ok: false, reason: "invalid" };
			const bits =
				b[data + 1] | (b[data + 2] << 8) | (b[data + 3] << 16) | (b[data + 4] << 24);
			return {
				ok: true,
				format: "webp",
				width: (bits & 0x3fff) + 1,
				height: ((bits >>> 14) & 0x3fff) + 1,
			};
		}
		off = data + size + (size & 1);
	}
	return { ok: false, reason: "truncated" };
}

export function sniff(b: Uint8Array): Sniff {
	if (b.length < 12) return { ok: false, reason: "truncated" };
	if (b[0] === 0x89 && ascii(b, 1, "PNG\r\n\x1a\n")) return png(b);
	if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return jpeg(b);
	if (ascii(b, 0, "GIF87a") || ascii(b, 0, "GIF89a")) return gif(b);
	if (ascii(b, 0, "RIFF") && ascii(b, 8, "WEBP")) return webp(b);
	return { ok: false, reason: "unsupported" };
}
```

Reject the dimensions in a separate step so the same function serves both the prefix check and the decoded check:

```ts
export function checkPixels(size: { width: number; height: number }, maxPixels: number, maxEdge: number) {
	const pixels = size.width * size.height;
	if (size.width <= 0 || size.height <= 0 || !Number.isSafeInteger(pixels)) return "invalid";
	if (size.width > maxEdge || size.height > maxEdge || pixels > maxPixels) return "pixels";
	const ratio = Math.max(size.width, size.height) / Math.min(size.width, size.height);
	return ratio > 20 ? "pixels" : null;
}
```

`width * height` can exceed `Number.MAX_SAFE_INTEGER` for 32-bit inputs, which `isSafeInteger` catches before a comparison silently rounds. The edge cap is what stops a 1×100000 strip from passing the pixel product.

## Decode and canonicalize

`sharp` (libvips) is the maintained decoder for the common server stack. Header metadata is a cheap first pass; the transform is the admission gate.

```ts
import sharp from "sharp";

const ALLOWED = new Set(["png", "jpeg", "webp", "gif"]);
const PREFIX_BYTES = 1 << 20;

export async function canonicalize(
	body: Buffer,
	limits: { maxPixels: number; maxEdge: number; maxBytes: number },
) {
	if (body.byteLength > limits.maxBytes) throw new Reject("TOO_LARGE");

	// Header first: reject a bomb before the decoder opens the file. The
	// decoder's own limit is the backstop for a header that disagrees.
	const header = sniff(body.subarray(0, PREFIX_BYTES));
	if (!header.ok) throw new Reject(header.reason === "unsupported" ? "FORMAT" : "TRUNCATED");
	const headerPixels = checkPixels(header, limits.maxPixels, limits.maxEdge);
	if (headerPixels === "invalid") throw new Reject("FORMAT");
	if (headerPixels) throw new Reject("PIXELS");

	const image = sharp(body, {
		failOn: "truncated",
		limitInputPixels: limits.maxPixels,
		sequentialRead: true,
	});
	const meta = await image.metadata().catch(() => {
		throw new Reject("DECODE");
	});

	if (!meta.format || !ALLOWED.has(meta.format)) throw new Reject("FORMAT");
	if (!meta.width || !meta.height) throw new Reject("DECODE");
	if (meta.pages && meta.pages > 1) throw new Reject("FORMAT"); // animated input
	const metaPixels = checkPixels(
		{ width: meta.width, height: meta.height },
		limits.maxPixels,
		limits.maxEdge,
	);
	if (metaPixels === "invalid") throw new Reject("DECODE");
	if (metaPixels) throw new Reject("PIXELS");

	const { data, info } = await image
		.rotate() // apply EXIF orientation, then drop it
		.resize({ width: limits.maxEdge, height: limits.maxEdge, fit: "inside", withoutEnlargement: true })
		.webp({ quality: 82 })
		.toBuffer({ resolveWithObject: true })
		.catch(() => {
			throw new Reject("DECODE");
		});

	if (checkPixels(info, limits.maxPixels, limits.maxEdge)) throw new Reject("PIXELS");
	return { bytes: data, width: info.width, height: info.height, format: "webp" as const };
}
```

`metadata()` reads the header; `toBuffer()` decodes the pixels. `limitInputPixels` must be set on the same pipeline, because the header dimensions can disagree with what the decoder allocates. The re-encode is also the polyglot defense: appended or embedded payloads the decoder did not consume do not survive it.

The output codec is a product decision. Swap `.webp()` for `.png()` when the image is a flat graphic whose lossy artifacts would show; keep WebP for photos.

## Runtime limits

| Runtime | Header-only | Full decode | Guard |
|---|---|---|---|
| Node `sharp` | `metadata()` | `toBuffer()` | `limitInputPixels`, `failOn: "truncated"`, `sequentialRead` |
| Node `file-type` | magic only | none | never an admission check; no dimensions |
| Node `image-size` | header only | none | cheap reject; decoder still decides |
| Go | `image.DecodeConfig` | `image.Decode` | `http.MaxBytesReader`, blank imports for formats, `x/image/webp` |
| Python Pillow | `Image.open` (lazy) | `load()` / `verify()` | `Image.MAX_IMAGE_PIXELS`, `DecompressionBombError`, `ImageOps.exif_transpose` |
| ImageMagick | `identify` | `convert` | `-limit` resource caps; run sandboxed, never on the request thread |

Go's config/decode split needs a rewindable source: `DecodeConfig` consumes the prefix, so a one-shot network stream must first be buffered to a bounded file or memory. If the whole file is under the cap, buffer it; that is cheaper than a second protocol.

## What a header cannot prove

- **Polyglots and trailing data.** A valid image can also parse as HTML or carry a second payload. Header checks pass by design. Full decode plus re-encode removes what the decoder ignores; `nosniff` and a separate origin contain what remains.
- **Declared versus decoded dimensions.** Each container's header is a claim the decoder re-reads. Check both, and use the decoded dimensions.
- **EXIF orientation.** Orientations 5–8 swap width and height. Parse orientation before an aspect-ratio decision, or compare after `rotate()`.
- **Embedded images.** EXIF thumbnails and ICC/color profiles are additional payloads. Re-encoding drops them; anything you preserve is content you must validate separately.
- **Animation.** `meta.pages > 1` is a frame budget, a decode budget, and often a product decision. Reject or cap it explicitly.
- **Metadata you serve.** GPS, author, and device fields leak. Strip them unless the product promises to keep them.

## SVG

SVG is an XML document, not a raster image: scripts, external entities, CSS, and remote references are all in scope. Reject it from untrusted uploads. If the product requires SVG, sanitize with an allowlist sanitizer (DOMPurify), serve it as `image/svg+xml` from the media origin with `Content-Security-Policy: default-src 'none'; sandbox`, and never render it inline in the app origin. Rasterizing with librsvg is another parser with its own history; it is not a sanitizer.

## Streaming versus buffering

An image decoder needs the compressed bytes, so a "zero-buffer" image pipeline is a fiction: the prefix rejects early, and the cap bounds the buffer that the decoder reads. The honest choice is a small proxied cap (a few MB, buffer in memory) or the direct-to-storage path (no server buffer, verify after). For a raw request that must be rejected before multipart parsing, read a bounded prefix and close the connection; do not drain a body you have already refused.

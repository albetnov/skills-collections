# Image pipeline

Decode, orient, resize, and encode are one pass. Hashing is the last step, over the exact bytes that leave the browser.

## Shape

```ts
const size = await sourceSize(file);        // optional preflight, header only
const bitmap = await decode(file);          // full decode, orientation applied
const target = fit(bitmap, maxEdge);        // pixels, not file bytes
const canvas = new OffscreenCanvas(...);    // target-size surface
const blob = await encode(canvas, type);    // final bytes
const digest = await sha256(blob);          // after the last transform
```

Run the whole function in a worker; the main thread receives `{ blob, width, height, type, sha256 }`.

## Preflight

The file-size cap is the first bound. A header read gives dimensions without decoding pixels; PNG and JPEG cover camera output and screenshots.

```ts
async function sourceSize(file: Blob) {
	const b = new Uint8Array(await file.slice(0, 256 * 1024).arrayBuffer());
	if (b.length >= 24 && b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) {
		const view = new DataView(b.buffer, b.byteOffset, b.byteLength);
		return { width: view.getUint32(16), height: view.getUint32(20) };
	}
	if (b[0] === 0xff && b[1] === 0xd8) {
		for (let i = 2; i + 9 < b.length; ) {
			if (b[i] !== 0xff) return null;
			const marker = b[i + 1];
			const length = (b[i + 2] << 8) | b[i + 3];
			if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
				return {
					width: (b[i + 7] << 8) | b[i + 8],
					height: (b[i + 5] << 8) | b[i + 6],
				};
			}
			i += 2 + length;
		}
	}
	return null;
}
```

A `null` means "unknown, proceed to decode". This is a UX guard, not admission: the server still checks the decoded dimensions. The full format table lives in the `backend-upload-verifier` skill; do not grow this into a second validator.

Cap the source at 24 MP on desktop and 12 MP on a low-memory device; above that, ask the user to pick a smaller image or let the server do it.

## Decode and orientation

```ts
async function decode(file: Blob): Promise<ImageBitmap> {
	if (typeof createImageBitmap === "function") {
		try {
			return await createImageBitmap(file, { imageOrientation: "from-image" });
		} catch {
			// fall through to the <img> path
		}
	}
	const url = URL.createObjectURL(file);
	try {
		const img = new Image();
		img.src = url;
		await img.decode();
		return await createImageBitmap(img);
	} finally {
		URL.revokeObjectURL(url);
	}
}
```

`imageOrientation: "from-image"` makes the bitmap dimensions match the displayed image; orientations 5–8 swap width and height. Drawing an `<img>` respects its default `image-orientation: from-image`, which is why the fallback still works. If `createImageBitmap` is missing entirely, draw the `<img>` into the canvas directly; the helper above assumes the API exists for its fallback path. Verify orientation with a fixture, not by assumption: some WebKit versions have ignored the option.

## Resize and encode

```ts
async function processImage(
	file: File,
	options: { maxEdge: number; maxPixels: number; maxBytes: number; type: "image/webp" | "image/jpeg" },
) {
	if (file.size > options.maxBytes) throw new Error("TOO_LARGE");
	if (!crypto.subtle) throw new Error("NO_SUBTLE");
	const size = await sourceSize(file);
	if (size && size.width * size.height > options.maxPixels) throw new Error("PIXELS");

	const bitmap = await decode(file);
	try {
		const scale = Math.min(1, options.maxEdge / Math.max(bitmap.width, bitmap.height));
		const width = Math.max(1, Math.round(bitmap.width * scale));
		const height = Math.max(1, Math.round(bitmap.height * scale));

		const canvas = new OffscreenCanvas(width, height);
		const ctx = canvas.getContext("2d");
		if (!ctx) throw new Error("NO_CONTEXT");
		ctx.imageSmoothingEnabled = true;
		ctx.imageSmoothingQuality = "high";
		ctx.drawImage(bitmap, 0, 0, width, height);

		const preferred = await canvas.convertToBlob({ type: options.type, quality: 0.82 });
		const blob =
			preferred.type === options.type
				? preferred
				: await canvas.convertToBlob({ type: "image/jpeg", quality: 0.85 });

		canvas.width = 0;
		canvas.height = 0;

		const bytes = new Uint8Array(await blob.arrayBuffer());
		const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
		const sha256 = [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
		return {
			blob,
			bytes,
			width,
			height,
			type: blob.type,
			sha256,
		};
	} finally {
		bitmap.close();
	}
}
```

`convertToBlob` silently falls back to PNG when the requested type is unsupported; `blob.type` is the only reliable answer. Chromium returns `image/png` for a request of `image/avif`, so checking the string is mandatory. JPEG is the universal fallback; WebP encoding is widely available but should still be probed (`capability-matrix.md`).

For a downscale below half the source dimension, halve once or twice with `drawImage` before the final draw. A single large-ratio draw is cheaper but aliases; the extra canvases cost memory, so do it only when quality matters.

## Memory

| Source | Decoded RGBA | Target canvas | Peak in the worker |
|---|---|---|---|
| 12 MP | 48 MB | 5 MB at 1280 px | ~55 MB |
| 24 MP | 96 MB | 10 MB at 1920 px | ~110 MB |
| 48 MP | 192 MB | 10 MB | ~205 MB |

The decoded bitmap is the dominant cost, and it is allocated before your resize runs. That is why the source pixel cap is a preflight, not a post-decode cleanup. A canvas itself is capped: iOS 17 and earlier allow a 4096×4096 canvas (16.7 Mpx); iOS 18+ allows 8192×8192 (67.1 Mpx). Keep target dimensions inside the cap; tile larger output.

## Format choice

- **Photos:** WebP at quality 0.8, or JPEG at 0.85 for maximum compatibility.
- **Flat graphics with alpha:** PNG if the browser's WebP encoder is lossy-only; WebP lossless is not reachable through `convertToBlob` in Chromium.
- **AVIF:** canvas encoding is not portable; Chromium silently returns PNG. Probe `blob.type` (see [capability-matrix](capability-matrix.md)); when it falls back, use a Wasm encoder (`@jsquash/avif`, `wasm-vips`) from `ImageData` or the original bytes, accept the CPU cost, and keep JPEG/WebP as the fallback. Do not label a PNG as AVIF.
- **GIF:** do not re-encode animation through a canvas; frames are lost. Handle it server-side or reject it.

## Video

`WebCodecs` (`VideoEncoder`, `VideoFrame`) works in a worker and gives codec-level control; `isConfigSupported` is the capability probe because codec support varies by device. `MediaRecorder` is a capture shortcut, not a transcode pipeline. `HTMLVideoElement` is main-thread-only, so worker frame extraction uses `VideoFrame` from `WebCodecs`, not `drawImage(video)`. For anything longer than a short clip, upload the original and transcode on the server; a 2 GB Wasm heap is not a video pipeline.

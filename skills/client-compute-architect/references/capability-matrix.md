# Capability matrix

Decode support, encode support, and thread support are three different questions. Browsers that display AVIF do not necessarily encode it; browsers with `OffscreenCanvas` do not necessarily have WebGL in a worker. Probe the operation you are about to run, in the context that will run it.

## Detection

```ts
export const capabilities = {
	offscreen2d: () =>
		typeof OffscreenCanvas === "function" &&
		typeof OffscreenCanvas.prototype.convertToBlob === "function",
	bitmap: () => typeof createImageBitmap === "function",
	webcodecs: () => typeof VideoEncoder === "function" && typeof VideoFrame === "function",
	crossOriginIsolated: () => globalThis.crossOriginIsolated === true,
	savePicker: () => "showSaveFilePicker" in globalThis,
	backgroundSync: () => "serviceWorker" in navigator && "SyncManager" in globalThis,
	persistentStorage: () => typeof navigator.storage?.persist === "function",
};

export async function encodes(type: string): Promise<boolean> {
	try {
		const canvas = new OffscreenCanvas(1, 1);
		return (await canvas.convertToBlob({ type })).type === type;
	} catch {
		return false;
	}
}
```

In a worker, `document` does not exist; that is the context where the operation will run, so probe there. On the main thread, the `document.createElement("canvas").toBlob` variant probes the same encoders.

## Matrix

| Capability | Support | Fallback |
|---|---|---|
| `OffscreenCanvas` 2D | Chrome 69+, Firefox 105+, Safari 16.4+ | Main-thread canvas |
| `OffscreenCanvas` WebGL | Safari 17+; Chromium and Firefox earlier | 2D path, or main-thread WebGL |
| `createImageBitmap` | Chrome 50+, Firefox 42+, Safari 15+ | `<img>` + `drawImage` |
| WebP decode | Chrome, Firefox, Safari 14+ (macOS 11+ for 14–15.6) | JPEG/PNG |
| WebP encode | Chromium and Firefox; WebKit versions vary and some return PNG | Probe `blob.type`; JPEG |
| AVIF decode | Chrome 85+, Firefox 93+, Safari 16.4+ (macOS 13+) | JPEG/WebP |
| AVIF encode via canvas | Chromium returns PNG; some WebKit 26.5+ builds return AVIF; not portable | Probe `blob.type`; Wasm encoder or server |
| `WebCodecs` | Chromium 94+, Firefox 130+, Safari 16.4+ video-only, per-codec gaps | `MediaRecorder`, or server transcode |
| `SharedArrayBuffer` / Wasm threads | Needs `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp` | Single-thread Wasm |
| `crypto.subtle.digest` | Secure contexts; all modern browsers and workers | Server-side hash |
| `navigator.deviceMemory` | Chromium only, capped at 8 | Assume a low-end device |
| `showSaveFilePicker` | Chromium only | Blob download |
| Background Sync | Chromium only | Retry on `online` and visibility |
| `StorageManager.persist()` | Modern browsers; grant is best-effort | Warn about eviction |

`toBlob` / `convertToBlob` fall back to PNG when the requested type is unsupported, silently. The returned `blob.type` is the only reliable answer; a filename extension is not.

## Canvas limits

| Platform | Maximum canvas area |
|---|---|
| iOS 17 and earlier | 4096×4096 (16,777,216 px) |
| iOS 18+ | 8192×8192 (67,108,864 px) |
| Desktop Chromium | Much larger, but memory-bound; keep a budget |

The cap is on the canvas, not on the source bitmap. A 48 MP source can be decoded and drawn into a 4096×4096 target; the decoded bitmap is the memory risk, not the target. Keep one canvas at target size, and tile only when the target itself exceeds the cap.

## Codec probes

```ts
const config = { codec: "vp09.00.10.08", width: 1280, height: 720, bitrate: 2_000_000 };
const { supported } = await VideoEncoder.isConfigSupported(config);
```

`isConfigSupported` is necessary but not sufficient: a device may advertise a codec and fail on a specific resolution or hardware path. Encode one short frame before starting a long job.

`createImageBitmap` resize options are not universal; feature-detect them by the resulting dimensions:

```ts
const probe = await createImageBitmap(blob, { resizeWidth: 16, resizeHeight: 16 });
const resizes = probe.width === 16 && probe.height === 16;
probe.close();
```

If `resizes` is false, decode at source dimensions and draw into a target canvas instead. The fallback allocates the full bitmap, so pair it with the source pixel cap.

## Deployment knobs

- Wasm threads and `SharedArrayBuffer` require cross-origin isolation headers on every response that loads the worker, including the document. COOP/COEP also breaks third-party embeds that do not send CORP/CORS headers; plan for that before turning it on.
- `crypto.subtle` is unavailable on plain HTTP origins other than localhost. A development server on a LAN IP is not a secure context.
- Service workers and Background Sync need a secure origin; the queue can exist without them, it just retries less opportunistically.
- iOS may evict IndexedDB and blob storage under pressure; `persist()` is a request, not a guarantee.

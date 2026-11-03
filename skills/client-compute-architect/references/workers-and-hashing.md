# Workers and hashing

A worker is not a performance decoration: it is the only way a 48 MB decode does not become a 300 ms main-thread stall. Moving work into one costs a message protocol, a queue, and a cancellation story.

## Topology

- One worker per pipeline family (image, document, hash), or one pool of `min(4, hardwareConcurrency - 1)` workers for the same family.
- One job per worker at a time. A second job waits; it does not interleave inside the codec.
- Bounded queue: two jobs per worker. Beyond that, reject with a visible "busy" state; an unbounded queue of 100 photos is an out-of-memory bug with a progress bar.
- The main thread keeps input, painting, and abort; everything else is a message.

`ImageBitmap`, `OffscreenCanvas`, `ArrayBuffer`, and `MessagePort` are transferable. Transferring moves the buffer; structured cloning copies it. A `Blob` is immutable and cheap to hand over, but not transferable. Never `postMessage` a large `Uint8Array` without listing its buffer in the transfer list.

## Protocol

```ts
// image.worker.ts
/// <reference lib="webworker" />
import { processImage } from "./image-pipeline";

type JobBody = {
	kind: "image";
	file: File;
	maxEdge: number;
	maxPixels: number;
	maxBytes: number;
	type: "image/webp" | "image/jpeg";
};
type Job = JobBody & { id: number };

type Result =
	| { id: number; ok: true; value: { blob: Blob; width: number; height: number; type: string; sha256: string } }
	| { id: number; ok: false; error: string };

self.onmessage = async (event: MessageEvent<Job>) => {
	const job = event.data;
	try {
		const { blob, width, height, type, sha256 } = await processImage(job.file, {
			maxEdge: job.maxEdge,
			maxPixels: job.maxPixels,
			maxBytes: job.maxBytes,
			type: job.type,
		});
		self.postMessage({ id: job.id, ok: true, value: { blob, width, height, type, sha256 } } satisfies Result);
	} catch (error) {
		self.postMessage({ id: job.id, ok: false, error: String(error) } satisfies Result);
	}
};
```

```ts
// client.ts
const worker = new Worker(new URL("./image.worker.ts", import.meta.url), { type: "module" });
let nextId = 0;
const pending = new Map<number, (result: Result) => void>();

worker.onmessage = ({ data }: MessageEvent<Result>) => {
	pending.get(data.id)?.(data);
	pending.delete(data.id);
};

worker.onerror = () => {
	for (const resolve of pending.values()) resolve({ id: -1, ok: false, error: "worker crashed" });
	pending.clear();
};

function run(job: JobBody) {
	const id = nextId++;
	return new Promise<Result>((resolve) => {
		pending.set(id, resolve);
		worker.postMessage({ ...job, id });
	});
}
```

Send stage updates as `{ id, stage: "decode" | "encode" | "hash", progress }`; the main thread maps them to one progress bar. A progress number derived from elapsed time is a lie; use byte or stage counts.

## Cancellation

- Network: `xhr.abort()` or `AbortController` with `fetch`.
- CPU: check a generation token between stages; for one long codec call, `worker.terminate()` and create a replacement. Termination is the only way to interrupt a synchronous decode or encode, and it drops the worker's queue.
- Memory: `bitmap.close()`, `canvas.width = 0`, `URL.revokeObjectURL(url)`, and drop references to the source `File`.

After `terminate()`, reject every pending promise and clear the map. A resolved-but-ignored job is a leak.

## Hashing

Hash once, after the final encode. Two hashes of the same file at different stages are two chances to disagree.

```ts
async function sha256(blob: Blob): Promise<{ base64: string; hex: string }> {
	const buffer = await blob.arrayBuffer();
	const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
	const base64 = btoa(String.fromCharCode(...digest));
	const hex = [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
	return { base64, hex };
}
```

`crypto.subtle` needs a secure context (HTTPS or localhost) and is available in workers. The one-shot API needs the whole file in an `ArrayBuffer`, so peak memory is the blob plus a copy. Above roughly 100 MB, use a streaming Wasm hasher and feed it `blob.slice(offset, offset + chunk)` in 4 MB chunks; the server side expects the same algorithm, not the same tool.

Encoding matters: the upload contract names one representation, and the provider boundary converts if it needs another. Returning both base64 and hex from the hash function is cheap and avoids a second pass over the blob.

## Scheduling

- Prioritize the visible edit over background uploads; a queue of uploads must not delay the preview.
- Pause background work when `document.visibilityState === "hidden"` if the job is optional; browsers throttle timers anyway.
- Wasm builds are release artifacts: serve each binary from a content-hashed URL with `Cache-Control: public, max-age=31536000, immutable`, and keep the compiled module alive in the worker. A 5–30 MB module should download and compile once per release, not once per job.
- Size the pool from `navigator.hardwareConcurrency`, capped at 4. `navigator.deviceMemory` (Chromium) is a coarse hint, capped at 8.
- Do not spawn a worker per file. Worker startup and Wasm instantiation are real costs.

## Testing

- Run the pure pipeline against real fixtures in the test runner: assert `blob.type`, decoded dimensions, and digest.
- Use a browser test for codecs: a Node canvas shim proves nothing about Safari's encoder.
- Force the fallback path with a flag (for example `?no-offscreen`), then run the same assertions. A fallback that has never executed is a comment.
- Record a performance trace of a 24 MP image on a throttled CPU; assert no long task over 50 ms on the main thread and that the worker handled decode/encode/hash.

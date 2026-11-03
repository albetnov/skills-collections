---
name: client-compute-architect
description: "Browser-native processing and upload pipelines. Use when offloading image or video work to Canvas, Wasm, or Web Workers, generating PDF/CSV/spreadsheet exports in the browser, or building a direct-to-storage upload path with hashing, progress, retry, and offline queues."
---

# Client compute architect

Client compute buys latency, bandwidth, and server cost; it does not buy trust. The pipeline produces bytes plus claims, and the server verifies both. Server-side admission belongs to the `backend-upload-verifier` skill.

## Choose the mechanism

| Workload | Mechanism | Constraint |
|---|---|---|
| Decode, resize, re-encode still images | `createImageBitmap` + `OffscreenCanvas` in a worker | Canvas encodes PNG and JPEG everywhere; WebP and AVIF are probe-and-fallback |
| Codec not in Canvas: AVIF encode, HEIC, heavy filters | Wasm (`@jsquash/avif`, `wasm-vips`, `ffmpeg.wasm`) | 5–30 MB payload, CPU-bound, threads need cross-origin isolation; cache a content-hashed module immutably |
| PDF | `pdf-lib` for composition, `pdfmake` for declarative tables | Large documents belong on the server |
| CSV and spreadsheets | Manual CSV writer, `exceljs`, `write-excel-file` | Workbooks build in memory; huge exports are CSV streams |
| Video | `WebCodecs` in a worker; `MediaRecorder` for a quick capture | Codec support and hardware vary; server transcode is the fallback |
| Large local filtering and sorting | Worker over typed arrays, or IndexedDB indexes | Keep the dataset off the main thread; query the server when the set is large |
| Upload | Presigned direct-to-storage; multipart or resumable for large files | The app server is not a media proxy |
| Offline queue | IndexedDB plus `StorageManager` | Quota is not guaranteed; presigned URLs expire |

## Pipeline invariants

1. The output is a suggestion. The digest and metadata describe the exact bytes that are uploaded; the final encode defines them, and the server or storage recomputes them.
2. Heavy work leaves the main thread. Decode, encode, hash, parse, PDF, and spreadsheet generation run in a worker; the main thread receives messages and paints. No task over 50 ms.
3. Memory is budgeted in decoded pixels, not file bytes. A 12 MP image is 48 MB decoded; cap the source, size the target, and close bitmaps, canvases, and object URLs when done.
4. Capability is detected before use, and every probe has a working fallback. A requested encode type is a request: check `blob.type` and fall back instead of shipping a PNG named `.avif`.
5. Orientation and color are deliberate. Apply EXIF orientation; canvas output is sRGB unless `colorSpace` says otherwise; re-encoding drops ICC profiles and metadata.
6. Hash after the final encode. Re-encoding after hashing produces a digest that no longer matches the uploaded bytes.
7. Cancel means free. `AbortController` stops network, worker termination stops CPU, `bitmap.close()`, zeroed canvases, and revoked URLs release memory.
8. Progress is measured, not implied. Upload progress comes from XHR; retries reuse a stable key and the same digest; large uploads resume instead of restarting.
9. Build the low-end path first. The fallback path runs on the slowest supported device with the largest fixture, not on desktop Chrome.

## Reference router

| Read when | File |
|---|---|
| Decoding, orienting, resizing, encoding, image memory, AVIF/Wasm | [image-pipeline](references/image-pipeline.md) |
| Worker topology, transferables, scheduling, cancellation, hashing | [workers-and-hashing](references/workers-and-hashing.md) |
| PDF, CSV, spreadsheet generation, large exports, saving files | [documents-and-exports](references/documents-and-exports.md) |
| Presign handoff, upload transport, progress, retry, resumable, offline | [upload-handoff](references/upload-handoff.md) |
| Feature detection and browser gaps | [capability-matrix](references/capability-matrix.md) |

## Before returning a pipeline

- Every step names its thread, its input cap, and its fallback.
- Every capability probe has a fallback that was exercised on Safari and iOS.
- The metadata sent to the server is computed from the bytes that are uploaded, after the last transform.
- Peak memory is the sum of source decode, target canvas, and output blob at the largest fixture; it fits the low-end device budget.
- No main-thread task exceeds 50 ms in the profile; decode, encode, hash, and export appear on the worker.
- Cancel and failure release buffers and stop the request.
- Retry and offline paths are idempotent and survive a reload.
- The presign request carries the final size and digest; the server pins what the provider supports and verifies the rest at finalize.

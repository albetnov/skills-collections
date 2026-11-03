---
name: backend-upload-verifier
description: "Server-side admission of client-processed uploads. Use when designing or reviewing a file upload API: magic-byte and container checks, image dimension and pixel limits, presigned S3/R2/GCS policies, checksum verification, streaming caps, or serving user files safely."
---

# Backend upload verifier

The browser side is a cost optimization, not an authority. A file is admitted by a check this server performs, or one the storage provider enforces on this server's configuration. Everything the client says about the file — type, dimensions, digest, "already processed" — is input to a check, never the check.

Scope: uploads whose bytes were produced in the browser. The producing pipeline is the `client-compute-architect` skill.

## Admission paths

| Path | What admits the file | Use for |
|---|---|---|
| Direct to object storage | Provider policy pins what it can (key, type, size range, checksum); finalize verifies the stored object | Large media, high volume |
| Through the API | Bounded buffer, header check, full decode, then write | Small files, strict inspection, no storage credentials in the browser |
| Direct, async inspect | Provider policy at upload; a queue decodes before publish | Best throughput, delayed publish |

No path makes the client the last check. A proxied upload is for files small enough to buffer (a few MB); media large enough to threaten memory is exactly the media that belongs on the direct path.

## Admission invariants

1. Format comes from bytes. A magic prefix selects a parser; it does not admit the file. `Content-Type`, extension, and client metadata only choose which parser runs.
2. The byte cap is counted while reading and is the minimum of the caps the proxy, framework, and provider actually set. `Content-Length` is a hint, not the cap.
3. Dimensions are checked from the header before decode and from the decoded image after. A decoder-level pixel limit backs both; a header can lie.
4. A file is admitted only after a full decode by a maintained decoder. When the stored bytes are served unchanged, that decode happens at admission; when you can, re-encode to canonical bytes and drop everything the decoder did not consume.
5. The upload authorization is server-derived: key and exact content type, plus size and digest where the provider supports them. The pending row carries the rest, and the client never names the destination.
6. Completion re-reads the stored object and compares size, type, and digest with the authorization. Only then does the object become publishable.
7. A digest proves integrity only when storage or this server computes it over the stored bytes. A client-supplied digest is a dedupe hint until one of them recomputes it.
8. Rejections carry distinct codes (`TOO_LARGE`, `FORMAT`, `TRUNCATED`, `DECODE`, `PIXELS`, `CHECKSUM`, `TYPE_MISMATCH`, `SIZE_MISMATCH`). A shared 400 hides which control fired.

## Reference router

| Task | Read |
|---|---|
| Magic numbers, header dimensions, pixel bombs, decoder limits, buffering, SVG | [byte-validation](references/byte-validation.md) |
| Presigned POST/PUT, key and checksum pinning, S3/R2/GCS differences, finalize | [storage-policies](references/storage-policies.md) |
| Response headers, origin isolation, proxy/body limits, archives, malware, lifecycle | [serving-and-limits](references/serving-and-limits.md) |
| Fixture matrix, local S3, negative tests, rejection-code coverage | [verification](references/verification.md) |
| Producing the client bytes and metadata | the `client-compute-architect` skill |

## Before returning an admission design

- Every accepted format has a sniff branch, a header-dimension branch, a decode branch, and its own reject code.
- The effective byte cap is one number enforced at the outermost layer; no inner layer raises it.
- Every upload authorization pins key, exact type, and every property the provider can enforce; finalize checks size, type, and digest against the stored object.
- Every publish path sets a server-chosen type, `nosniff`, a disposition, and an origin with no app cookies.
- The fixture set includes a valid file, wrong magic, truncation, a header/pixel bomb, an oversized body, a checksum mismatch, and a type mismatch, and each fails with the intended code.

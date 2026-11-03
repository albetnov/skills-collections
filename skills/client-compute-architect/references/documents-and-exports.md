# Documents and exports

Exports fail in three places: they build the whole payload in memory, they freeze the tab while doing it, or they produce a file Excel refuses to open. Pick the format from the size, then pick the library.

## Decision

| Output | Client library | Limit |
|---|---|---|
| PDF composed from known data | `pdf-lib` | DOM-free; embed images and fonts; good for invoices, reports |
| PDF with declarative tables and page breaks | `pdfmake` | Larger bundle; verify its worker build before relying on it |
| Quick PDF from an existing view | `window.print()` via a print stylesheet | Not a data export; no control over pagination |
| CSV | A hand-written RFC 4180 writer | Streams; opens everywhere; no styling |
| XLSX, small | `exceljs` or `write-excel-file` | Workbook is built in memory |
| XLSX, large | Server-side generation, or CSV | Browser memory is the ceiling |
| Huge export | File System Access API in a worker, CSV chunks | Chromium only; Blob fallback needs memory |

`pdf-lib` is the safe default for programmatic PDFs: it has no DOM dependency, embeds PNG/JPEG, and supports custom fonts through `@pdf-lib/fontkit`. `pdfmake` is better when the document is a table definition; its browser build assumes a document in some paths, so test it inside the worker rather than assuming it is portable.

Generate from data the client already has. If the server owns the rows, generating the export there avoids shipping the entire dataset to the browser just to turn it back into a file; paginate or stream the data only when the client must assemble it.

The `xlsx` package on npm is an old release with published prototype-pollution and ReDoS advisories. Use the vendor tarball if you need SheetJS, or a maintained alternative.

## PDF

```ts
import { PDFDocument, StandardFonts } from "pdf-lib";

const pdf = await PDFDocument.create();
const page = pdf.addPage([595.28, 841.89]); // A4 in points
const font = await pdf.embedFont(StandardFonts.Helvetica);

page.drawText("Invoice", { x: 40, y: 800, size: 18, font });
const png = await pdf.embedPng(pngBytes);
page.drawImage(png, { x: 40, y: 600, width: 200, height: 150 });

const bytes = await pdf.save();
const blob = new Blob([bytes], { type: "application/pdf" });
```

- Page sizes in points: A4 `595.28 × 841.89`, Letter `612 × 792`, millimetres × `2.8346`.
- Recompress and downscale images before embedding. A 20 MB PNG embedded five times is a 100 MB PDF.
- Load fonts as `ArrayBuffer` from `fetch`; embed only the weights you use. CJK fonts are 5–15 MB before subsetting.
- Add metadata (`setTitle`, `setAuthor`, `setCreationDate`) and a document ID if the file is stored or audited.
- Generate in a worker. A 200-page document with images is CPU and memory work, not a render task.

For a large or legally significant document, generate it on the server and deliver a signed URL. The browser path is for immediate, local, user-owned output.

## CSV

```ts
const escapeCell = (value: unknown) => {
	let text = String(value ?? "");
	if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
	return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

export function toCsv(rows: unknown[][]): string {
	const body = rows.map((row) => row.map(escapeCell).join(",")).join("\r\n");
	return `\uFEFF${body}\r\n`;
}
```

- Quote fields containing a comma, quote, CR, or LF; double embedded quotes.
- CRLF is the interoperable line ending; the UTF-8 BOM is what makes Excel read non-ASCII correctly.
- A leading `=`, `+`, `-`, or `@` is a formula in Excel. Prefix those cells with an apostrophe (or reject them); CSV quoting alone does not stop execution.
- For a large export, build `Blob` parts incrementally and release each string chunk. `new Blob(parts)` still materializes the file in memory; `showSaveFilePicker` plus `FileSystemWritableFileStream` avoids that in Chromium.
- CSV has no types. Dates need one documented format (ISO 8601), numbers no thousands separators, and identifiers kept as strings so Excel does not strip leading zeros.

## Spreadsheet

```ts
import ExcelJS from "exceljs";

const workbook = new ExcelJS.Workbook();
const sheet = workbook.addWorksheet("Export");
sheet.columns = [
	{ header: "id", key: "id", width: 20 },
	{ header: "email", key: "email", width: 40 },
];
sheet.addRows(rows);
const buffer = await workbook.xlsx.writeBuffer();
const blob = new Blob([buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
```

- Excel limits: 1,048,576 rows, 16,384 columns, 32,767 characters per cell, 31 characters per sheet name, and `[]:*?/\` are invalid in sheet names.
- The workbook, styles, and shared strings are all in memory. Above roughly 100k rows, switch to CSV or move generation to the server; a browser export of a million rows is a denial of service against the user.
- Do not put untrusted text in formulas. Write it as a string cell, and prefix formula-leading values.
- `write-excel-file` is a smaller alternative for simple tables. `exceljs` is heavier but supports styling, merged cells, and multiple sheets.

## Save and share

```ts
async function save(blob: Blob, name: string) {
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	a.click();
	setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
```

On mobile, `a.download` may open a preview instead of saving; `navigator.share({ files: [new File([blob], name, { type: blob.type })] })` is the native path where available, with the anchor as the fallback. Do not revoke the URL before the download starts.

Use `showSaveFilePicker()` when the user must choose a location or when the export is too large for a Blob. It is Chromium-only; feature-detect and keep the Blob path.

## Progress and cancellation

- A document generation run reports pages or rows, not a spinner. Update at most a few times per second; a message per row floods the main thread.
- `AbortSignal` cannot interrupt a synchronous `pdf.save()` or a synchronous workbook build. Check a cancelled flag between chunks, and terminate the worker for a hard cancel.
- Disable the export button while a run is active and keep the previous file until the new one succeeds.
- Chunk the work: 1,000 rows per message in a worker, or one page at a time for a PDF. One monolithic `postMessage` with a 200 MB array is a copy you cannot afford.

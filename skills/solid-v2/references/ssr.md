# SSR

One component source runs on the server and in the browser, so this file covers the three ways a line can break that: work that only exists in the browser, values that differ between the two renders, and markup the browser rebuilds differently than the server wrote it.

## Where each line runs

| Code | Server render | Browser |
| --- | --- | --- |
| Module scope | Runs at import, once per process, shared by every request | Runs at import, once per page load |
| Component body | Runs once per request | Runs once per mount |
| `createStore` function, memo compute function | Runs, tracked | Runs, tracked |
| Effect compute function | Runs once; the result is discarded | Runs on each tracked change |
| Effect function (the `apply` half) | Never runs | Runs on each tracked change |
| `onSettled` callback | Never runs; reserves a hydration id | Runs after mount or hydration |
| Event handler | Never runs; there are no events | Runs on the event |
| `"use server"` body | Runs for a server render, in-process under the request event | Never; the call becomes an HTTP request |

The server render is one pass from inputs to HTML. `createEffect` still evaluates its compute function there, because that call is how the effect subscribes, but the effect function and every `onSettled` callback are dropped. The browser runs everything, so a `document.title` write in an effect function takes effect after hydration.

Rules:

- Put browser-only work in an effect function or an `onSettled` callback. Anywhere else the server executes it and throws `window is not defined` before producing HTML.
- A `"use server"` body is the opposite case: it runs on the server on both call paths. During a server render it runs in the same process under the request event; in the browser the wrapper turns it into an HTTP request.
- Never create a signal or a store at module scope. Module scope is evaluated once per process and then shared, so one visitor's state appears in another visitor's response. Create state in a component or a context provider, which runs once per request on the server.
- A setter called during a server render does nothing, because the output has already been serialized as the render walks. Development prints `[SERVER_WRITE]` the first time it happens. Move the write to an event handler, `onSettled`, or an `action`; if the value must be in the HTML, compute it before rendering.

```tsx
import { createEffect, createMemo, createSignal, createStore, onSettled } from "solid-js";

// Module scope: both sides, once per process on the server
const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export function CartSummary() {
	// Component body: both sides, once per request on the server
	const [open, setOpen] = createSignal(false);
	// Store function: both sides; the body of getCart runs on the server only
	const [cart] = createStore(() => getCart(), { items: [] as CartItem[] });
	const total = createMemo(() => cart.items.reduce((sum, item) => sum + item.price * item.quantity, 0));

	createEffect(
		// Compute function: both sides
		() => total(),
		// Effect function: browser only
		(amount) => {
			document.title = `Cart (${currency.format(amount)})`;
		}
	);

	// onSettled callback: browser only
	onSettled(() => {
		document.getElementById("cart-toggle")?.focus();
	});

	return (
		<aside>
			<button id="cart-toggle" onClick={() => setOpen(!open())}>
				{cart.items.length} items, {currency.format(total())}
			</button>
		</aside>
	);
}
```

## Browser APIs

A browser API read at module scope, in a component body, or in a compute function runs on the server and crashes the request. The server has no `window`, `document`, `localStorage`, `matchMedia`, or `navigator` state, so the fix is always to move the read below the render boundary.

```tsx
import type { ParentProps } from "solid-js";

// Avoid: the read runs in the component body, so the server throws
function CartDrawer(props: ParentProps) {
	const compact = window.matchMedia("(max-width: 40rem)").matches;
	return <aside class={compact ? "drawer drawer-compact" : "drawer"}>{props.children}</aside>;
}
```

```tsx
import { createSignal, onSettled, type ParentProps } from "solid-js";

// Prefer: the browser answers after hydration, and the answer is a signal
function CartDrawer(props: ParentProps) {
	const [compact, setCompact] = createSignal(false);

	onSettled(() => {
		const query = window.matchMedia("(max-width: 40rem)");
		setCompact(query.matches);
		const update = (event: MediaQueryListEvent) => setCompact(event.matches);
		query.addEventListener("change", update);
		return () => query.removeEventListener("change", update);
	});

	return <aside class={compact() ? "drawer drawer-compact" : "drawer"}>{props.children}</aside>;
}
```

The `Avoid` version throws before the drawer produces any HTML. The `Prefer` version renders `class="drawer"` on the server, hydrates the same markup, then reads the media query once and updates the class; the returned cleanup removes the listener when the drawer is disposed.

- Seed a browser-measured signal with the deterministic value so the first client render matches the server. A `false` seed is correct while hydrating but costs a visible flip on a client-side navigation, where there is no server markup to agree with.
- Use `isHydrating()` to separate those two cases. It is `true` during the root pass of `hydrate()` and while a streamed boundary resumes; `false` on the server, in a client-only render, and afterwards. It is not reactive, so read it where the signal is created.

```tsx
import { createSignal, isHydrating, onSettled } from "solid-js";
import { isServer } from "@solidjs/web";

function CartDrawer() {
	const [compact, setCompact] = createSignal(
		isServer || isHydrating() ? false : window.matchMedia("(max-width: 40rem)").matches
	);

	onSettled(() => {
		setCompact(window.matchMedia("(max-width: 40rem)").matches);
	});

	return <aside class={compact() ? "drawer drawer-compact" : "drawer"} />;
}
```

The `onSettled` callback stays in both variants: it is what updates the value after a hydrated first paint.

- For a helper called where there is no owner, such as a formatter shared with server code, use `isServer` from `@solidjs/web`. It is a build-time constant — `true` in server output, `false` in browser output — so the bundler removes the unreachable branch.

```ts
import { isServer } from "@solidjs/web";

export function prefersReducedMotion(): boolean {
	if (isServer) return false;
	return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
```

`isServer` prevents the crash; it does not make the two renders agree. This helper returns `false` on the server and possibly `true` in the browser, so use its result in an effect function or `onSettled`, never in JSX that decides which elements exist.

- When a component cannot be made safe — a map or rich-text editor whose library touches `window` at import — wrap it in `clientOnly`. The server renders the fallback and never starts the import; the browser hydrates the fallback, waits for the module and for hydration to settle, then swaps the component in.

```tsx
import { clientOnly } from "@solidjs/web";

const Map = clientOnly(() => import("./Map"), { lazy: true });

export function StoreLocator(props: { city: string }) {
	return <Map city={props.city} fallback={<div class="map-placeholder" />} />;
}
```

- Pass `{ lazy: true }` to defer the import until first render; without it the import starts when the declaration runs. Data the imported component needs must be fetched above the boundary, because its async reads start only on the client.
- Keep a module-scope import only when it is server-safe. A library that reads `window` in its module body fails at import, before any component runs, and `clientOnly` or a dynamic import inside `onSettled` is the only fix.

## Per-run values

Any value that decides which elements exist must be computed once, on the server, then passed as data. `Math.random()`, `Date.now()`, `crypto.randomUUID()`, `navigator.language`, and anything else the two sides compute independently will otherwise disagree.

```tsx
import { Show } from "solid-js";

// Avoid: each side rolls its own value
function Promo() {
	return (
		<Show when={Math.random() < 0.5}>
			<aside class="promo">Free shipping on orders over $50</aside>
		</Show>
	);
}
```

```tsx
import { Show } from "solid-js";

// Prefer: one side decides, both sides render the decision
function Promo(props: { message: string | null }) {
	return (
		<Show when={props.message}>
			<aside class="promo">{props.message}</aside>
		</Show>
	);
}
```

With the `Avoid` version, half of the page loads disagree. If the server rendered the banner and the browser did not, development reports unclaimed server-rendered nodes and the banner stays in the document with nothing attached. If the browser rendered it and the server did not, development reports a key miss and the banner is a detached element that never appears.

Rules:

- When the condition depends on a random, a clock, a locale, or a generated id, compute it in the same request that renders the page and pass it down as a prop or a store field.
- Text is not compared during hydration. Hydration claims each template root by its key and the nodes inside by position, checks tags in development, and adopts server text as-is. `<p>{Date.now()}</p>` produces no warning and keeps the server's text until a reactive update replaces it; only structure changes — a `Show`, a list length, an element that exists on one side — warn.
- Use `createUniqueId()` for any id that appears in both markup and an attribute (`id` plus `for`, `aria-labelledby`, `aria-describedby`). A counter or `Math.random()` gives the two sides different strings, so the `<label>` points at a missing input.

```tsx
import { createUniqueId } from "solid-js";

function Field(props: { label: string; value: string }) {
	const id = createUniqueId();
	return (
		<>
			<label for={id}>{props.label}</label>
			<input id={id} value={props.value} />
		</>
	);
}
```

`createUniqueId` derives the id from the component's position in the owner tree on both sides, so the attribute the server wrote is the attribute the browser hydrates. Call it during component setup; on the server it throws outside a reactive context.

- For a value that must count up in the browser, render a server-provided value first and let the browser take over after hydration. The first text then matches on both sides, and the timer starts only in the browser.

```tsx
import { createSignal, onSettled } from "solid-js";

function formatRemaining(ms: number): string {
	const seconds = Math.max(0, Math.floor(ms / 1000));
	return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function SaleCountdown(props: { endsAt: number; serverNow: number }) {
	const [now, setNow] = createSignal(props.serverNow);

	onSettled(() => {
		const timer = setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(timer);
	});

	return <p>Sale ends in {formatRemaining(props.endsAt - now())}</p>;
}
```

`serverNow` comes from the server function that returned the product, so both sides render the same first text.

## Data the server does not have

When data lives only in the browser, the server renders its seed and the browser fills it in after hydration. A `localStorage` cart renders empty, then shows three items one frame later, for a visitor who never saw the empty state in the browser. Accept that cost only for drafts the current browser alone cares about: read storage in `onSettled` and write it back from an effect function.

When the first frame must be correct, move the data to where the server can read it. A cart id in a cookie arrives with every request, so a server function can read it from the request event and a store function renders the real items on the server:

```ts
import { getRequestEvent, parseCookieHeader } from "@solidjs/web";

export async function getCart(): Promise<{ items: CartItem[] }> {
	"use server";
	const event = getRequestEvent();
	const cookies = parseCookieHeader(event?.request.headers.get("cookie") ?? "");
	const cartId = cookies["cart"];
	if (!cartId) return { items: [] };
	return (await database.carts.get(cartId)) ?? { items: [] };
}

declare const database: {
	carts: { get(id: string): Promise<{ items: CartItem[] } | undefined> };
};
```

`createStore(() => getCart(), { items: [] as CartItem[] })` then renders three items in the HTML, and the browser asks the same function for the same answer. Once a signed-in session exists, middleware-set `event.locals.userId` replaces the raw cookie read.

Choose by who needs the first frame: a shareable link, a crawler, or a slow connection needs the server's view; a draft only the current browser cares about can wait for hydration.

## Markup the browser rewrites

The browser's HTML parser does not build every tree it is handed. A `<div>` inside a `<p>` closes the paragraph first, a `<tr>` directly inside a `<table>` gets an implied `<tbody>`, and an `<a>` inside an `<a>` ends the outer link. The server writes the JSX structure; the browser builds a different one; the client's compiled template then looks for nodes that are not where it expects them.

The compiler catches this when the whole structure is in one JSX expression:

```tsx
// Avoid: the parser closes <p> when it meets <div>
function Description(props: { badge: string; text: string }) {
	return (
		<p class="description">
			<div class="badge">{props.badge}</div>
			{props.text}
		</p>
	);
}
```

```tsx
// Prefer: an element that may contain flow content
function Description(props: { badge: string; text: string }) {
	return (
		<div class="description">
			<div class="badge">{props.badge}</div>
			<p>{props.text}</p>
		</div>
	);
}
```

The `Avoid` version fails the build with `The HTML provided is malformed and will yield unexpected output when evaluated by a browser.`, followed by the HTML as written and the HTML a browser would build from it. The check strips attributes and text, so compare the tag order of the two skeletons to find the moved node.

The compiler cannot see across components. A `Description` component that renders `<p>{props.children}</p>` and a parent that passes `<div>` children each compile to a valid template, and the browser still rebuilds the tree at runtime. When a hydration warning points at an element whose parent in the Elements panel is not its parent in the JSX, look for nesting that spans a component boundary and change the outer element.

## Hydration warnings

Development compares the server's DOM with the client's expectations and prints one of five messages. Each names a different check, and the check says where to look. Production runs none of these checks.

| Message | What it means | Where to look |
| --- | --- | --- |
| `Hydration structure mismatch: expected <X> as first child of` | The client is walking inside one template and the node at that position is not the element the template expects. The `after` variant reports the same check for a later sibling. | Markup the browser rewrote, or a template root claimed from the wrong place because an earlier element shifted ids. The line after the message sketches the parent's children with `← expected X` or `← missing`. |
| `Hydration tag mismatch for key "...": expected <X> but found` | A template root was found under its hydration key, but it is a different element than the template's root. | Two branches rendered different elements at the same position: an `isServer` conditional inside JSX, or two components whose order differs. |
| `Hydration key miss for "...": no server-rendered element carries this key` | The client rendered a template root the server never emitted under that id; the message adds that a detached element was created and will not appear or become interactive. | A branch that runs only in the browser (`Show when={!isServer}`), a per-run value, or a subtree hydrated under a different `renderId` than the server used. |
| `Hydration completed with N unclaimed server-rendered node(s):` | Hydration finished and the listed server-rendered elements were never claimed by the client. | The server rendered something the browser did not — the mirror image of a key miss. |
| `Hydration Mismatch. Unable to find DOM nodes for hydration key` | An error, not a warning: code that claims an element without a template to fall back on, such as `dynamic()` resolving to a string tag, found no server node under its key. | The same causes as a key miss; the difference is that there is no template from which to create a stand-in. |

Rules:

- Read the first mismatch in the console and fix it before looking at the rest. One shifted node produces a cascade of later warnings, so the later messages usually describe consequences, not causes.
- Check three things in order: invalid nesting, ids that differ between renders, and any value the two sides compute independently.
- A key miss and an unclaimed node are two directions of the same disagreement; decide which side rendered the extra element, then make that side render the same structure as the other.
- These checks are development-only. A clean production console is not evidence that the server and client agree, so run the dev server after changing anything structural.

## Rendering modes

All modes run the same `App` and `Document`; the mode changes one or two plugin options, what the build writes, and what the host must run.

| Mode | Config | First paint | Server code |
| --- | --- | --- | --- |
| Static shell, client render | `solid({ start: true })` | `Document` shell, then the app once the bundle and data arrive | None in the response; the build writes an empty shell |
| Streaming SSR | `solid({ start: true, ssr: true })` | Real HTML immediately, with each `Loading` fallback standing in until it settles | Every request |
| Prerendered | `ssr: true` plus the crawler plugin | Complete HTML, as with SSR | Once, at build time |

```ts
import solid from "@solidjs/vite-plugin";
import { serverFunctions } from "@solidjs/prerender/integration";
import { prerender } from "prerender-crawler/vite";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [
		solid({ start: true, ssr: true, serverFunctions: true }),
		prerender({ mode: "static", integrations: [serverFunctions()] }),
	],
});
```

`prerender-crawler` starts at `/`, renders each page through the server build, writes the HTML, and follows same-origin links to find the rest. Server functions wrapped in `prerendered()` from `@solidjs/prerender` run during the build, and their results are written as JSON instead of being called at runtime.

Choose in three questions:

1. Must the content be in the HTML, for search, link previews, or first paint on a slow connection? If no, use the static shell.
2. Does the content change between deploys or depend on who is asking? If no, prerender.
3. Otherwise stream with `ssr: true`.

Rules:

- `ssr` changes assumptions, not components. Under `ssr: true` the document, component bodies, and compute functions run on the server; code that tolerated a browser-only runtime must move below the render boundary as described above.
- A static shell with `serverFunctions: true` still needs the `dist/server` handler deployed. Prerendering with `prerendered()` is the way to ship files only while keeping server-side data.
- Do not decide from development. The crawler runs during `vite build`, and that is where a server function nothing prerendered is reported.
- A `Loading` boundary is a server decision, not only a client one. An async read with no boundary above it blocks the shell until it settles; a boundary around the region lets the shell ship with the fallback and the content stream in later. Put the boundary around the region, not the page.

The client side of a server render is `hydrate`, which claims the existing nodes instead of rebuilding them:

```tsx
import { hydrate } from "@solidjs/web";

const root = document.getElementById("app");

if (!root) throw new Error("Missing #app");

hydrate(() => <App />, root);
```

`hydrate` must receive the same root JSX the server rendered, including the same `renderId` when one was set. For several roots on one page, give each server render a distinct `renderId` and pass it to the matching `hydrate` call.

## Document shell

The document shell is `src/Document.tsx`, the default-exported full HTML document. It receives the app as `props.children`; a body that does not render `props.children` never renders the app. Site-wide head tags belong here, and the plugin injects the client script — do not write that tag yourself.

```tsx
import type { ParentProps } from "solid-js";
import { HydrationScript } from "@solidjs/web";

export default function Document(props: ParentProps) {
	return (
		<html lang="en">
			<head>
				<meta charset="utf-8" />
				<meta name="viewport" content="width=device-width, initial-scale=1" />
				<title>Storefront</title>
				<HydrationScript />
			</head>
			<body>{props.children}</body>
		</html>
	);
}
```

Rules:

- Include `HydrationScript` exactly once, in `<head>` before the app markup, when `ssr` is on. Without it, clicks and input that happen between the HTML arriving and the bundle hydrating are dropped, because the script records delegated events and initializes hydration support.
- Keep `<HydrationScript />` even in a static-shell project. The handler strips its output from the prerendered shell, so it costs nothing until `ssr` is turned on.
- Put the charset, viewport, favicon, and default title in `Document`. A page that needs its own title renders `Title` from `@solidjs/meta`, which replaces the document title on both sides.

```tsx
import { Title } from "@solidjs/meta";

export default function ProductPage(props: { product: { name: string } }) {
	return (
		<>
			<Title>{`${props.product.name} — Storefront`}</Title>
			<main>{props.product.name}</main>
		</>
	);
}
```

- The static `<title>` in `Document` is the fallback for pages that mount no `Title`; it is not a second source of truth.

## Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `window is not defined` or `document is not defined` at import | A module body, component body, or compute function reads a browser API, and with `ssr: true` it runs on the server | Move the read into an effect function or `onSettled`, guard a helper with `isServer`, or wrap the component in `clientOnly` |
| A hydration mismatch survives the crash fix | Both sides render now, but with different structures: a per-run value in a condition, an `isServer` check inside JSX, or data one side lacks | Compute the decision on the server and pass it as data; render the same structure on both sides and fill browser-only values after hydration |
| The build fails with `The HTML provided is malformed` | One template nests elements the parser would move, such as `<div>` inside `<p>` or `<tr>` directly inside `<table>` | Compare the two HTML skeletons in the message and change the outer element; look across component boundaries when the message does not fire |
| The cart shows empty, then fills in | The data lives in `localStorage` or in memory, so the server renders the empty seed | Either accept the first frame for browser-only drafts, or move the data behind a cookie or session that the server function reads |
| A `<label>` points at a different id than its `<input>` | The id came from a counter or `Math.random()`, so the server and browser generated different strings | Use `createUniqueId()` inside the component so both sides derive the same id from the owner tree |

See also: `references/async.md` for what stands in the shell under a `Loading` boundary and how held updates interact with hydration.

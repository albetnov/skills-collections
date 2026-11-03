# TypeScript and testing

This reference covers two contracts that share one setup: the TypeScript types that describe a Solid 2.0 app's data flow, and the tests that prove the app behaves as described. Assume the model from the primer — components run once, props are getters, async is a value.

## Config
```json
{ "compilerOptions": { "jsx": "preserve", "jsxImportSource": "@solidjs/web", "strict": true } }
```
- `jsx: "preserve"` leaves JSX for the Vite plugin, which compiles `.tsx` itself. Any other value makes the checker and the compiler disagree about what an expression compiles to.
- `jsxImportSource: "@solidjs/web"` points the checker at the DOM renderer's element, attribute, and event types. With another value, every intrinsic element is unknown.
- `strict: true` is what makes `createSignal<Product>()` report its `undefined` before the first render does.

`solid-js` exports the renderer-neutral types: `Component`, `Element`, `ParentProps`, `Accessor`, `Store`. It exports **no** `JSX` namespace. Every `JSX.*` type — `JSX.Element`, `JSX.EventHandler`, `JSX.IntrinsicElements` — comes from `@solidjs/web`, so a `declare module "solid-js"` block changes nothing about what JSX accepts. `@solidjs/web` also exports a `ComponentProps` that accepts a tag name, so `ComponentProps<"button">` is a native button's attributes. Do not annotate a component's return type by hand; infer it, and use `JSX.Element` only where a type is genuinely needed — a prop that accepts markup, or a callback that returns markup.

## Props
An ordinary component is a function declaration with one typed parameter. Use `Component<P>` when the component is a value: stored in a map, passed to `dynamic()`, or returned from `lazy()`. Both shapes produce identical checks, because `Component<P>` is `(props: P) => Element`.
```tsx
import type { Component } from "solid-js";

type Product = { id: string; name: string; price: number };

function LineItem(props: { product: Product; quantity: number }) {
	return <li>{props.product.name} × {props.quantity}</li>;
}

const Row: Component<{ product: Product; quantity: number }> = (props) => (
	<li>{props.product.name}</li>
);
```
Three helpers extend a props type with a children contract:
```tsx
import type { FlowProps, ParentProps, VoidProps } from "solid-js";
import type { JSX } from "@solidjs/web";

function Panel(props: ParentProps<{ title: string }>) { return <section>{props.children}</section>; }
function Price(props: VoidProps<{ amount: number }>) { return <span>{props.amount}</span>; }
function Loader(props: FlowProps<{ id: string }, (p: Product) => JSX.Element>) {
	return <>{props.children(getProduct(props.id))}</>;
}
```
- `ParentProps` makes `children` an optional `JSX.Element`.
- `VoidProps` types `children` as `never`. Write `<Price amount={12}>USD</Price>` and the checker rejects the text child — without it the text type-checks and is dropped at runtime, because a component renders only the children it reads.
- `FlowProps` requires a child of a specific type; use it for render callbacks.

Reuse another component's contract by deriving it: `ComponentProps<typeof Button>` is whatever `Button` declared, so adding a prop to `Button` adds it to every consumer with no second edit. Defaults and rest props keep reactivity through `merge` and `omit`:
```tsx
import { merge, omit } from "solid-js";
import type { JSX } from "@solidjs/web";

function Button(
	_props: { label: string; variant?: "primary" | "ghost" } & JSX.ButtonHTMLAttributes<HTMLButtonElement>
) {
	const props = merge({ variant: "primary" } as const, _props);
	const rest = omit(props, "label", "variant");
	return <button {...rest} class={props.variant}>{props.label}</button>;
}
```
After `merge`, `props.variant` is `"primary" | "ghost"` with `undefined` gone. After `omit`, `rest.label` is a type error, so a consumed prop cannot leak onto the `<button>`. Both return reactive views; they replace destructuring and spreading, which read once.
```tsx
// Avoid: valid TypeScript, reads quantity once in the component body
function LineItem({ quantity }: { quantity: number }) {
	return <li>{quantity}</li>;
}

// Prefer: read the prop where it is used
function LineItem(props: { quantity: number }) {
	return <li>{props.quantity}</li>;
}
```
The `Avoid` version compiles clean because destructuring a parameter is ordinary TypeScript. At runtime the parent's next `quantity` never reaches the row, and development prints `[STRICT_READ_UNTRACKED]` with the component name. Types describe the shape of `props`, not when it is read; `const quantity = props.quantity` in the body is the same bug. Props are read-only from the child's side — a child that must change a value calls a callback prop from an event handler.

## Element and children
`JSX.Element` is the core `Element` widened with DOM `Node`: the type for "markup", whether it arrives as a prop, a child, or a return value. `ResolvedElement` excludes arrays. When a component must inspect or iterate its children, use the `children` helper:
```tsx
import { children, type ParentProps } from "solid-js";

function Stack(props: ParentProps) {
	const resolved = children(() => props.children);
	return <div class="stack">{resolved.toArray()}</div>;
}
```
`children()` returns a `ChildrenReturn`: an accessor of the resolved children with `toArray(): ResolvedElement[]`. Both types are exported from `solid-js`. Call it once in the component body — reading `props.children` in several places creates the children several times, each with its own DOM — and note that the accessor resolves lazily, at the point where the result is inserted or `toArray()` runs.

## Signals, memos, and setters
`createSignal` infers from the initial value; the no-argument form includes `undefined`:
```tsx
import { createMemo, createSignal } from "solid-js";

const [quantity, setQuantity] = createSignal(1); // Signal<number>
const [selected, setSelected] = createSignal<string>(); // Signal<string | undefined>
setQuantity((prev) => prev + 1);
setSelected();
const product = createMemo(() => getProduct(props.id)); // SourceAccessor<Product>
```
`Signal<T>` is `[get: SourceAccessor<T>, set: Setter<T>]`. `Accessor<T>` is just `() => T`; `SourceAccessor<T>` is that accessor with a `Refreshable` brand, which is what lets `refresh()` accept it. A parameter typed `Accessor<T>` accepts a `SourceAccessor<T>`; the reverse does not hold, so type a shared accessor prop as `SourceAccessor<T>` only when the child hands it to `refresh()`. A memo whose compute function returns a promise is typed as the settled value: `product()` is a `Product`, never a `Promise<Product>`; the pending state is a boundary concern, not a type.

Accessors travel as props in two ways, and mixing them is the most common type error in a component tree:
```tsx
function Results(props: { query: string }) {
	return <p>{props.query}</p>;
}

// Avoid: the accessor is passed where the value is expected
<Results query={query} />;

// Prefer: call it; the dynamic attribute compiles to a props getter
<Results query={query()} />;
```
The `Avoid` line fails with `Type 'SourceAccessor<string>' is not assignable to type 'string'`. The `Prefer` line stays reactive: the getter re-reads `query()` at the point of use, inside `Results`. Type a prop as `Accessor<T>` only when the child needs the function itself — to hand it to a primitive or defer the read — and give a setter prop `Setter<T>`, which accepts a value or an updater.

A function passed to a setter is read as an updater, not as a value: `setHandler(() => console.log("saved"))` reports `Type 'void' is not assignable to type 'Handler'`. To store a function, return it from an updater: `setHandler(() => next)`. The same rule governs `createSignal`: a function first argument is the writable-derivation form, not an initial value.

## Stores
`createStore<T>` returns `[Store<T>, StoreSetter<T>]`, and `Store<T>` is `T`, so a store passes anywhere the plain value is expected with no cast.
```tsx
import { createStore, reconcile } from "solid-js";

type CartItem = { id: string; name: string; price: number; quantity: number };
type Cart = { items: CartItem[]; coupon: string };

const [cart, setCart] = createStore<Cart>({ items: [], coupon: "" });
setCart((draft) => {
	draft.items.push({ id: "mug", name: "Mug", price: 12, quantity: 1 });
});
setCart(reconcile(nextCart));
<CartLines items={cart.items} />;
```
- The draft parameter has the store's type, so `draft.coupon = 5` or a half-built item is reported on the line that wrote it.
- `reconcile(value)` returns `(state: U) => T`, exactly what the setter takes.
- The derived form without a seed, `createStore(async () => getCart())`, is typed by the function's return, so `cart` is `Store<Cart>`. It takes object roots only.
- With a seed, the store is typed by the seed, which must be a complete `T`: `{ items: [] }` for `Cart` is a type error, and an array store seeds with `[]`.

`createProjection` has no setter, follows the same two forms, and returns a `Store<T>`; `ProjectionOptions` adds `key` (default `"id"`), `seedLoadingValue`, `deferStream`, and `ssrSource`:
```tsx
import { createProjection, type Store } from "solid-js";

type User = { id: string; name: string; active: boolean };
const activeUsers: Store<User[]> = createProjection<User[]>(
	() => allUsers().filter((user) => user.active),
	[]
);
```
A projected collection seeds with `[]`, never with a partial element.

## Events and refs
Inline handlers take their element type from the JSX they sit on:
```tsx
<input onInput={(event) => setQuery(event.currentTarget.value)} />
<button onClick={(event) => event.currentTarget.disabled} />
```
- `event.currentTarget` is the element the handler is attached to: `HTMLInputElement`, then `HTMLButtonElement`. Read it.
- `event.target` is narrowed to the same element only for `onInput`, `onChange`, and focus events on `input`, `select`, and `textarea`. Anywhere else it is `Element`, and `event.target.value` in an `onClick` is `Property 'value' does not exist on type 'EventTarget & Element'`.

A handler defined outside the JSX uses the namespace types:
```tsx
import type { JSX } from "@solidjs/web";

const onInput: JSX.InputEventHandler<HTMLInputElement, InputEvent> = (event) =>
	setQuery(event.target.value);
const onClick: JSX.EventHandler<HTMLButtonElement, MouseEvent> = (event) =>
	event.currentTarget.blur();
```
A prop that forwards to an element takes `JSX.EventHandlerUnion<HTMLButtonElement, MouseEvent>` — the union the element attribute itself accepts, which includes the bound `[handler, data]` form; a narrower handler type rejects that form.

A `ref` variable is `undefined` until Solid creates the element, so annotate it as definitely assigned and read it only after creation:
```tsx
function SearchField() {
	let input!: HTMLInputElement;
	return (
		<>
			<input ref={(element) => (input = element)} type="search" />
			<button type="button" onClick={() => input.select()}>Select</button>
		</>
	);
}
```
The `!` holds because every read is in an event handler or `onSettled`, both of which run after the element exists. Reading `input` in the component body fails with `'input' is possibly 'undefined'` — the checker is describing the runtime. A component that exposes its element takes a `Ref<T>` prop — `T | ((val: T) => void) | undefined | Ref<T>[]` from `solid-js` — and passes it straight to `ref`. Ref callbacks run untracked and without an owner: never create a primitive, effect, or cleanup inside one; a factory that creates its setup during component setup and returns the callback is the correct shape.

## Custom elements
A hyphenated tag is unknown until declared. Augment the `JSX` namespace of `@solidjs/web` — the package `jsxImportSource` names, not `solid-js`:
```ts
// src/types/custom-elements.d.ts
export {};

declare module "@solidjs/web" {
	namespace JSX {
		interface IntrinsicElements {
			"date-picker": HTMLAttributes<HTMLElement> & {
				value?: string;
				"prop:disabledDates"?: string[];
				onDatechange?: (event: CustomEvent<{ value: string }>) => void;
			};
		}
	}
}
```
Inside the augmented namespace, `HTMLAttributes` is the namespace's own interface, which supplies global attributes, `ref`, and the standard handlers. Then `event.detail.value` is a `string`, and `prop:disabledDates={1}` reports `Type 'number' is not assignable to type 'string[]'`.

Two details decide whether the declaration applies:

- The file must be a module. `export {};` (or any import/export) makes `declare module` an augmentation that merges. Without it the file is a global script, and the same block declares a replacement module whose only member is the namespace: imports such as `render` then report `Module '"@solidjs/web"' has no exported member 'render'`, and the tag is still unknown.
- No `.ts` file may share its name. `date-picker.d.ts` beside `date-picker.ts` is treated as that file's output and excluded from the program, so the declaration silently never applies.

`prop:` types the property assignment the runtime performs; a plain attribute goes through attribute-string semantics, so an object or array must use `prop:`. Event prop names are case-sensitive and must match the event the element dispatches.

## Generic components
A component that works over a type parameter is a generic function; `T` is inferred from `options`, so both callbacks are typed from the caller's array:
```tsx
import { For } from "solid-js";

type SelectProps<T> = { options: T[]; label: (option: T) => string; onChange: (value: T) => void };

function Select<T>(props: SelectProps<T>) {
	return (
		<select onChange={(event) => props.onChange(props.options[event.currentTarget.selectedIndex])}>
			<For each={props.options}>{(option) => <option>{props.label(option)}</option>}</For>
		</select>
	);
}
```
An arrow function needs a trailing comma in the type parameter list, `const first = <T,>(items: T[]) => items[0]`; without it a `.tsx` file reads `<T>` as a JSX tag and reports `JSX element 'T' has no corresponding closing tag`. When the component itself is stored as a value, build it through the type: `const makeSelect = <T,>(): Component<SelectProps<T>> => (props) => <Select {...props} />;`. Keep `any` out of both shapes: a generic parameter, `unknown` plus a narrowing guard, or a union describes the real contract, and `any` disables the check that would have caught an accessor passed as a value.

## Server functions and router
A `"use server"` function is typed like any async function, and every caller sees its declared return type:
```tsx
import { getRequestEvent, redirect } from "@solidjs/web";

export async function getCart() {
	"use server";
	const userId = getRequestEvent()?.locals.userId;
	if (!userId) throw redirect("/sign-in");
	return database.cart.forUser(userId);
}

export async function deleteAccount() {
	"use server";
	const userId = getRequestEvent()?.locals.userId;
	if (!userId) return redirect("/sign-in");
	return database.cart.forUser(userId);
}
```
`redirect()` returns a `Response`. Thrown, it leaves the return type alone, so `await getCart()` is a `Cart`. Returned, it widens the result to `Cart | Response`, which is what plain code receives when it calls the function directly. `getRequestEvent()` is `RequestEvent | undefined`, so the optional chain is required. `locals` keys are typed by augmentation, and an un-augmented key reads as `any`, so a typo in `locals.userid` type-checks until this block exists:
```ts
declare module "@solidjs/web" {
	interface RequestEventLocals {
		userId: string;
	}
}
```
Route types are derived from the route table, never hand-written. `defineRoutes` keeps the path literals, so a typed path node is the witness for both the component and its props:
```tsx
import type { PathParamsOf, RouteProps } from "@solidjs/router";
import type { Router } from "../router";

export default function Product(props: RouteProps<typeof Router.paths.products>) {
	return <h1>{props.params.id}</h1>;
}
type ProductParams = PathParamsOf<typeof Router.paths.products>; // { id: string }
```
`RouteComponent<typeof Router.paths.products>` is the same contract when the component is a value. With `matchFilters: { id: int }`, `Router.paths.account.orders("latest")` reports `Argument of type 'string' is not assignable to parameter of type 'number'` — a builder's parameter type is its filter's input type. A typed path builder returns an `Href`-branded value from `@solidjs/web`; `const target: Href = paths.products("mug")` is accepted by `redirect(url: string | Href)`, and the brand carries the logical pathname, so a hash-history integration receives a routable Location header rather than its display form.

`query` preserves its function's contract and adds key helpers: `query(getProduct, "product")` returns `CachedFunction<typeof getProduct>`, which keeps `Parameters` and `ReturnType` and adds `key` and `keyFor`. A query read has the server function's return type; `refresh()` and `revalidate()` do not widen it.

## Choosing a test environment
Pick the smallest environment that exercises the behavior under test.

| Environment | Use when | Cost |
| --- | --- | --- |
| jsdom | Component DOM, event wiring, conditional and list rendering | No layout, CSS, real focus, or browser APIs |
| Vitest browser mode (Chromium) | The test depends on layout, CSS, focus, selection, or a browser API | Slower; needs Playwright browsers |
| Separate Node project | Server functions, middleware, sessions, request/response | Needs the server build aliased and the env module stubbed |

Start component tests in jsdom. A test that passes in jsdom and fails in the browser is measuring layout, not behavior — move it up an environment rather than patching it.

## jsdom setup
```sh
pnpm add -D vitest jsdom @solidjs/testing-library @testing-library/jest-dom
```
```ts
import { defineConfig } from "vitest/config";
import solid from "@solidjs/vite-plugin";

export default defineConfig({
	plugins: [solid()],
	test: {
		environment: "jsdom",
		globals: false,
		setupFiles: ["./vitest-setup.ts"],
		// Remove this option when tests need module isolation.
		isolate: false,
	},
});
```
```ts
// vitest-setup.ts
import "@testing-library/jest-dom/vitest";
```
- `environment: "jsdom"` is per test project; the Solid plugin does not choose it. Without it, a `.test.tsx` file runs in Node and fails with `document is not defined`.
- `isolate: false` is a speed setting: module state survives from one test file into the next. Remove it when tests mutate module-level state, or reset that state in `afterEach`. A module-scope store that leaks between files looks like a component bug.
- `globals: false` means nothing installs an automatic afterEach; register cleanup explicitly.

## The interaction test
```tsx
import { cleanup, fireEvent, render } from "@solidjs/testing-library";
import { flush } from "solid-js";
import { afterEach, describe, expect, test } from "vitest";

import Counter from "./Counter";

afterEach(cleanup);

describe("<Counter />", () => {
	test("increments on click", () => {
		const { getByRole } = render(() => <Counter />);
		const button = getByRole("button");
		expect(button).toHaveTextContent("Clicks: 0");
		fireEvent.click(button);
		flush();
		expect(button).toHaveTextContent("Clicks: 1");
	});
});
```
- Pass a function to `render`, not the component or an element. The function form runs the component under a reactive owner, so memos and effects created inside it are disposed by `cleanup`; passing the component itself loses the owner.
- Query by accessible role and assert visible text or state. Do not inspect signal values, effect counts, or compiled output.
- `fireEvent.click` stages the write; `flush()` commits it and drains queued work. Asserting on the next line without it reports the old value — there is no automatic flush before an assertion.
- `flush()` does not wait for async work. For behavior that is asynchronous by contract — an async memo, a form submission — await the settled value instead: `const settled = await resolve(() => product())`, with `resolve` from `solid-js` and the read outside any tracking scope. Asynchronous queries (`findByRole`) are the alternative when the assertion itself should wait.

## Browser mode
```sh
pnpm add -D vitest @solidjs/testing-library @testing-library/jest-dom @vitest/browser-playwright playwright
pnpm exec playwright install chromium
```
```ts
import { playwright } from "@vitest/browser-playwright";
import { defineConfig } from "vitest/config";
import solid from "@solidjs/vite-plugin";

export default defineConfig({
	plugins: [solid()],
	test: {
		globals: false,
		setupFiles: ["./vitest-setup.ts"],
		browser: { enabled: true, provider: playwright(), headless: true, instances: [{ browser: "chromium" }] },
	},
});
```
The jsdom interaction test runs unchanged: same `render`, same `flush()`, same role query. Only the host changes from a simulated document to a Chromium page. Run it once and exit with `pnpm test --run`. Keep jsdom installed even in browser mode — the plugin resolves it before the browser pool starts.

An end-to-end test against a server-rendered page must wait until hydration ends before it clicks. `onHydrationEnd` runs its callback once the hydration phase ends:
```tsx
// src/entry-client.tsx
import { onHydrationEnd } from "solid-js";
import { hydrate } from "@solidjs/web";
import App from "./App";

hydrate(() => <App />, document);
onHydrationEnd(() => {
	document.documentElement.dataset.hydrated = "";
});
```
Register the callback after `hydrate()`; registered earlier, it runs in the next microtask without waiting. The test waits for `html[data-hydrated]` before interacting. The marker means the phase ended, not that it succeeded — use it in tests, never to change what the app renders.

## Server tests
Keep client and server files in separate Vitest projects so each file lands in exactly one environment:
```ts
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import solid from "@solidjs/vite-plugin";

const build = (path: string) =>
	fileURLToPath(new URL(`./node_modules/${path}`, import.meta.url));
const local = (path: string) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig({
	plugins: [solid({ start: true, ssr: true })],
	test: {
		globals: false,
		setupFiles: ["./vitest-setup.ts"],
		projects: [
			{ extends: true, test: { name: "client", environment: "jsdom", include: ["src/**/*.test.tsx"] } },
			{ extends: true, test: {
				name: "server",
				environment: "node",
				include: ["src/server/**/*.test.ts"],
				server: { deps: { inline: [/@solidjs[+/]web/] } },
				alias: [
					{ find: /^@solidjs\/web$/, replacement: build("@solidjs/web/dist/server.js") },
					{ find: /^@solidjs\/web\/storage$/, replacement: build("@solidjs/web/storage/dist/storage.js") },
					{ find: "virtual:env/server", replacement: local("./vitest-env-server-stub.ts") },
				],
			} },
		],
	},
});
```
- The alias keeps request helpers and request-event storage on the **same** server-build instance. Inlining only one of them gives two module instances, and `getRequestEvent()` returns `undefined` inside a handler that is clearly running.
- `src/server/**/*.test.ts` and `src/**/*.test.tsx` must stay disjoint. A server file matched by the client pattern runs under jsdom and fails on Node APIs.

Code that reads an environment module at import time needs the stub plus a module reset. The proxy reads `process.env` per property access, so setting `process.env.SESSION_SECRET` before import works; it does not validate the key or boot the server, so use a realistic test key:
```ts
// vitest-env-server-stub.ts
export const env: Record<string, unknown> = new Proxy({}, {
	get: (_, key) => {
		if (typeof key !== "string") return undefined;
		const value = process.env[key];
		if (key === "SESSION_SECRET") return value?.split(",").map((s) => s.trim());
		return value;
	},
});
```
Exercise request-scoped code through the real request runtime rather than a hand-built event:
```ts
import { commitEventResponse, createRequestEvent } from "@solidjs/web";
import { provideRequestEvent } from "@solidjs/web/storage";
import { expect, test } from "vitest";

async function runRequest<T>(request: Request, handler: () => Promise<T>) {
	const event = createRequestEvent(request);
	return provideRequestEvent(event, async () => {
		const result = await handler();
		const response = commitEventResponse(new Response("ok"), event);
		return { result, response };
	});
}

test("reads a session on the next request", async () => {
	const login = await runRequest(new Request("http://localhost/login"), () =>
		session.setSession({ userId: "user_1" })
	);
	const cookie = login.response.headers.getSetCookie()
		.find((value) => value.startsWith("session="))?.split(";")[0];
	const current = await runRequest(
		new Request("http://localhost/me", { headers: { cookie: cookie! } }),
		() => session.getSession()
	);
	expect(current.result).toEqual({ userId: "user_1" });
});
```
Carry the response cookie into the next request; that round trip is the contract under test. Reset modules before importing code that captured environment values at module initialization, and undo everything process-wide in `afterEach`: environment variables, fake timers, mocks, and module state.

## Asserting behavior
Assert what the user sees: visible text, roles, enabled/disabled, `aria-*` state, the URL. A test that counts effect runs or reads a signal asserts an implementation detail and breaks on a correct refactor. When the claim is itself about reactivity — "this update recomputes the total once" — turn it into evidence:
```ts
import { captureArtifact } from "@solidjs/diagnostics";
import { fireEvent, render } from "@solidjs/testing-library";
import { flush } from "solid-js";
import { expect, test } from "vitest";

import Cart from "./Cart";

test("adding an item recomputes the total once", async () => {
	const { artifact } = await captureArtifact(
		() => {
			const { getByRole } = render(() => <Cart />);
			fireEvent.click(getByRole("button", { name: "Add" }));
			flush();
		},
		{ scenario: "add-item" }
	);

	expect(artifact).toHaveNoDiagnostics();
	expect(artifact).toHaveNoWaste();
	expect(artifact).toStayWithinRerunBudget(1, { scope: "total" });
});
```
- `captureArtifact(scenario, options?)` from `@solidjs/diagnostics` runs the scenario with the diagnostics channel open and resolves to `{ artifact }`: a serializable record of every diagnostic and every re-run with its cause.
- `toHaveNoDiagnostics` fails on any coded `error` or `warn` seen during the scenario; `info` findings do not fail it. A scenario that accepts a known `info` code lists it in the artifact's `allow` option rather than dropping the assertion.
- `toStayWithinRerunBudget(max, { scope })` bounds how often a named scope may re-run. It needs the scope's `name`, so unnamed scopes cannot be budgeted.
- `toHaveNoWaste` fails on a re-run whose result was unchanged; `toHaveNoSilentHolds` fails when a write was held on async work and nothing on screen acknowledged the wait; `toStayWithinHoldBudget(ms)` bounds every hold.

The function forms are `expectNoDiagnostics(artifact)` and `expectRerunBudget(artifact, max, { scope })`, both from `@solidjs/diagnostics`. The matchers need one import in the setup file: `import "@solidjs/diagnostics/vitest";`. Attribution records are collected by default; passing `attribution: false` to `captureArtifact` makes every budget and waste assertion fail because it has no records to read.

## Common mistakes
| Symptom | Cause | Fix |
| --- | --- | --- |
| The assertion after `fireEvent` sees the old DOM | The write is staged; the batch has not landed | `flush()` after the event, before the assertion; for async sources await `resolve()` or an async query |
| `document is not defined` | The test block has no `environment`, so the file runs in Node | Set `environment: "jsdom"` (or `"happy-dom"`), or enable browser mode |
| A server test runs under jsdom | The file matches the client project's `include` | Keep `src/server/**/*.test.ts` and `src/**/*.test.tsx` disjoint |
| The session module ignores the test's `SESSION_SECRET` | The module captured the environment at import time | Set the variable, call `vi.resetModules()`, then import |
| State leaks from one test file into the next | `isolate: false` keeps module state alive | Remove the option, or reset module-level state in `afterEach` |
| `Type 'SourceAccessor<string>' is not assignable to type 'string'` | An accessor was passed where the value is expected | Call it in the attribute, `query={query()}`; type the prop `Accessor<T>` only when the child needs the function |
| The child never updates and there is no type error | `props` was destructured or copied into a local | Read `props.name` in the JSX; the checker cannot see when a read happens |
| `'Price' components don't accept text as child elements` | `VoidProps` types `children` as `never` | Remove the child, or switch to `ParentProps` if the component should render children |
| `Type 'SourceAccessor<number>' is not assignable to type 'Element'` | A signal was placed in JSX without calling it (`{quantity}`) | Add the parentheses: `{quantity()}` |
| `'input' is possibly 'undefined'` | The ref variable is read before the element exists | Declare it `let input!: HTMLInputElement` and read it from a handler or `onSettled` |
| `Module '"@solidjs/web"' has no exported member` after adding a declaration | The `.d.ts` is a global script, so its `declare module` replaces the package's types | Add `export {};`; also ensure no `.ts` file shares the declaration's name |

See also `references/components.md` for the runtime behavior behind destructured props, refs, children, and the `children()` helper.

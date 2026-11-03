# Components and JSX

This reference covers the component surface — props, events, refs, children, context, control flow, classes — and the seam where code that knows nothing about signals plugs into the graph.

It assumes the run-once model from the primer: a component function executes once, and the JSX it returns keeps running.

## Run-once model

A component is a plain function that returns renderer operations. Lowercase JSX names are native elements; capitalized names are components. The compiler emits a call to `createComponent(Component, props)`, which invokes the function **once, untracked**, so reactive reads in the component body do not subscribe the parent.

- The body runs top to bottom and returns JSX. The returned element does not exist while the body runs, so nothing in the body may depend on the DOM node.
- Each JSX expression is its own tracking scope. `{count()}` in text and `class={props.active}` in an attribute each subscribe the one DOM write they own.
- There is no virtual DOM and no second pass. Nothing re-runs the component to diff a new tree.

Consequence: any value computed in the body is a one-time snapshot. Move the computation into JSX, a memo, or a function that JSX calls.

```tsx
import { createSignal } from "solid-js";

function LineItem() {
	const [quantity, setQuantity] = createSignal(1);

	return (
		<button type="button" onClick={() => setQuantity((n) => n + 1)}>
			Quantity: {quantity()}
		</button>
	);
}
```

`LineItem` runs once. `{quantity()}` is tracked, so the text updates; the function around it does not run again.

## Props

A child receives one `props` object. A dynamic attribute compiles to a **getter** on that object:

```ts
createComponent(LineItem, {
	get quantity() {
		return quantity();
	},
});
```

The parent's expression is therefore evaluated when the child reads `props.quantity`, inside whatever tracking scope that read happens in — even though neither component function runs again.

- Never destructure the parameter. `function Card({ title })` calls the getter once in the body and freezes the child at the first value.
- Never copy a prop into a local. `const quantity = props.quantity;` is the same bug with the same consequence.
- Read `props.x` at the use site, usually inside JSX. Development warns with `[STRICT_READ_UNTRACKED]` and the component name when a body read escapes the graph.
- Props are read-only. A child changes parent state by calling a function the parent passed, from an event handler.
- Pass values, not accessors. `<Child count={count()} />` gives the child a value that updates through the getter; `<Child count={count} />` gives it a function, and the child renders that function instead of the number.
- Use `createMemo` when a derived prop needs its own identity, is read by several expressions, or should gate propagation by equality.

```tsx
import { createMemo } from "solid-js";

type Product = { id: string; name: string; price: number };

function LineItem(props: { product: Product; quantity: number }) {
	const lineTotal = createMemo(() => props.product.price * props.quantity);

	return (
		<li>
			{props.product.name} × {props.quantity} = ${lineTotal()}
		</li>
	);
}
```

```tsx
// Avoid: the copy reads the getter in the component body, once.
function LineItem(props: { product: Product; quantity: number }) {
	const quantity = props.quantity;
	return <li>{quantity}</li>;
}

// Prefer: read the prop where it is used.
function LineItem(props: { product: Product; quantity: number }) {
	return <li>{props.quantity}</li>;
}
```

Defaults and pass-through props keep tracking only through the proxy forms:

- `merge(defaults, props)` returns a live view where later sources win: `const merged = merge({ type: "button" }, props)`. A function source is treated as memo-backed, so a derived default tracks. Do not destructure the result.
- `omit(props, "label", "value")` returns a live view with keys hidden, for spreading rest props onto an element (`<input {...omit(props, "label")} />`). Keys are fixed at call time; a predicate form hides by rule.
- `ComponentProps<typeof Button>` reuses another component's props: `function IconButton(props: ComponentProps<typeof Button> & { icon: JSX.Element })`.

## Events

Pass a function to a camelCase prop such as `onClick` or `onInput`. Solid delegates supported events through the render or hydration root, so the handler runs when the browser dispatches the event and every read inside it sees current values.

- `event.currentTarget` is the element the handler was attached to. Use it, not `event.target`, when reading `value` from an input.
- Handler types come from the `@solidjs/web` JSX namespace: `JSX.EventHandler<HTMLInputElement, InputEvent>` for a named handler, `JSX.EventHandlerUnion<HTMLButtonElement, MouseEvent>` for a prop that forwards to an element attribute.
- For native listener options such as `capture` or `passive`, attach the listener yourself from a `ref` directive; there is no prop for options.

```tsx
import type { JSX } from "@solidjs/web";

function SearchField(props: { onQuery: (value: string) => void }) {
	const handleInput: JSX.EventHandler<HTMLInputElement, InputEvent> = (event) => {
		props.onQuery(event.currentTarget.value);
	};

	return <input type="search" onInput={handleInput} />;
}
```

## Refs and directives

`ref` receives the element after the JSX that creates it has been evaluated. It accepts an assignable variable, a callback, or a nested array of callbacks (flattened recursively, invoked in order).

```tsx
function SearchInput() {
	let input!: HTMLInputElement;

	return (
		<>
			<input ref={input} type="search" />
			<button type="button" onClick={() => input.select()}>
				Select query
			</button>
		</>
	);
}
```

A ref callback runs **untracked and without an owner**. Its return value is ignored. Creating an effect, a memo, or cleanup inside it produces a primitive that is never disposed (`[NO_OWNER_EFFECT]`, `[NO_OWNER_CLEANUP]`).

A directive is a function passed to `ref`; there is no separate directive syntax. The factory runs during component setup, where it has an owner, and returns the element callback. Setup that needs the element in the document belongs in `onSettled`, which runs after the first render settles and honors a returned teardown.

```tsx
import { onSettled } from "solid-js";

function listen(
	type: string,
	listener: EventListener,
	options?: AddEventListenerOptions
) {
	let element: HTMLElement | undefined;

	onSettled(() => {
		const target = element;
		if (!target) return;
		target.addEventListener(type, listener, options);
		return () => target.removeEventListener(type, listener, options);
	});

	return (next: HTMLElement) => {
		element = next;
	};
}
```

Compose several behaviors on one element with an array of callbacks: `<input ref={[(el) => (input = el), autofocus, listen("input", props.onInput)]} />`.

The server never runs ref callbacks or effects; a ref variable is `undefined` there and no listener is attached.

## Children and composition

A component accepts children only when its props type includes `children`.

- `ParentProps` makes `children` optional. Most wrappers render `props.children` directly inside their markup.
- `children(() => props.children)` resolves children once and exposes an accessor plus `toArray()`. Use it only when the component must inspect or iterate; render-through needs no helper. Read `props.children` in several places recreates them several times.
- `FlowProps<P, C>` requires `children` of exactly type `C`. Use it when the child is a render callback, for example a component that hands a value back to its children.
- A wrapper that forwards children must render them directly, not read them in the body.

```tsx
import { children, type ParentProps } from "solid-js";

function Stack(props: ParentProps) {
	const resolved = children(() => props.children);
	return <div class="stack">{resolved.toArray()}</div>;
}
```

## Context

`createContext<T>()` returns a context object that **is** its own provider component. Scope a value with `<Context value={...}>` and read it with `useContext(Context)`.

- For anything reactive — signals, stores, `[state, actions]` tuples, services — use the default-less form. Reading outside a provider throws `ContextNotFoundError`; a missing provider is a loud bug, not a silent fallback.
- A default is only for a primitive with a meaningful static fallback: theme, locale, frozen config. `undefined` counts as "not provided".
- `useContext` must be called in an owned scope: the component body or another primitive. It does not work after an `await` or inside an event handler.
- Pass a store or accessors, not a snapshot. `<CartContext value={{ count: cart.items.length }}>` freezes the count; `<CartContext value={cart}>` stays live.
- A provider creates a scoped owner, so the value is per app or per request, and nested providers replace it for their own descendants. Never use module scope for this.

```tsx
import { createContext, useContext, type ParentProps } from "solid-js";

type Theme = "light" | "dark";

const ThemeContext = createContext<Theme>("light");

function ThemeProvider(props: ParentProps<{ value: Theme }>) {
	return <ThemeContext value={props.value}>{props.children}</ThemeContext>;
}

function ThemeButton() {
	const theme = useContext(ThemeContext);
	return <button class={theme}>Save</button>;
}
```

## Control flow

`Show` renders children when `when` is truthy and `fallback` otherwise.

- `when` is tested for truthiness: `0` and `""` are falsy and show the fallback. Compare explicitly (`when={count() !== undefined}`) or use `Switch` when there are several cases.
- A bare accessor is a function and therefore always truthy: write `when={user()}`, never `when={user}`.
- Default function children receive an accessor for the narrowed value and keep their DOM while `when` stays truthy. With `keyed`, the child receives the raw value and remounts whenever its identity changes.

```tsx
import { Show, createSignal } from "solid-js";

type User = { id: string; name: string };

function Account() {
	const [user] = createSignal<User | undefined>({ id: "u1", name: "Ada" });

	return (
		<Show when={user()} fallback={<a href="/sign-in">Sign in</a>}>
			{(current) => <p>Signed in as {current().name}</p>}
		</Show>
	);
}
```

`Switch` renders the first truthy `Match` and its `fallback` when none match. Order branches from most to least specific; non-`Match` children never render.

```tsx
import { Match, Switch } from "solid-js";

function Status(props: { code: number }) {
	return (
		<Switch fallback={<p>Unknown status</p>}>
			<Match when={props.code === 200}><p>Ready</p></Match>
			<Match when={props.code === 404}><p>Not found</p></Match>
		</Switch>
	);
}
```

Lists use `For`, `Repeat`, and key functions; see `state.md` for identity, editing, selection, and windows.

Dynamic components: `dynamic` from `@solidjs/web` takes a reactive source that may resolve to a component **or a tag name** (or a promise/async iterable of either, or a falsy value for nothing) and returns a stable component. Because a source may answer with a string, one `dynamic` on a page retains the element runtime, so `dynamicComponent` from `solid-js` is the cheaper choice when the source only ever answers with a component — a tag name is a type error there.

```tsx
import { createSignal, type Component } from "solid-js";
import { dynamic } from "@solidjs/web";

const Compact: Component<{ value: string }> = (props) => <span>{props.value}</span>;
const Detailed: Component<{ value: string }> = (props) => <strong>{props.value}</strong>;

function Preview() {
	const [detailed, setDetailed] = createSignal(false);
	const Result = dynamic(() => (detailed() ? Detailed : Compact));

	return (
		<>
			<button onClick={() => setDetailed((value) => !value)}>Toggle</button>
			<Result value="Current result" />
		</>
	);
}
```

Create the dynamic component once per component instance and let the source change; creating it inside the render path recreates the subtree.

## Classes

`class` accepts a string, an object of conditional names, or a nested array that combines them.

- A string supplies the complete class value; a reactive string replaces the whole attribute.
- An object adds each key whose value is truthy and removes it when the value becomes falsy. A key may contain several space-separated class names.
- An array combines strings, objects, and other arrays, flattened recursively.

Put conditional names in the object form instead of building a string with concatenation, `filter(Boolean)`, or `join`: Solid then toggles the affected class tokens directly instead of rewriting the attribute.

```tsx
function SaveButton(props: { class?: string; active: boolean; saving: boolean }) {
	return (
		<button
			class={[
				"button",
				props.class,
				{ active: props.active, "saving muted": props.saving },
			]}
		>
			Save
		</button>
	);
}
```

## Non-Solid integration

Libraries that know nothing about signals need four things: a DOM node once it exists, a place to construct the instance once, an effect that pushes each settled value in, and a teardown.

### Ref timing

The component body runs before the returned JSX creates its elements, so a ref variable is still `undefined` there.

```tsx
import { Chart } from "chart-lib";

function OrderTotalsChart(props: { totals: number[] }) {
	let canvas!: HTMLCanvasElement;

	// Avoid: the body runs before the returned JSX creates the canvas.
	const chart = new Chart(canvas, { data: props.totals });

	return <canvas ref={canvas} />;
}
```

A ref callback runs at the moment the element is created, while the surrounding render is still being built.

### Construct once, update in an effect

`onSettled` runs after the first render settles, is not a tracking scope, and returns the teardown. `createEffect(compute, apply)` carries every later value: read the input in `compute`, hand the settled value to the library in `apply`, and never read reactive data in `apply`.

```tsx
import { createEffect, onSettled } from "solid-js";
import { Chart } from "chart-lib";

function OrderTotalsChart(props: { totals: number[] }) {
	let canvas!: HTMLCanvasElement;
	let chart: Chart | undefined;

	onSettled(() => {
		chart = new Chart(canvas, { data: props.totals });
		return () => chart?.destroy();
	});

	createEffect(
		() => props.totals,
		(totals) => chart?.update(totals)
	);

	return <canvas ref={canvas} />;
}
```

The `props.totals` read in `onSettled` is the construction-time snapshot; `onSettled` never observes later values. The effect is what makes the chart follow the data — omit it and the chart draws once and freezes.

### Web components

A custom element is a native element in JSX. Three binding forms matter:

- A plain attribute on a hyphenated tag is set with `setAttribute`, so the value becomes a string and `null`/`false` removes it. An object or array passed this way is stringified.
- `prop:name` assigns a property instead, which is what an element expecting an array or object needs. The server emits attributes and skips `prop:` bindings; the browser assigns them when it renders or hydrates.
- `onEventname` lowercases the suffix and calls `addEventListener` for that name — `onDatechange` listens for `datechange`. A name with uppercase letters or a hyphen cannot be written this way; attach it from a `ref` directive with the exact name.

Events Solid delegates (`input`, `click`, and the rest) are handled by a listener on the render root, so a custom element dispatching one of those names must set `bubbles: true`.

```tsx
function DeliveryDate(props: {
	value: string;
	holidays: string[];
	onChange: (value: string) => void;
}) {
	return (
		<date-picker
			value={props.value}
			prop:disabledDates={props.holidays}
			onDatechange={(event) => props.onChange(event.detail.value)}
		/>
	);
}
```

TypeScript does not know the tag until it is declared once. Augment the `@solidjs/web` JSX namespace, and keep `export {}` so the file stays a module:

```ts
// src/types/date-picker.d.ts
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

### Portals and foreign containers

`Portal` from `@solidjs/web` renders its children into another element (default `document.body`) while they stay in the parent's reactive scope and dispose with it. The server renders nothing for a portal, and under hydration its children render fresh once hydration settles — so async reads inside a portal start on the client. Fetch above the portal and pass the data down.

```tsx
import { Show, type ParentProps } from "solid-js";
import { Portal } from "@solidjs/web";

function AddedToCart(props: ParentProps<{ open: boolean }>) {
	return (
		<Show when={props.open}>
			<Portal>
				<dialog open>{props.children}</dialog>
			</Portal>
		</Show>
	);
}
```

`render` mounts a tree into a node that another host owns, creates the reactive root, and returns a disposer that removes the DOM, disposes the root, and drops the delegated listeners the root added. It renders fresh DOM; for markup the server already produced, use `hydrate` with the same root JSX.

```tsx
import { render } from "@solidjs/web";
import { MiniCart } from "./MiniCart";

const node = document.getElementById("mini-cart")!;
const dispose = render(() => <MiniCart />, node);

// When the host removes the region:
dispose();
```

For markup the server already produced, `hydrate(() => <App />, node)` attaches to it instead and returns the same kind of disposer; the client must render the same tree.

### Outside sources

`from(source)` adapts a callback subscription, an object with `subscribe(observer)`, or an async iterable into an async iterable that a memo returns. The memo owns the subscription: changing its inputs unsubscribes the previous one before opening the next, and disposal unsubscribes.

```ts
import { createMemo, from, type Accessor } from "solid-js";
import { stockFeed } from "./stockFeed";

export function createStock(productId: Accessor<string>) {
	return createMemo(() =>
		from<number>((next) => stockFeed.subscribe(productId(), next))
	);
}
```

- A value pushed synchronously during `subscribe` renders on the first pass; otherwise a read waits for the nearest `Loading` boundary like any async memo.
- Faster pushes coalesce, so readers see the latest value.
- On the server the memo renders the source's first value and unsubscribes; the hydrating client adopts that value and subscribes again once its section has hydrated.
- When the library hands over a `Map`, class instance, or `Date`, it arrives as one value; derive a store from it when rows must keep identity.

`enableExternalSource` is the wider tool: call it once before rendering to register an adapter for a whole external reactive system (MobX and similar). The factory receives each Solid computation's function and a `trigger`; it returns `track`, which runs the function under the external library's tracking, and `dispose`, called when the computation is disposed. Solid wraps every computation with the adapter and re-runs one when its `trigger` fires; several registrations chain, each wrapping the previous. For a library that exposes `subscribe`, `from` is the smaller tool.

### Keeping browser-only code off the server

A library that reads `window` while it is imported fails before any component code runs. `clientOnly` takes the dynamic import and returns a component that renders only in the browser: the server renders the fallback, the client keeps it through hydration, then swaps in the imported component with the props it was given. The import starts when `clientOnly` is called; pass `{ lazy: true }` to defer it to first render.

```tsx
import { clientOnly } from "@solidjs/web";

const StoreMap = clientOnly(() => import("./StoreMap"), { lazy: true });
<StoreMap fallback={<div class="map-placeholder" />} center={[51.5, 0]} />;
```

When only one call site needs the library, import it inside `onSettled` and guard the async result with a disposed flag, because the component can leave before the import resolves:

```tsx
import { onSettled } from "solid-js";

function MapPanel(props: { center: [number, number] }) {
	let container!: HTMLDivElement;

	onSettled(() => {
		let map: MapInstance | undefined;
		let disposed = false;

		import("map-lib").then(({ createMap }) => {
			if (disposed) return;
			map = createMap(container, { center: props.center });
		});

		return () => {
			disposed = true;
			map?.remove();
		};
	});

	return <div ref={container} class="map" />;
}
```

Async reads inside a `clientOnly` component start in the browser after the swap, so create the memo above the boundary and pass the result down.

## Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| A child keeps showing the first value | Parameter destructured, or the prop copied into a `const` in the body; the getter ran once | Read `props.x` inside JSX or a memo |
| Every list row is rebuilt on each change | New objects per update, so row identity changes | Keep identity stable, pass a key function, or use a store |
| `Show` renders the fallback although a value is set | `when` is checked for truthiness; `0` and `""` are falsy | Compare explicitly, or use `Switch`/`Match` |
| An effect or cleanup inside a `ref` callback never runs | The callback runs untracked and without an owner | Create it in a directive factory or in the component body |
| `window is not defined` at import | A library reads a browser global in its module body and renders on the server | `clientOnly`, or import inside `onSettled` |
| The chart draws once and never updates | Data was read in `onSettled` or in the effect's `apply` half, which do not track | Read it in the effect's compute function |
| A custom element receives a stringified object | The value went through `setAttribute` | Use `prop:name={...}` |
| A custom event handler never fires | Name case or a hyphen does not match the dispatched name, or a delegated event does not bubble | Attach the exact name from a `ref` directive; dispatch with `bubbles: true` |

See also: `references/ssr.md` for `clientOnly`, hydration, and where each line runs.

# Reactivity

This reference covers the reactive engine: where reads are tracked, how derived values and effects run, who owns them, how a diagnostic names a defect, and which reactivity-graph shape to change when a profile is slow.

## Tracking scopes

A read subscribes only when a tracking scope is running at the moment of the read. These are tracking scopes:

- Every JSX expression the compiler emits — text, attributes, `class`, `style`, and each child insertion.
- The function passed to `createMemo` and the compute (first) function passed to `createEffect`.
- The function forms of `createSignal` and `createStore` — `createSignal(() => props.value)`, `createStore(async () => api.list(), [])`.
- Store property reads, including array index and `length` reads, which subscribe the reading scope to that property only.

The component body is not a tracking scope. It runs once to create signals, memos, effects, and DOM nodes; a read there returns the current value and subscribes nothing. `props` compiles to getters, so `props.x` is fresh at the place it is read — in JSX or a derived function — but `const x = props.x` in the body snapshots it.

```ts
import { createSignal } from "solid-js";

const [quantity, setQuantity] = createSignal(1);
const subtotal = () => quantity() * 10; // reads where JSX calls it
```

Use `untrack` when the snapshot is deliberate. It suppresses tracking without suppressing errors or async settlement.

```ts
import { untrack } from "solid-js";

const initialQuantity = untrack(quantity);
```

An untracked read in a component or effect body reports `[STRICT_READ_UNTRACKED]` in development. The repair is always to move the read, not to copy the value: call a derived function from JSX, or read the value inside a memo or effect compute function.

## Signals

`createSignal(value, options?)` returns `[get, set]` typed `Signal<T>`. Call the getter; the setter accepts a value or an updater.

```ts
import { createSignal, type Accessor, type Setter } from "solid-js";

const [count, setCount] = createSignal(0);
const value: Accessor<number> = count;
const write: Setter<number> = setCount;

setCount(1);
setCount((current) => current + 1);
```

- The updater receives the staged value, including a write made earlier in the same event. Prefer it whenever the next value depends on the previous one; `setCount(count() + 1)` reads the committed value and collides with another staged write.
- `options.equals` controls notification. The default is reference equality; `false` notifies on every write; a comparator such as `(a, b) => a.id === b.id` stops propagation when the content matches.
- `options.name` is the only way a diagnostic, attribution table, or `[why-run]` group can name the signal.
- The function form `createSignal(fn, options?)` is a writable derivation: `fn` recomputes from its tracked inputs, and a setter call places a local override until the next recompute. This replaces a copied value plus an effect; see `state.md` for nested drafts.
- Never call `createSignal` inside an event handler, promise callback, or ref callback. There is no owner, so nothing survives or disposes the primitive; create it in setup and drive it from the handler.

To store a function as the value rather than as an updater, wrap it: `setHandler(() => next)`.

## Derived values

A plain function is the default derived value. It has no node and no cache; it reads its inputs in whatever tracking scope calls it, so it cannot be stale independently of them.

```tsx
const total = () => subtotal() * (1 - discount());
```

Use `createMemo` when several readers share the result, when the computation is expensive, or when its equality gate should stop propagation downstream.

```ts
import { createMemo } from "solid-js";

const subtotal = createMemo(() => quantity() * price);
const discount = createMemo(() => (discountCode() === "SAVE10" ? 0.1 : 0), {
	name: "discount",
});
const total = createMemo(() => subtotal() * (1 - discount()), { name: "total" });
```

- A memo caches its result and compares by reference. For a returned object or array that is often equal in content, pass `equals`; without it, every reader runs for nothing and development reports `[UNSTABLE_MEMO_OUTPUT]`.
- A memo's scope is its tracked reads. Reading a whole store (`memo(() => cart)`) or spreading it subscribes to every property, so any unrelated edit re-runs the memo; read the properties the calculation needs.
- A memo function must not write. A write inside a memo throws `[REACTIVE_WRITE_IN_OWNED_SCOPE]`. The value you wanted to write is a derived value — return it.
- An async memo is read as its settled `T`; first-load and pending behavior belong to `async.md`. Do not read it in a component body.
- Give every memo under investigation a `name`; an unnamed memo prints as `computed` in every report.

## Effects

An effect is the end of the graph: a settled reactive value driving something Solid does not own — a storage write, a chart, a subscription, a browser API without a declarative JSX form. It is not a place to keep two pieces of state in step.

`createEffect(compute, apply, options?)` takes two functions.

```ts
import { createEffect } from "solid-js";

createEffect(
	() => props.productId,
	(id) => {
		const source = new EventSource(`/stock/${id}`);
		source.onmessage = (event) => setStock(Number(event.data));
		return () => source.close();
	}
);
```

- `compute` runs tracked and returns a value. It is the dependency list: a signal read only in `apply` never re-runs the effect. Return an object or tuple when several inputs must cross the boundary.
- `apply` receives that value and the previous value, runs untracked, and performs the imperative work after the update has landed and the DOM reflects it.
- Cleanup runs before the next `apply` and when the owner is disposed. Return a cleanup function or `undefined` — nothing else. A setter returns its value, so brace the call: `(value) => { setDraft(value); }`.
- `defer: true` skips the first `apply` run, for effects that persist state and should not write the seed back.
- An effect that writes a source feeding its own inputs costs an extra flush on every change and reports `[EFFECT_WRITES_OWN_SOURCE]`. The written value is a function of the effect's inputs, so it belongs in a memo, or the normalization belongs where the source is written.
- An effect that emits a value derived from its input should be a memo. An effect copying one signal into another is derived state kept one flush late and reports `[EFFECT_RELAY_TEAR]`.

One function that both reads and acts is the wrong shape:

```ts
import { createEffect, createSignal } from "solid-js";

const [quantity] = createSignal(1);

// Avoid: one function that reads and acts — [MISSING_EFFECT_FN]
createEffect(() => {
	localStorage.setItem("cart:quantity", String(quantity()));
});
```

Split the read into `compute` and the write into `apply`. If the function only computed a value, you wanted a memo or a plain function.

## Scheduling and batching

Writes are staged, then applied together in a microtask after the current synchronous code finishes. Several writes in one handler commit once, so readers never observe the intermediate states.

A read immediately after a write sees the old value:

```ts
import { createSignal } from "solid-js";

const [quantity, setQuantity] = createSignal(1);
setQuantity(3);
quantity(); // 1 until the batch lands
```

Application code should derive from the write instead of reading it back. Two callers need the drain:

```ts
import { flush } from "solid-js";

setQuantity(3);
flush();
quantity(); // 3
```

- `flush()` applies the staged queue synchronously; `flush(fn)` runs `fn` with synchronous scheduling and drains when it returns. Tests call it after firing an event, before asserting.
- `flush()` does not resolve async work; a memo waiting on a promise stays pending.
- Never call `flush()` inside an `action` body or an `onSettled` callback; the queue is already draining. Development throws `[FLUSH_IN_ACTION]`, and `flush()` from an effect callback is a no-op reported as `[FLUSH_IN_EFFECT_CALLBACK]`.
- To keep one write out of another update's hold, call `onFlush` from the event handler instead of flushing early:

```ts
import { onFlush } from "solid-js";

const select = (id: string) => {
	onFlush(() => setOpen(false));
	props.onSelect?.(id);
};
```

`onFlush` runs once after the pending flush, in the same microtask checkpoint. Its write is its own update unless it also derives from the held work. `queueMicrotask` is not a substitute: scheduled before the frame's first write, it runs before that flush and joins it. Calling `onFlush` in a component body or computation reports `[ON_FLUSH_IN_OWNED_SCOPE]`; use `onSettled` there.

## Ownership

Every memo, effect, cleanup, and boundary belongs to the owner current when it was created. A component is an owner. Disposing the component disposes everything it created: subscriptions drop, cleanups run, memos and effects stop. That is why setup created in a component body needs no manual teardown.

- `onSettled(callback)` is the lifecycle primitive. It runs once after the owner's first render and pending async reads settle; return a cleanup to pair setup with teardown. Reads inside it are untracked.
- `onCleanup(fn)` registers disposal only. In application code it is rare; use it for a resource started in a primitive body where there is no post-render setup. It cannot be used inside `onSettled` or a tracked effect callback — return the cleanup instead.
- Primitives must be created during setup: in a component body or in another primitive called from it. One created in an event handler, promise callback, or ref callback has no owner; it runs for the life of the page and reports `[NO_OWNER_EFFECT]`, `[NO_OWNER_CLEANUP]`, or `[NO_OWNER_BOUNDARY]`. If it must start on an event, create it in the body and gate it on a signal.
- `onSettled` and effect callbacks may not create signals, memos, or effects (`[PRIMITIVE_IN_FORBIDDEN_SCOPE]`); create them in the body.
- `createRoot(dispose => ...)` creates an owner by hand and returns its disposer. Reserve it for tests of primitives and for integrations that host Solid reactivity outside a component. Application state shared between components belongs in context, never in a module-scope root.

```ts
import { onSettled } from "solid-js";

onSettled(() => {
	const id = setInterval(tick, 1000);
	return () => clearInterval(id);
});
```

## Custom primitives

A custom primitive packages owned setup into a `createX` function. It is called in a component body or in another primitive called from one — never from an event handler or a later callback.

```ts
import { createSignal, onCleanup } from "solid-js";

export function createDebouncedSignal(initial: string, ms: number) {
	const [value, setValue] = createSignal(initial);
	let timer: ReturnType<typeof setTimeout> | undefined;

	const setDebounced = (next: string) => {
		clearTimeout(timer);
		timer = setTimeout(() => setValue(next), ms);
	};

	onCleanup(() => clearTimeout(timer));

	return [value, setDebounced] as const;
}
```

Rules for the contract:

- **Accept accessors for inputs that change.** A plain parameter is a one-time read. Use `MaybeAccessor<T>` and unwrap it inside a tracking scope.

```ts
import type { Accessor } from "solid-js";

export type MaybeAccessor<T> = T | Accessor<T>;

export function access<T>(value: MaybeAccessor<T>): T {
	return typeof value === "function" ? (value as Accessor<T>)() : value;
}
```

- **Return accessors, not values.** `return matches;` lets the caller's JSX subscribe; `return matches();` freezes the boolean and reports `[STRICT_READ_UNTRACKED]`. Return a store proxy as it is — it is already a live view.
- **Use a tuple for a signal with extra behavior** (`[value, setter] as const`); use an object of accessors and actions for several values.
- **Register teardown where the setup is.** `onCleanup` for something started in the body; a function returned from `onSettled` or from an effect's `apply` for something started there.
- **Split browser setup correctly.** `onSettled` for a one-time read of browser state; `createEffect` when the input can change and the instance must be re-created. Neither phase runs on the server.
- **Return an async memo as you would a sync one.** The caller's nearest `Loading` boundary handles the wait; nothing about the primitive is async-specific.
- **Guard build-time branches with `isServer` from `@solidjs/web`.** It is a constant, not a runtime probe.
- **Capture an owner for post-await creation.** `getOwner()` in the body, then `isDisposed(owner)` and `runWithOwner(owner, ...)` in the callback.

A browser listener primitive takes its input as an accessor and re-creates the subscription when the input changes:

```ts
import { createEffect, createSignal } from "solid-js";
import { access, type MaybeAccessor } from "./access";

export function createMediaQuery(query: MaybeAccessor<string>) {
	const [matches, setMatches] = createSignal(false);

	createEffect(
		() => access(query),
		(current) => {
			const media = window.matchMedia(current);
			setMatches(media.matches);
			const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
			media.addEventListener("change", onChange);
			return () => media.removeEventListener("change", onChange);
		}
	);

	return matches;
}
```

The effect function is browser-only, so the server renders the initial `false` and hydration updates it. Use `onSettled` instead when the input never changes and there is only one subscription to create.

A primitive that syncs a store to storage reads storage after render and writes it at the boundary:

```ts
import { createEffect, createStore, deep, onSettled } from "solid-js";

const STORAGE_KEY = "cart:draft";

export function createCartDraft() {
	const [cart, setCart] = createStore({ items: [] as CartItem[] });

	onSettled(() => {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved) {
			setCart((draft) => {
				draft.items = JSON.parse(saved).items;
			});
		}
	});

	createEffect(
		() => JSON.stringify(deep(cart)),
		(json) => localStorage.setItem(STORAGE_KEY, json),
		{ defer: true }
	);

	return [cart, setCart] as const;
}
```

`deep` subscribes the compute function to every level of the store; `defer: true` keeps the empty seed out of storage.

## Reading a diagnostic

Development builds print one entry per finding: a stable bracketed code, the repair sentence, the owner chain that produced it, and the source position of the nearest located node.

```
[STRICT_READ_UNTRACKED] Reactive value read directly in <LineItem> will not update.
Move it into a tracking scope (JSX, a memo, or an effect's compute function).
  in <App> › <Cart> › <LineItem>
  at src/components/LineItem.tsx:12:5
```

- `in` is the owner chain, root downward. Components print as `<Name>`; computations print their `name` option or `effect`/`computed`/`signal`.
- Severity is the kind of finding: an `error` throws and halts execution; a `warn` logs and the code still runs, structurally wrong or expensive; an `info` never reaches the console and is delivered on the diagnostics channel.
- The first report of each code appends a footer with the code's page and the packaged repair guide. Treat the first occurrence as the one to fix.
- Every code describes a real defect or cost. Do not suppress one; change the code shape it names.

| Group | Code | Reading |
| --- | --- | --- |
| Reads | `STRICT_READ_UNTRACKED` | A reactive value was read in a component or effect body with nothing tracking it; move the read into JSX, a memo, or an effect compute function. |
| Reads | `PENDING_ASYNC_UNTRACKED_READ` | A pending async value was read outside a tracking scope; read it in JSX under a `Loading` boundary. |
| Writes | `REACTIVE_WRITE_IN_OWNED_SCOPE` | A setter or invalidation ran in a component body or computation; write from an event handler, `onSettled`, or an `action`. |
| Writes | `ACTION_CALLED_IN_OWNED_SCOPE` | `action()` was invoked from a component body or computation; call it from an event handler. |
| Writes | `FLUSH_IN_EFFECT_CALLBACK` | `flush()` was called from an effect callback, where the drain is already running; remove it. |
| Writes | `SERVER_WRITE` | A setter ran during a server render; the write is inert and will throw, so derive the value from an async source instead. |
| Leaks | `NO_OWNER_EFFECT` | An effect was created with no current owner and will never be disposed; create it during setup. |
| Leaks | `NO_OWNER_BOUNDARY` | A boundary was created without an owner; create it during setup. |
| Leaks | `NO_OWNER_CLEANUP` | `onCleanup` ran without an owner and will never run; register it during setup or return it from `onSettled`. |
| Async placement | `ASYNC_OUTSIDE_LOADING_BOUNDARY` | An async computation is read with no `Loading` above it, so the root mount waits; add a boundary around the reading region. |
| Async placement | `LOADING_ON_OUTSIDE_HOLD` | `Loading on` changed, but the same data is also read outside the boundary and holds the frame; move every reader inside. |
| Graph size | `HUGE_FAN_OUT` | One change reached 2,000 live subscribers (250 while attribution runs); key per-row flags by id or use a projection. |
| Graph size | `HUGE_FAN_IN` | One computation tracked 2,000 sources; read only the properties the calculation uses. |
| Cost | `HOT_SCOPE_RERUNS` | One scope re-ran 120+ times in a second; share the result or narrow its dependencies. |
| Cost | `HOT_SCOPE_TIME` | One scope spent 8ms+ of self time in a second; move the work behind a memo or out of the update path. |
| Cost | `WIDE_SCOPE_DEPS` | A scope subscribed to 200+ sources; read less of the store or split the derivation. |
| Cost | `WASTED_RECOMPUTE` | Most of a scope's runs produced an unchanged value; add an equality boundary on a primitive or stop memoizing a cheap expression. |
| Cost | `ASYNC_WATERFALL` | Two or more (reported at three) requests ran in sequence; derive independent requests from inputs already available. |
| Cost | `UNSTABLE_MEMO_OUTPUT` | A memo returned a new-but-equivalent container four runs in a row; return the same reference, pass `equals`, or keep the data in a store. |
| Cost | `EFFECT_WRITES_OWN_SOURCE` | An effect's write feeds back into its own inputs; make the written value a memo or normalize at the source. |
| Cost | `EFFECT_RELAY_TEAR` | A reader ran twice for one change because an effect relayed it; derive the value and delete the effect. |
| Cost | `IMMUTABLE_UPDATE_IN_STORE` | A store path was replaced with a mostly identical copy; mutate the draft or use `reconcile`. |
| Cost | `UNSTABLE_LIST_IDENTITY` | `For` recreated rows for equivalent items; keep object identity or pass a stable key. |
| Cost | `GRAPH_GROWTH` | The live graph grew 1.25× across three visits to a route; something each visit creates outlives navigation. |
| Responsiveness | `SILENT_HOLD` | A write was held 100ms+ (reported at 200ms) with no `isPending`, `latest`, optimistic value, or `affects` on screen; add feedback, never remove the hold. |
| Responsiveness | `LONG_HOLD` | An acknowledged hold's tail ran 500ms+ (warning at 1000ms); add a `Loading on` boundary or speed up the source. |
| Responsiveness | `UNTRACKED_ASYNC_HANDLER` | A handler awaited 100ms+ past its frame with no write before the `await` and no `action`; use an action or an optimistic write. |
| Responsiveness | `ABANDONED_FLIGHTS` | One async source abandoned three flights in a second — the request-per-keystroke signature; debounce the input. |
| Responsiveness | `FALLBACK_FLASH` | A `Loading` fallback showed for under 150ms; do not put a boundary around a fast read. |
| Responsiveness | `STACKED_HOLDS` | Three interactions were waiting behind one source when it committed; give each interaction its own feedback. |
| Responsiveness | `OPTIMISTIC_REVERTED` | An optimistic value the screen showed was replaced; write the expected result before `yield` and refresh after settle. |
| SSR | `SSR_RENDER_ERROR_CONTAINED` | A server render error was routed by a boundary; inspect whether it used the fallback, the client, or failed. |
| SSR | `SSR_BOUNDARY_WATERFALL` | A boundary needed 3+ render passes from sequential async waits; parallelize the reads or narrow the boundary. |
| SSR | `SERVER_ERROR_SANITIZED` | An error was replaced with the generic error on the wire; throw `respond(...)` or mark errors you own with `markSafeError`. |
| SSR | `SSR_STREAM_ABANDONED` | The response stream was cancelled or its sink failed with fragments pending; do not close the response early. |

`[REACTIVITY_HALTED]` is separate from the groups above: an uncaught error escaped every boundary and scheduling stopped, so wrap any subtree that can throw in an `Errored` boundary.

## Finding why it ran

Give the scopes you care about `name` options first; every table and chain refers to nodes by name. Then record.

```ts
import { createMemo, createStore } from "solid-js";
import { attribution, costs, feedback, subscriptions, why } from "solid-js/attribution";

const [cart] = createStore(initialCart, { name: "cart" });
const total = createMemo(() => sum(cart.items), { name: "total" });

const release = attribution.enable();
// reproduce the interaction, then:
for (const event of why(total)) {
	console.log(event.nodeName, event.causes, `${event.selfMs}ms`);
}
console.log(subscriptions(total));
console.table(costs().scopes);
console.table(feedback().flights);
```

- `attribution.enable(options?)` takes a hold and returns its release; each hold may open a fresh measurement window. `disable()` tears the engine down for every holder; release your own hold instead.
- `why(scope)` returns re-run history: the root write, the dependency that changed, the interaction it traces to, and self time.
- `subscriptions(scope)` lists the current dependency names. Compare them to what the calculation actually uses; a whole-store read shows up here.
- `costs().scopes` ranks scopes by self time, with `wastedMs` for runs whose result did not change; `costs().writes` ranks root writes by downstream re-run time.
- `feedback()` folds holds and re-runs into `sources`, `interactions`, `navigations`, `flights`, and `fallbacks`. A high `flights.abandoned` count is a request storm; a low-duration `fallbacks` entry is a flash.
- While attribution is enabled, the same chains print as collapsed `[why-run]` console groups, one per re-run, naming the cause chain and dependency changes.
- `enablePerformanceTracks()` from `@solidjs/web/performance-tracks` paints those records on the browser Performance panel; release the hold it returns when done.
- Attribution and diagnostics exist in development and observe builds only. Production strips them; measure production timing with the browser profiler, and measure causes here.

## Performance

Measure before changing. Record one interaction in the Performance panel to see where time went, then enable attribution to see which scope ran and what made it run. A component function high in a profile is its first and only run — components do not re-render, so do not hunt for a re-render to skip.

### Expensive derivations

A plain function runs once per reader; a memo runs once per change and hands the cached value to every reader. Make the shared or expensive derivation a memo, then put the equality boundary where the value is a primitive.

```ts
import { createMemo } from "solid-js";

const needle = createMemo(() => query().trim().toLowerCase(), { name: "needle" });
const visible = createMemo(
	() => products.filter((product) => product.name.toLowerCase().includes(needle())),
	{ name: "visible" }
);
```

Type a trailing space and `needle` recomputes to the same string and stops; `visible` and the rows do not run. A filter returns a new array on every run, so the equality gate belongs on `needle`, not on `visible`. Pass `equals` when a memo must return a container that is often equal in content.

### Lists

`For` keys rows by object identity. Handing it new objects per update disposes and recreates every row, losing DOM state, focus, selection, and animations, and reports `[UNSTABLE_LIST_IDENTITY]`.

```tsx
import { For } from "solid-js";
import { ProductCard } from "./ProductCard";

// Avoid: a fresh wrapper object per row rebuilds every row
<For each={visible().map((product) => ({ product, inCart: cartIds().has(product.id) }))}>
	{(row) => <ProductCard product={row.product} />}
</For>;
```

Prefer the store's objects and read per-row state by key, or pass `keyed={(item) => item.id}`. A selection signal read by every row makes one click re-run all rows (`[HUGE_FAN_OUT]`); keep selection in a store keyed by id and read `selected[product.id]`. Use `Repeat` for a fixed-size positional window; use `For` whenever rows can reorder.

### Waterfalls

Derive each request from inputs already available so independent requests start together, and join genuine dependencies on the server. Three sequential flights of 50ms or more report `[ASYNC_WATERFALL]` while attribution runs. Component nesting does not order requests; only data dependency does.

### Code splitting

Split at the boundary between what the first page shows and what it does not.

```tsx
import { Loading, lazy } from "solid-js";

const Account = lazy(() => import("./account/Account"));

<Loading fallback={<AccountSkeleton />}>
	<Account />
</Loading>;
```

The dynamic import starts on first render and the boundary shows the skeleton while the chunk loads. Call `Account.preload()` from a hover or focus handler to start earlier. `lazyModule(() => import("./routes"))` is the same cached import for a module that is not a component, with the same `.preload()`. With the router, split at the route and enable `preloadLinks: intentPreload()` from `@solidjs/router`. Do not split the header, the first grid, or anything else the first paint needs — a chunk is a round trip.

### Streaming

With `ssr: true`, the synchronous shell is sent first and each `Loading` boundary streams in when its content settles. An async read with no boundary above it holds the whole shell, so wrap the region that depends on it.

```tsx
<main>
	<Header />
	<Loading fallback={<GridSkeleton />}>
		<ProductGrid products={products()} />
	</Loading>
</main>
```

Pass `deferStream: true` to a memo only when the first HTML must contain that data, for a crawler or a link preview; otherwise the shell waits for it and streaming is lost.

### Stores at scale

A store does not create tracking nodes for the whole object up front. The proxy creates a node for a property the first time a tracking scope reads it, so off-screen rows cost nothing until they render.

```ts
import { createProjection, createStore } from "solid-js";

const [catalog] = createStore(async () => getProducts(), [] as Product[], {
	name: "catalog",
});

const inCart = createProjection<Record<string, boolean>>(
	(draft) => {
		for (const key of Object.keys(draft)) delete draft[key];
		for (const item of cart.items) draft[item.id] = true;
	},
	{},
	{ name: "inCart" }
);
```

The async store reconciles by `id`, so a refetch notifies only rows whose fields changed; the projection gives each row its own key, so adding a cart item re-runs one row. The alternative — every row calling `cart.items.some((item) => item.id === product.id)` — subscribes all rows to the collection. For a record map whose values are replaced wholesale, `createStore(value, { shallow: true })` tracks root keys and stores each value by reference, avoiding per-field nodes.

## Common mistakes

| Mistake | Consequence | Fix |
| --- | --- | --- |
| Reading a signal in the component body | One-time snapshot; `[STRICT_READ_UNTRACKED]` | Read in JSX, a memo, or an effect compute function. |
| Writing `{count}` instead of `{count()}` | Renders the function, or a type error; never updates | Call the accessor at the read site. |
| Destructuring props or copying one to a `const` | The getter runs once and the child freezes | Keep `props` whole and read `props.x` where used. |
| An effect copying one signal into another | Readers update one flush late; `[EFFECT_RELAY_TEAR]` | Derive the value or use a writable derivation. |
| Reading a signal right after setting it | Sees the old value until the microtask batch lands | Use the updater form, derive, or `flush()` in a test. |
| Creating an effect or primitive in a handler or ref callback | No owner, never disposed; `[NO_OWNER_EFFECT]` | Create it in setup and gate it on a signal. |
| Reading a second dependency in `apply` | Untracked, so the effect never re-runs for it | Read every input in `compute` and pass the values across. |
| Suppressing or working around a diagnostic | The defect remains and surfaces later as stale or slow UI | Change the shape the code names. |
| Memoizing every cheap expression | Extra graph nodes and comparisons with no benefit | Use a plain function until sharing, cost, or an equality gate justifies a memo. |
| Measuring timing in a development build | Attribution and diagnostics inflate every number | Profile the production bundle; use development for causes. |

See also `references/components.md` for the JSX and component surface where these primitives are consumed.

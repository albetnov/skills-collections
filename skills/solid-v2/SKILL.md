---
name: solid-v2
description: "Solid 2.0 conventions and best practices. Use when writing, reviewing, or debugging Solid 2 code: signals, memos, effects, stores, async data, Loading/Errored boundaries, SSR and hydration, Solid Router, server functions, forms, lists, TypeScript, or tests."
---

# Solid 2.0

## The model

Solid has no re-render. A component runs once: it creates its signals, memos, and DOM nodes, and returns. JSX expressions, memo functions, effect compute functions, and the function forms of `createSignal` / `createStore` are **tracking scopes** — a read inside one subscribes it, a read anywhere else (including the component body) is a snapshot. Updates are staged and applied together in a microtask batch, and the JSX compiler wires each expression directly to the DOM node it writes, so an update touches exactly the expressions that read it. Everything below follows from those three facts.

## Non-negotiables

1. Read reactive values inside JSX, a memo, or an effect's compute function — or in a plain function those three call. A read in the component body is a one-time snapshot; `untrack(fn)` is the deliberate form.
2. Keep `props` whole and read `props.x` where it is used. Never destructure parameters. Pass values, not accessors: `<Child count={count()} />`.
3. `createEffect(compute, apply)` takes two functions. `compute` is tracked and returns a value; `apply` receives it untracked and returns a cleanup or `undefined`. One argument is an error. Read every dependency in `compute`.
4. Never write a signal or store from a memo, an effect's compute function, or a component body. Write from event handlers, `onSettled`, or an `action`.
5. Writes land in a microtask batch. A read right after a write sees the old value. Use the updater form when the next value depends on the previous one. Tests call `flush()`.
6. Derive, do not sync. A plain function is the default derived value; use `createMemo` when several readers share it, it is expensive, or its equality gate should stop propagation. A writable derivation (`createSignal(() => props.value)`, `createStore(fn, seed)`) replaces a copy-plus-effect.
7. Stores are written through the setter's draft: `setCart((draft) => { draft.items[0].quantity = 2; })`. No path setters, no `produce`, no direct writes to the proxy.
8. Async work is a value: return a promise from a memo and read the result as `T`. `Loading` covers the first load; later updates are held with the old content visible. Acknowledge holds with `isPending` and `latest`. Read every reactive input before the first `await`.
9. State lives local to a component, in a context provider, in the URL, or on the server. Module-scope signals and stores are wrong under SSR: one module instance is shared by every request.
10. Browser-only work goes in an effect function or `onSettled`. The server runs neither. The first client render must match the server markup; keep `Math.random()`, `Date.now()`, `crypto.randomUUID()`, and browser reads out of structural JSX.
11. Lists keep row identity: pass the same objects (store-backed) or a stable key. Rebuilding items per update loses focus, selection, and animations.
12. Server functions are `"use server"` functions. Validate and authorize every argument inside the body; a caller can reach the function directly. Throw `respond(...)` for failures the client should see; return or throw `redirect(...)` / `reload(...)`.

## Canonical shapes

Signal plus a derived function — read in JSX, derive with a plain function:

```tsx
import { createSignal } from "solid-js";

function Counter() {
	const [count, setCount] = createSignal(0);
	const doubled = () => count() * 2;
	return (
		<button onClick={() => setCount((n) => n + 1)}>
			{count()} / {doubled()}
		</button>
	);
}
```

Two-function effect with cleanup — `compute` is the dependency list, `apply` owns the imperative work:

```tsx
import { createEffect, createSignal } from "solid-js";

const [stock, setStock] = createSignal(0);

createEffect(
	() => props.productId,
	(id) => {
		const source = new EventSource(`/stock/${id}`);
		source.onmessage = (event) => setStock(Number(event.data));
		return () => source.close();
	}
);
```

Store draft write — mutate the one property, never rebuild the collection:

```tsx
import { createStore } from "solid-js";

const [cart, setCart] = createStore({ items: [] as CartItem[] });
setCart((draft) => {
	const item = draft.items.find((i) => i.id === id);
	if (item) item.quantity += 1;
});
```

Async memo plus boundary — the read is a plain `T` under `Loading`:

```tsx
import { createMemo, Loading } from "solid-js";

const product = createMemo(() => getProduct(props.id));

<Loading fallback={<ProductSkeleton />}>
	<h1>{product().name}</h1>
</Loading>;
```

## Where state lives

| Kind of state | Home | Rule |
| --- | --- | --- |
| Local | Signal or store in the rendering component | Default. Disposed with the component. |
| Shared subtree | Store in a context provider, read via `useContext` | Only when a second component needs it. |
| Shareable navigation state | Search params | When a copied link should reproduce the view. |
| Authoritative data | Server functions / `query`, client holds a view | When the server must decide. |

## Red flags

- Parameters destructured (`function Card({ title }: Props)`) or a prop copied into a `const`.
- Reactive read in the component body.
- One-argument `createEffect(fn)`.
- An effect copying a signal into another signal.
- `setStore("path", value)` or a path setter of any shape.
- `cart.items.push(...)` on the proxy instead of the setter's draft.
- `.map`/spread rebuilding a collection inside a store setter.
- A primitive or effect created in an event handler or a ref callback.
- A reactive read after `await` inside an async memo.
- `on={accessor}` on `Loading` instead of `on={accessor()}`.
- `Loading` wrapped around the whole page.
- A loading flag, request counter, and manual abort controller standing in for an async memo.
- Module-scope signal or store.
- `Math.random()` / `Date.now()` deciding structure.
- `form action={coreAction}` — `action` from `solid-js` is not a form action.

## References

Read the branch that matches the task.

| Read when | File |
| --- | --- |
| Setting up or reviewing a project: file layout, imports, naming, state placement, tooling, anti-patterns, or a known 2.0 failure mode | [conventions.md](references/conventions.md) |
| A value does not update, an effect runs at the wrong time, ownership/cleanup is unclear, a diagnostic fires, or a profile is slow | [reactivity.md](references/reactivity.md) |
| Writing props, children, refs, context, control flow, dynamic components, or driving non-Solid code | [components.md](references/components.md) |
| Choosing where state lives, updating nested state with a store, projecting data, or rendering/editing/selecting lists | [state.md](references/state.md) |
| A promise, loading/error boundary, held update, isPending/latest, or data-fetching pattern | [async.md](references/async.md) |
| Adding pages, links, search params, route data, preloads, guards, server functions, mutations, or forms | [routing-and-server.md](references/routing-and-server.md) |
| Keeping code safe under SSR or reading a hydration warning | [ssr.md](references/ssr.md) |
| Typing props, children, accessors, stores, events, refs, custom elements, or writing component/browser/server tests | [typescript-and-testing.md](references/typescript-and-testing.md) |

Read `conventions.md` before creating files or reviewing a diff.

# State and stores

This reference covers the state half of a Solid 2 app: which of the five homes a value belongs in, how a store is read and written, and how a list keeps row identity across updates.

## Five homes

| Kind | Storefront example | Home |
| --- | --- | --- |
| Local | A dialog's open flag, a hovered row | A signal or store in the component that renders it |
| Shared by a subtree | The cart, read by the header and the checkout | A store created in a provider, read through context |
| Shared by the app | The current customer, the theme | The same provider, placed at the root of `App` |
| In the URL | Search query, category, sort, page | Search parameters, read with `useSearchParams` |
| On the server | The catalog, orders, the session | Server functions; the client holds a view, not a copy |

The first three differ only in where the provider sits. The last two are not Solid state at all: the URL and the server own them, and components read them through a router primitive or a server function.

Decide in this order and stop at the first yes: should a shared link or a refresh reproduce it (search parameter); does the server own it because it comes from a database or session (server function into a memo or store, changed through an action); does exactly one component read and write it (local signal or store); do two nearby components need it (common parent, passed as props); do distant components or every page need it (provider, read with `useContext`). Lift only when a second component needs the value, and never keep state at module scope to share it.

## Local state

State created in a component is owned by that component: Solid disposes it when the component leaves the page, so every instance starts fresh.

```tsx
import { Show, createSignal } from "solid-js";
function RemoveButton(props: { onConfirm: () => void }) {
	const [open, setOpen] = createSignal(false);
	const confirm = () => {
		setOpen(false);
		props.onConfirm();
	};
	return (
		<Show when={open()} fallback={<button onClick={() => setOpen(true)}>Remove</button>}>
			<button onClick={confirm}>Confirm</button>
		</Show>
	);
}
```

Nothing else reads `open`, so nothing else should see it. If a sibling must react to it, lift it to the list component: props are reactive on their own, so lifting costs only the lines that pass the value down. Use a signal for a value replaced as a unit (a count, a selected id, a string); use a store as soon as readers need separate parts of an object or array.

## Context

Create the state once inside a provider, publish the store and its actions, and read it below with a hook.

```tsx
// src/cart.tsx
import { action, createContext, createStore, refresh, useContext, type ParentProps } from "solid-js";
import { addToCart, getCart } from "./data/cart";
type CartItem = { id: string; name: string; quantity: number };
function createCart() {
	const [cart] = createStore(() => getCart(), { items: [] as CartItem[] });
	const add = action(function* (item: CartItem) {
		yield addToCart(item.id);
		refresh(cart);
	});
	return { cart, add };
}
const CartContext = createContext<ReturnType<typeof createCart>>();

export function CartProvider(props: ParentProps) {
	return <CartContext value={createCart()}>{props.children}</CartContext>;
}

export function useCart() {
	return useContext(CartContext);
}
```

`createCart()` runs inside `CartProvider`: once per app in the browser, once per request on the server. The provider creates a scoped owner for its children and disposes the store with them, so pages come and go while the cart survives. The context object returned by `createContext` is also the provider component, and `useCart` returns the value from any descendant without a prop in between.

`createContext<T>()` with no default makes the provider mandatory: a read outside one throws `ContextNotFoundError`, and the return type is `T` with no `undefined` to narrow. Use that for reactive state; a cart that silently reads as `undefined` is found much later than one that throws at the first read. A default value is for a primitive with a meaningful fallback, such as a theme name, where a component rendered alone in a test must still work.

The provider reads `value` once, when it runs, so pass the store or accessors, never a value computed at that moment.

```tsx
// Avoid: the length is read once; every consumer receives a frozen number
<CartContext value={{ count: cart.items.length }}>

// Prefer: consumers read the store in their own tracking scopes
<CartContext value={{ cart, add }}>
```

The `Avoid` version leaves the badge at the number the provider saw at startup; in the `Prefer` version `cart.items.length` is a tracked read in the header. A nested provider of the same context replaces the value for its own subtree only; outer consumers keep reading the outer store.

## Module scope

Constants are fine at module scope: a category list, a currency formatter, and the `createContext` call itself have no per-visitor state. Signals and stores are not fine in code that runs on the server.

```ts
import { createStore } from "solid-js";
// Avoid: one store object shared by every request the process handles
export const [cart, setCart] = createStore({ items: [] as CartItem[] });

// Prefer: one store per client or per request, created when the provider runs
function createCart() {
	const [cart, setCart] = createStore({ items: [] as CartItem[] });
	return { cart, setCart };
}
```

The generated server entry imports the module once; every request renders with that same value. On the server a store setter mutates the object in place and warns `[SERVER_WRITE]`, so a write made while rendering one request is what the next request reads; the symptom is a cart that belongs to a different visitor. Without `ssr: true` a module-scope store is one store per tab and behaves, then breaks the day server rendering is enabled; create it in a provider from the start.

A module-scope store derived from a server function fails immediately, because no request event exists while the module is evaluated:

```ts
import { createStore } from "solid-js";

// Avoid: throws Cannot call server function outside of a request
export const [cart] = createStore(() => getCart(), { items: [] as CartItem[] });
```

The same line inside `createCart()` runs during a request, so `getRequestEvent()?.locals.userId` inside `getCart()` names the right customer.

## URL state

State that describes which view the user is looking at belongs in the URL: filter, sort order, page number, search query.

```tsx
import { For, createMemo, latest } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { searchProducts } from "../data/products";
export default function Search() {
	const [search, setSearch] = useSearchParams();
	const results = createMemo(() =>
		searchProducts(String(search.q ?? ""), { category: String(search.category ?? "all") })
	);

	return (
		<>
			<input type="search" value={latest(() => String(search.q ?? ""))} onInput={(event) => setSearch({ q: event.currentTarget.value })} />
			<For each={results()}>{(product) => <li>{product.name}</li>}</For>
		</>
	);
}
```

`search.q` is a reactive read like a store property, so the memo re-runs when the URL changes, including on Back. `setSearch` merges the keys it is given into the current query string and navigates without scrolling, so two handlers can set `q` and `category` without erasing each other; setting a key to `""`, `undefined`, or `null` removes it. Read a control through `latest` while its write is held, so the input shows the new value while the old results stay on screen; never use `latest` for the content itself.

Without a schema every value is a string or an array of strings. A route `search` schema parses and types them:

```ts
import * as v from "valibot";
import Search from "./pages/Search";
const route = {
	path: "/search",
	search: v.object({ q: v.optional(v.string(), ""), page: v.optional(v.pipe(v.unknown(), v.transform(Number)), 1) }),
	component: Search,
};
```

Search schemas run synchronously; a value that needs a server round trip is a query, not a search parameter. The query string is user input, so validate it again in the server function. Do not move local state into the URL: a dialog's open flag, a hovered row, or text typed before submit stays in the component, and the test is whether a shared link should reproduce it.

## Server state

Authoritative data lives in a database or a session. The client holds a view that a server function returned, and the function reads identity from the request event.

```ts
// src/data/account.ts
import { getRequestEvent } from "@solidjs/web";
import { database } from "../server/database";
export async function getCurrentUser() {
	"use server";
	const userId = getRequestEvent()?.locals.userId;
	if (!userId) return null;
	return database.customers.find(userId);
}
```

```tsx
import { Loading, Show, createMemo } from "solid-js";
import { getCurrentUser } from "../data/account";
export function Header() {
	const user = createMemo(() => getCurrentUser());
	return (
		<Loading fallback={<span />}>
			<Show when={user()} fallback={<a href="/sign-in">Sign in</a>}>{(current) => <span>{current().name}</span>}</Show>
		</Loading>
	);
}
```

`user` is a memo of a promise, not a copy of the customer. When the server changes what `getCurrentUser()` would return, the view is stale until it is re-read: `refresh(user)` after a rename, or a full navigation after sign-out. Put the memo where its readers are; a second region that needs the same user should read it through a provider next to the cart rather than call the server function again.

## Stores

`createStore(object | array)` returns a read-only proxy and a setter.

```tsx
import { createStore } from "solid-js";
type CartItem = { id: string; name: string; price: number; quantity: number };
function Cart() {
	const [cart, setCart] = createStore({
		items: [{ id: "mug", name: "Mug", price: 12, quantity: 1 }] as CartItem[],
		coupon: "",
	});
	return (
		<>
			<p>{cart.items.length} lines, coupon {cart.coupon}</p>
			<input value={cart.coupon} onInput={(event) => {
				const coupon = event.currentTarget.value;
				setCart((draft) => {
					draft.coupon = coupon;
				});
			}} />
		</>
	);
}
```

Store properties are values, not accessors: read `cart.coupon`, never `cart.coupon()`. Each property read inside a tracking scope subscribes that scope to that property, including reads through nested objects and array indexes. Here the paragraph subscribes to the array's length and to `coupon`, and the input subscribes to `coupon` again; a write to `items[0].quantity` touches neither.

The proxy creates a tracking node for a property the first time a tracked reader reads it, and only for properties that get read. Reading `cart.items[0].quantity` and `cart.items.length` produce two independent subscriptions, and a store with a thousand rows costs nothing for rows nothing reads.

Every change goes through the setter's draft. Mutate it with normal assignments and array methods; Solid applies the changes when the callback returns.

```ts
setCart((draft) => {
	draft.coupon = "SAVE10";
	const mug = draft.items.find((item) => item.id === "mug");
	if (mug) mug.quantity += 1;
	draft.items.push({ id: "cap", name: "Cap", price: 15, quantity: 1 });
});
```

Three properties changed, so three subscriptions are notified; other rows are untouched. There are no path setters and no `produce`: `setCart("coupon", "SAVE10")` does not exist and becomes a draft write.

Rebuilding a collection inside the setter destroys the identity the store exists to preserve.

```ts
// Avoid: a new object for the changed row, so For disposes and rebuilds it
setCart((draft) => {
	draft.items = draft.items.map((item) =>
		item.id === id ? { ...item, quantity } : item
	);
});

// Prefer: change the one property on the draft
setCart((draft) => {
	const item = draft.items.find((item) => item.id === id);
	if (item) item.quantity = quantity;
});
```

Run the `Avoid` version with the cursor in that row's input and the input loses focus, because the row was torn down and a new one created; every reader of the old object also runs. The `Prefer` version updates one `value` binding.

The callback may return a replacement instead of mutating. For an array, Solid writes the returned entries by index and adjusts the length, so returning `draft.items.filter((item) => item.quantity > 0)` is the natural shape for removal: the surviving items are the same objects, so their proxies and rows are kept. For an object, keys present in the returned value are written and missing keys deleted. Neither form reconciles by key, so a fresh array of new objects replaces every row by index.

Writing the proxy outside a setter does nothing: `cart.items[0].quantity = 2` neither throws nor warns, and the value does not change. If a write seems to vanish, look for a write that skipped `setCart`, including writes inside actions and handlers. Store writes are staged like signal writes, so a read on the next line sees the previous value until the batch lands.

Only plain objects, arrays, and class instances are proxied. Platform objects such as `Map`, `Set`, and `Date` are stored raw; the property holding one still tracks reassignment, but mutations inside the object are invisible, so reassign the property to a new instance through the setter when readers must update.

## Projections

A projection is a store whose value is derived: `createMemo` for object and array shapes. It returns the projected store directly, with no setter.

```tsx
import { For, createProjection, createSignal, createStore } from "solid-js";
type VisibleItem = { id: string; name: string; savedForLater: boolean };
function CartView() {
	const [cart] = createStore({ items: [] as VisibleItem[] });
	const [showAll, setShowAll] = createSignal(false);
	const visible = createProjection(
		() => cart.items.filter((item) => showAll() || !item.savedForLater),
		[] as VisibleItem[]
	);
	return (
		<>
			<button onClick={() => setShowAll((value) => !value)}>Show saved</button>
			<For each={visible}>{(item) => <li>{item.name}</li>}</For>
		</>
	);
}
```

The derive function receives a draft of the seed; it may mutate the draft or return a replacement, and a returned array is reconciled into the store by `id` (the default `key`), so surviving items keep their proxy identity and `For` keeps their rows. The seed is a complete value of the store's type — an array projection always takes one, `[]` — and the root proxy keeps its identity across recomputations.

Pass a key name when identity lives elsewhere (`{ key: "sku" }`), a key function for a composite, or `null` to match by position. The derive function may be async; readers then wait for the first result unless `seedLoadingValue: true` declares the seed as the first committed value.

Use a projection for a derived collection or object that several consumers read by row. For a derived number or string, such as a cart total, `createMemo` is lighter: one value, no per-property nodes.

## Fetch into a store

The function form of `createStore` is a projection with a setter, and it is the normal way to load server data into a store: `const [cart, setCart] = createStore(async () => api.cart())`. The request starts when the store is created, and again whenever a reactive value the function read changes. Each response reconciles into the same proxy by `id`, so records the server did not change keep their identity and their DOM. An object root may omit the seed this way; an array root takes `[]`, because there is no other way to type the rows: `createStore(async () => api.cartItems(), [] as CartItem[])`.

A `Loading` boundary covers the first response. A refetch does not bring the skeleton back: `isPending(() => cart.items)` reports the wait, and `refresh(cart)` asks the server again. A seed, when given, is a complete value, not a partial one; add `seedLoadingValue: true` to let the seed answer the first load instead of suspending.

Split the request into its own memo only when a second reader shapes the same response differently: `const response = createMemo(() => api.cart())`, then derive the store and the shaped reader from it. Without that second reader the one-line form is correct; a memo that exists for its own sake is an extra node in the graph.

## Optimistic stores

`createOptimisticStore(async () => source)` has the same draft setter, with one difference: writes made inside an `action` are tentative. They show immediately; when the action settles, Solid drops the overlay and shows what the store derives from its source.

```ts
import { action, createOptimisticStore, refresh } from "solid-js";
const [cart, setCart] = createOptimisticStore(async () => api.cart());
const setQuantity = action(function* (id: string, quantity: number) {
	setCart((draft) => {
		const item = draft.items.find((entry) => entry.id === id);
		if (item) item.quantity = quantity;
	});
	yield api.setQuantity(id, quantity);
	refresh(cart);
});
```

Call `setQuantity("mug", 3)` and the input shows 3 at once. If the server agreed, the refreshed cart replaces the tentative value with an identical one and nothing visible changes; if the request failed, the quantity returns to what the server has.

Write before the `yield`, never after it: a write made after the action settles is an ordinary store write with no overlay to remove. To keep a server-echoed row (a generated id, a timestamp), write it into the draft inside the action after the yield. `refresh(cart)` is a quiet re-ask that does not flip `isPending`; call `affects(cart)` — or `affects(cart, "items")` for one key — when the UI should show a pending state over the visible refetch.

## Writable derivations

An editable field that starts from a reactive source needs a local override, not a copy plus an effect.

```tsx
import { createSignal } from "solid-js";
function NameField(props: { value: string }) {
	const [draft, setDraft] = createSignal(() => props.value);
	return (
		<input value={draft()} onInput={(event) => setDraft(event.currentTarget.value)} />
	);
}
```

The function form derives like a memo, and `setDraft` places an override over the derived result. The override holds until a dependency of the derivation changes and produces a new value; then the field resets to the source. A copy in a plain signal plus an effect to reset it gives the same behavior one flush later, with a visible frame showing the new prop beside the old edit.

For a nested form, pass a function and a seed to `createStore` to get a writable derived store:

```tsx
import { createStore } from "solid-js";
type Address = { name: string; street: string; postalCode: string };
function AddressForm(props: { address: Address }) {
	const [draft, setDraft] = createStore(() => props.address, { name: "", street: "", postalCode: "" });
	return (
		<input value={draft.street} onInput={(event) => {
			const street = event.currentTarget.value;
			setDraft((state) => {
				state.street = street;
			});
		}} />
	);
}
```

Use a writable derivation when the local value shadows a reactive source and must reset when that source changes. Use plain state when the local value has an independent lifetime and no source to follow.

## Store utilities

| Utility | Effect | Use when |
| --- | --- | --- |
| `snapshot(value)` | Returns the plain unwrapped view, untracked | Serializing, or passing to code that must not observe the store |
| `deep(value)` | Subscribes the current scope to every reachable level, then returns the plain view | Any change anywhere in the subtree must re-run the computation |
| `reconcile(next, key?)` | Returns a setter callback that merges `next` by key | A whole list arrives fresh from the server and rows must survive |
| `{ shallow: true }` | Root keys reactive, values raw records replaced by reference | A record map whose entries are replaced wholesale, never edited |

`reconcile` returns a setter callback, so a full replacement from the server is written as `setTodos(reconcile(next))`: the proxy of every item whose key matches is kept, and only added and removed items change. A different key on a keyed store root throws `Cannot reconcile states with different identity`, so replace the whole value through the setter in that case. `snapshot` and `deep` are the sanctioned ways to hand store data to code outside the graph; a raw proxy passed to a serializer tracks reads you did not intend.

## Lists

### For maps rows with identity

`For` keeps a row when the same object comes back and disposes it when a new object appears. Everything else about lists follows from that rule.

```tsx
import { For } from "solid-js";
function CartLines(props: { items: CartItem[] }) {
	return (
		<For each={props.items} fallback={<li>Your cart is empty</li>}>
			{(item, index) => <li>{index() + 1}. {item.name}</li>}
		</For>
	);
}
```

The callback runs once per item `For` has not seen before, and its JSX is created once. `item` is the raw row; `index` is an accessor, because the same item can move without being recreated — read `index()` in the JSX expression, or it captures the first position.

| `keyed` | Callback receives | Row identity |
| --- | --- | --- |
| default / `true` | `(item, index)` — raw item, index accessor | Object reference |
| `false` | `(item, index)` — item accessor, stable number index | Position |
| `(item) => key` | accessors for both | The returned key |

A rebuilt row loses its DOM nodes, and with them focus, text selection, an in-progress CSS animation, and every signal the row component created. `[UNSTABLE_LIST_IDENTITY]` reports rows disposed and recreated for items that match field by field.

### Keep identity across a refetch

A refetch returns new objects for the same records, so a default-keyed list rebuilds every row, including the input the user is typing in. Two fixes:

```tsx
import { For, createStore } from "solid-js";
// Key by a field: the row survives, item() returns the newest object
<For each={items()} keyed={(item) => item.id}>
	{(item) => <CartLine item={item()} />}
</For>;

// Or load into a store: the objects themselves keep their identity
function CartList() {
	const [items] = createStore(async () => api.cartItems(), [] as CartItem[]);
	return <For each={items}>{(item) => <CartLine item={item} />}</For>;
}
```

Prefer the store whenever the list is edited or refetched, which is most lists: `item.quantity` becomes a fine-grained read, and a response that changes one field of one record updates one text node.

### Edit a row on the draft

```ts
import { createStore } from "solid-js";
const [items, setItems] = createStore<CartItem[]>([]);
// Avoid: a new object for the edited row
setItems((draft) => draft.map((item) => (item.id === id ? { ...item, savedForLater: true } : item)));
// Prefer: change the one property
setItems((draft) => {
	const item = draft.find((entry) => entry.id === id);
	if (item) item.savedForLater = true;
});
```

Development builds flag the `Avoid` shape as `[IMMUTABLE_UPDATE_IN_STORE]`. Add with `draft.push(item)`; remove with `draft.filter(keep)` returned from the setter, or `draft.splice(index, 1)`. Use `reconcile` only when a whole fresh tree arrives from the server.

### Filter and sort as a derivation

```tsx
import { For, createMemo } from "solid-js";
function VisibleLines(props: { items: CartItem[]; filter: "all" | "saved"; sortBy: "name" }) {
	const visible = createMemo(() => {
		const list = props.items.filter((item) => props.filter === "saved" ? item.savedForLater : true);
		return list.sort((a, b) => props.sortBy === "name" ? a.name.localeCompare(b.name) : 0);
	});
	return <For each={visible()}>{(item) => <CartLine item={item} />}</For>;
}
```

`visible()` is a new array on every change, and that is fine: the items inside are the same proxies, so `For` keeps every row and only reorders or hides them. A derived array costs a diff; a new set of objects costs a rebuild. Do not store the filtered list in a signal, where it becomes a stale duplicate. When the derived collection is large and read by several consumers, `createProjection` gives it per-row tracking, so a reader of one row does not subscribe to the whole list.

### Select a row through a store

```tsx
import { createStore } from "solid-js";
const [selected, setSelected] = createStore<Record<string, boolean>>({});
const select = (id: string) => setSelected((draft) => {
	for (const key of Object.keys(draft)) delete draft[key];
	draft[id] = true;
});

function OrderRow(props: { order: Order }) {
	return <tr class={{ selected: selected[props.order.id] }} onClick={() => select(props.order.id)}>{props.order.number}</tr>;
}
```

Every row reads only its own key, so moving the selection updates exactly two rows: the one that lost the key and the one that gained it. A signal read by every row (`selectedId() === order.id`) re-evaluates every row's class binding instead, which is invisible with dozens of rows and painful with thousands. Leave other keys in place for multi-select.

### Window a large list with Repeat

`Repeat` renders positions, not items: it creates rows from numeric indexes without diffing array items, so store reads stay fine-grained.

```tsx
import { Repeat, createSignal, type Store } from "solid-js";
function OrderHistory(props: { orders: Store<Order[]> }) {
	const ROW_HEIGHT = 32;
	const [from, setFrom] = createSignal(0);
	return (
		<ul onScroll={(event) => setFrom(Math.floor(event.currentTarget.scrollTop / ROW_HEIGHT))}>
			<Repeat from={from()} count={Math.min(50, props.orders.length - from())}>
				{(index) => <li>{props.orders[index].number}</li>}
			</Repeat>
		</ul>
	);
}
```

Rows whose index stays in range are kept when `from` moves; rows that left are disposed and new indexes are created. Each row reads its order directly from the store, so a change to one order updates one row. `Repeat` is positional: inserting in the middle shifts what every later row shows, so use `For` when rows must follow their items.

### Loading versus empty

`Loading` is the not-yet state and `For`'s `fallback` is the settled-empty state.

```tsx
import { For, Loading } from "solid-js";
<Loading fallback={<ListSkeleton />}>
	<For each={items} fallback={<li>Your cart is empty</li>}>
		{(item) => <CartLine item={item} />}
	</For>
</Loading>;
```

The skeleton shows until the first response; the empty row shows when that response held no items. A refetch brings back neither: the rows stay, and `isPending(() => items.length)` lets you dim them.

## Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `items.push(item)` does nothing | A store proxy drops writes outside its setter | `setItems((draft) => { draft.push(item); })` |
| Every row rebuilds on one edit | New objects from `map` with a spread, or a fresh array of new objects | Mutate the one property on the draft; `reconcile` or a projection for server data |
| `cart.items.length` renders once | Read in the component body, outside a tracking scope | Read it in JSX, a memo, or an effect's compute function |
| A `Map`, `Set`, or `Date` in a store never updates | Platform objects are not proxied | Reassign the property to a new instance through the setter |
| The badge keeps the startup count | A context value holding a snapshot such as `{ count: cart.items.length }` | Pass the store and accessors; read them in the consumer |
| A row loses focus or an animation mid-edit | The row was disposed and recreated | Keep the same proxy: draft edit, stable key, or a store fetch |
| A row shows the wrong index after reordering | `index()` was captured once instead of read in JSX | Read `index()` in the expression, or use `keyed={false}` when position is identity |

See also `references/routing-and-server.md` for search-param schemas and server functions.

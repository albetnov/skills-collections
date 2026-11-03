# Async

This reference covers async values in Solid 2: a promise read as a plain value, where `Loading`, `Errored`, and `Reveal` go, what a held update does to the screen, how failures and cancellation behave, and the read patterns built from those pieces. Mutations and server functions are out of scope here.

## A memo that returns a promise

Return a promise from a memo and read the result as `T`. Nothing between the request and the JSX learns that the value is async.

```tsx
import { Loading, createMemo } from "solid-js";
type Product = { id: string; name: string; description: string };

async function fetchProduct(id: string): Promise<Product> {
	const response = await fetch(`/api/products/${id}`);
	if (!response.ok) throw new Error(`Could not load product ${id}`);
	return response.json() as Promise<Product>;
}

function ProductDetail(props: { id: string }) {
	const product = createMemo(() => fetchProduct(props.id));

	return (
		<Loading fallback={<p>Loading product…</p>}>
			<h1>{product().name}</h1>
			<p>{product().description}</p>
		</Loading>
	);
}
```

- `product()` has type `Product`; do not type it `Product | undefined` and do not write `product()?.name`, and do not add a loading flag or request counter. The memo's state is the loading state.
- On the first load, a read before the answer suspends and the nearest `Loading` boundary renders its fallback in its place; after the first answer, changing `props.id` keeps the current product on screen while the next request runs, and the fallback does not return. That later case is a held update, covered below.
- A derived value (a plain function or another memo) that reads `product()` becomes pending too. It does not need to know the source was async.

Avoid: modeling the request as a signal plus an effect. That shape needs a flag for the waiting state, a counter for stale responses, and cleanup for the request. Return the promise instead.

## Passing is not reading

A component runs once, so there is nothing to suspend and re-run. Only the expressions that read the async value wait. Passing it as a dynamic prop does not read it, because the prop compiles to a getter evaluated where the child uses it.

```tsx
import { Loading, createMemo } from "solid-js";
function ProductPage(props: { id: string }) {
	const product = createMemo(() => fetchProduct(props.id));
	return <ProductLayout product={product()} />;
}

function ProductLayout(props: { product: Product }) {
	return (
		<div class="layout">
			<CategoryNav />
			<main>
				<Loading fallback={<p>Loading product…</p>}>
					<ProductDetail product={props.product} />
				</Loading>
			</main>
		</div>
	);
}
```

- `product={product()}` looks like it calls the accessor too early. It does not: the attribute is a getter, evaluated when `ProductDetail` reads `props.product.name`.
- `ProductLayout` and `CategoryNav` render immediately; only the detail pane waits. A sibling component that creates its own memo mounts at once and starts its own request.

Use this to separate two decisions that usually fight each other:

- **Where to create the value is a performance decision.** Higher in the tree starts the request earlier and lets it run alongside other work.
- **Where to block is a design decision.** Lower in the tree makes the fallback replace a smaller region.

Fetch high, block low. Neither choice changes the components in between, and the async version differs from a hard-coded value by one `Loading` element.

## Nesting and waterfalls

Requests are ordered by data dependency, not by component nesting. A child below an async read does not wait for it unless it reads that value.

```tsx
import { For, createMemo } from "solid-js";
function ProductDetail(props: { id: string }) {
	const product = createMemo(() => fetchProduct(props.id));

	return (
		<article>
			<h1>{product().name}</h1>
			<Reviews productId={props.id} />
		</article>
	);
}

function Reviews(props: { productId: string }) {
	const reviews = createMemo(() => fetchReviews(props.productId));
	return <For each={reviews()}>{(review) => <ReviewRow review={review} />}</For>;
}
```

`Reviews` sits under `product().name` in the JSX, but it reads `props.productId`, which is available immediately. Both requests start together.

A waterfall is a real dependency: the second request needs a value from the first response.

```tsx
import { createMemo } from "solid-js";

// Avoid: the catalog reads the brand response, so it waits for the brand.
const product = createMemo(() => api.product(props.id));
const brand = createMemo(() => api.brand(product().brandId));
const catalog = createMemo(() => api.brandProducts(brand().id));
```

```tsx
import { createMemo } from "solid-js";

// Prefer: both reads derive from the brandId the product response already carries.
const product = createMemo(() => api.product(props.id));
const brand = createMemo(() => api.brand(product().brandId));
const catalog = createMemo(() => api.brandProducts(product().brandId));
```

- Prefer reading an input you already have (props, route params, a signal) over reading another response. The `Avoid` catalog adds the brand request's time to the total for no data reason. When the dependency is intrinsic, remove it from the client instead of tuning it: preload the dependent read, or join both reads in one server function.
- With attribution enabled, a chain of three or more sequential flights is reported as `[ASYNC_WATERFALL]`; two-flight chains are recorded at `info` and not printed, because two steps can be genuinely sequential.

## Held updates

After a value has settled, a write to any input it depends on is held until the async work has its next answer, and everything derived from that write waits with it. The page commits together.

```tsx
import { Loading, createSignal, isPending, latest } from "solid-js";
function Dashboard() {
	const [period, setPeriod] = createSignal("2026-Q2");

	return (
		<>
			<PeriodSelect value={latest(period)} onChange={setPeriod} />
			<Loading fallback={<DashboardSkeleton />}>
				<div class={{ stale: isPending(period) }}>
					<SummaryPanel period={period()} />
					<TrendPanel period={period()} />
					<AuditPanel period={period()} />
				</div>
			</Loading>
		</>
	);
}
```

With three panels taking 200 ms, one second, and ten seconds, the write to `period` is held: every panel keeps its old content, and the content side changes together at ten seconds. The picker reads through `latest`, so it moves at once while the content waits; the page never shows the new period's summary beside the old period's audit log.

- The hold is automatic — no opt-in API and no transition wrapper, and `Loading` does not create it — and it applies to later updates only. Each panel's first load still reaches the nearest boundary.
- `isPending(source)` takes a function and answers for the reads inside it, so pass the accessor: `isPending(period)` or `isPending(results)`, not the value (`isPending(period())`). It may probe any node on the held path: the async source, a memo derived from it, a prop further down, or the signal whose write started the update; `isPending(selectedId)` in a parent is `true` while a fetch inside a child settles.
- `latest(source)` reads the value the update is moving toward; use it on controls the user touched, and keep a plain read on content, because data read through `latest` can show a new answer before the rest of the update agrees with it.
- A held update that nothing acknowledges looks like a dead click. Development reports it as `SILENT_HOLD`, naming the interaction, the write, and what it waited on. Fix it with `isPending`, `latest`, an optimistic value, or `affects`; never by removing the hold.

A write that must not join another update's hold goes through `onFlush`. Writes in the same synchronous frame are applied together, so a menu closing before a navigation that starts async work would stay open with it.

```tsx
import { createSignal, onFlush } from "solid-js";
function Menu(props: { onSelect?: (id: string) => void }) {
	const [open, setOpen] = createSignal(false);
	const select = (id: string) => {
		onFlush(() => setOpen(false)); // closes now, whatever onSelect starts
		props.onSelect?.(id);
	};
	return <button onClick={() => select("mug")}>{open() ? "Close" : "Open"}</button>;
}
```

`onFlush` runs once after the pending flush, before paint. Call it from event handlers and effect callbacks; in a component body or a computation it warns as `ON_FLUSH_IN_OWNED_SCOPE`. `queueMicrotask` is not a substitute: before the frame's first write, it runs before that flush and joins it.

## `Loading` placement and `on`

Place the boundary around the smallest region its fallback should replace, and leave controls the user needs outside it.

```tsx
import { Loading } from "solid-js";
// Avoid: one boundary around the page, so a slow request hides the picker.
<Loading fallback={<PageSkeleton />}>
	<ProductPicker value={productId()} onSelect={setProductId} />
	<ProductDetail id={productId()} />
	<Recommendations id={productId()} />
</Loading>

// Prefer: one boundary per region that should have its own fallback.
<ProductPicker value={productId()} onSelect={setProductId} />
<Loading fallback={<DetailSkeleton />}>
	<ProductDetail id={productId()} />
</Loading>
<Loading fallback={<CardSkeleton />}>
	<Recommendations id={productId()} />
</Loading>
```

Once a boundary has shown content, a later update does not bring the fallback back. Sometimes that is wrong: an account panel showing account 1 while account 2 loads is worse than a skeleton. The `on` prop is a tracked dependency list that re-arms the boundary.

```tsx
import { Loading, createMemo, createSignal, latest } from "solid-js";
function AccountPanel() {
	const [accountId, setAccountId] = createSignal("acct-1");
	const account = createMemo(() => fetchAccount(accountId()));

	return (
		<>
			<AccountPicker value={latest(accountId)} onSelect={setAccountId} />
			<Loading on={accountId()} fallback={<AccountSkeleton />}>
				<h1>{account().name}</h1>
				<AccountDetails account={account()} />
			</Loading>
		</>
	);
}
```

- `on` is tracked, so read the signal: `on={accountId()}`, never `on={accountId}`; an uncalled accessor reads nothing and no change ever re-arms the boundary. Its value is irrelevant — several inputs go in as an array: `on={[accountId(), tab()]}`.
- The fallback lands in the same frame as the change. If other content waits on the same change, the frame lands when that content is ready; the skeleton never appears beside a page the change has not reached. Pending work caused by anything `on` does not read, such as a refresh of the same account, leaves the content in place.
- Every reader of the data must be inside the boundary. A heading outside that reads the same account keeps the frame waiting on the data the boundary is about to replace, so the fallback can never appear; development reports `LOADING_ON_OUTSIDE_HOLD`. Move the outside read under the boundary.

Two valid placements: one boundary with `on` around every reader shows one skeleton and reveals the subject together; one boundary with `on` per region shows each region's skeleton as its own data lands, releasing the rest of the page from the hold.

When neither fits because a breadcrumb or sibling must stay visible, drop `on` and acknowledge the wait with `isPending` and `latest`.

For a placeholder that renders through the same UI as real data, declare a loading value instead of a fallback. A source with `loadingValue` never reaches `Loading` on its first flight, and `isPending` stays `false` until the first answer lands.

```ts
import { createMemo } from "solid-js";
const results = createMemo(() => searchProducts(query()), {
	loadingValue: [] as Product[],
});
```

The store form uses the seed as the placeholder: `createStore(async () => api.orders(), [] as Order[], { seedLoadingValue: true })`. Use `on={data()}` only when a skeleton must return on every refetch; the same-data rule applies, and most regions are kinder with the old content plus `isPending`.

## Errors

A rejection travels through the graph like a value and stops at the nearest `Errored` boundary.

```tsx
import { Errored, Loading } from "solid-js";
<Errored
	fallback={(error, reset) => (
		<section>
			<p>{String(error())}</p>
			<button onClick={reset}>Retry</button>
		</section>
	)}
>
	<Loading fallback={<p>Loading product…</p>}>
		<h1>{product().name}</h1>
	</Loading>
</Errored>;
```

- `Loading` and `Errored` handle separate states. A loading boundary does not consume errors, and an error boundary does not replace loading UI; both can guard the same region.
- An error is a graph status, not a terminal state: it clears when an input of the failed computation changes, when `refresh(source)` lands successfully, or when a `live` source reconnects and yields. `reset` re-runs the failed sources with the same inputs for when nothing upstream will change; a retry that hits the same cause shows the same error.
- While a `reset` retry is in flight, the error fallback stays on screen. To show a placeholder during the retry, put `Loading` outside `Errored` and add a value the retry button changes to `on` (an `attempt` signal incremented alongside `reset()`).
- An error thrown while rendering an `Errored` fallback is not caught by that boundary; a parent boundary can catch it. With no boundary above, the reactive system halts and development reports `[REACTIVITY_HALTED]`; nothing on the page updates again until a reload.

Keep a plain read of the value next to every `isPending` probe. An errored expression is not pending: `isPending` returns `false` and does not rethrow, so a region that reads the value only through the probe silently reports success.

```tsx
import { Errored, For, isPending } from "solid-js";
// Avoid: the only read of results is the probe, so a rejection disappears.
<Errored fallback={<p>Search failed.</p>}>
	<p class={{ stale: isPending(results) }}>Showing results</p>
</Errored>

// Prefer: the list also reads results(), so the rejection reaches Errored.
<Errored fallback={<p>Search failed.</p>}>
	<ul class={{ stale: isPending(results) }}>
		<For each={results()}>{(product) => <li>{product.name}</li>}</For>
	</ul>
</Errored>
```

## Reveal order

Independent loading regions appear in data-arrival order, which shifts layout as each lands. `Reveal` controls when sibling `Loading` boundaries show, not when their data arrives.

```tsx
import { Loading, Reveal } from "solid-js";
<Reveal collapsed>
	<Loading fallback={<DetailSkeleton />}>
		<ProductDetail id={productId()} />
	</Loading>
	<Loading fallback={<CardSkeleton />}>
		<Reviews id={productId()} />
	</Loading>
	<Loading fallback={<CardSkeleton />}>
		<Recommendations id={productId()} />
	</Loading>
</Reveal>;
```

- `sequential` is the default: slots reveal in registration order; a later slot stays on its fallback until every earlier slot is ready.
- `together` holds every direct slot until all are minimally ready, then releases them as a group.
- `natural` reveals each slot as its own data resolves; at the top level it equals no `Reveal`, but nested it takes one position in an outer order.
- `collapsed` suppresses fallbacks past the frontier under `sequential` only, so effectively one skeleton shows at a time.
- A nested `Reveal` registers as one composite slot with the parent and follows its own order once released, with no way to opt out of an outer hold; a nested `Loading` starts a separate boundary scope, so it is not an additional slot in the outer group.

## Read inputs before the first `await`

Dependency tracking is synchronous. An async computation registers only the reads made before its first `await`; a later read is outside the tracking window, so a change to that source cannot re-run the computation.

```ts
import { createMemo } from "solid-js";

// Avoid: permissions() is read after the await and is never tracked.
const profile = createMemo(async () => {
	const user = await fetchUser(id());
	return { user, canEdit: permissions().includes("edit") };
});
```

```ts
import { createMemo } from "solid-js";

// Prefer: read every input first, then await.
const profile = createMemo(async () => {
	const userId = id();
	const canEdit = permissions().includes("edit");
	const user = await fetchUser(userId);
	return { user, canEdit };
});
```

Run the `Avoid` version and change `permissions`: the memo does not recompute, and the page keeps the old `canEdit`.

The failure is worse when the late read is itself async and not ready. No dependency edge exists, so the source cannot wake the computation, and it stays pending with no retry. Development turns that read into an error so it reaches `Errored` instead of hanging; production omits the check.

## Cancel work

Solid drops a superseded run's result automatically. The work the run started — a request, a timer, a subscription — keeps going unless the run stops it. When cleanups run depends on whether the user saw that run.

```ts
import { createMemo, onCleanup } from "solid-js";
const results = createMemo(async () => {
	const q = query();
	const controller = new AbortController();
	onCleanup(() => controller.abort()); // before the first await
	const response = await fetch(`/search?q=${q}`, { signal: controller.signal });
	return response.json();
});
```

- A run that never committed is cleaned up as soon as a newer run supersedes it, so `onCleanup` before the first `await` cancels an unfinished request. The run on screen stays fully live until its replacement lands — its children keep reacting and its timers keep running — and its cleanups run when the replacement commits.
- An iterable the computation returns is closed as soon as the run is superseded, because nothing can show its remaining values. To stop work when one input changes, tie that work to the input in a child computation, so it re-runs with the input instead of waiting for the whole update.
- Do not await a cleanup from inside the update that replaces the run. An on-screen run's cleanups run only when the held update commits, so code waiting on one can wait forever: an action racing a promise resolved from `onCleanup`, or a new run awaiting a lock the old run releases there. Signal from the input instead, or hand the lock over when the new run acquires it.

## Data-fetching patterns

**One thing.** Async memo plus `Loading`, as in the first section. When the data is a list or tree whose rows need identity across updates, load it into a store: `createStore(async () => api.orders(customerId()), [] as Order[])`. Responses reconcile by `id`, so unchanged rows keep their DOM. Add `on={itemId()}` only when a changed subject should show the fallback.

**Search as you type.** The input writes a signal; a memo turns it into results.

```tsx
import { For, createMemo, createSignal, isPending, latest } from "solid-js";
function ProductSearch() {
	const [query, setQuery] = createSignal("");
	const results = createMemo(() => {
		const text = query().trim();
		if (!text) return [];
		return api.search(text);
	});

	return (
		<>
			<input
				type="search"
				value={latest(query)}
				onInput={(event) => setQuery(event.currentTarget.value)}
			/>
			<ul class={{ stale: isPending(results) }}>
				<For each={results()}>{(product) => <li>{product.name}</li>}</For>
			</ul>
		</>
	);
}
```

- Superseded responses are dropped by the runtime — no request counter or "latest request id" check — and the list never blanks: the previous results stay visible, dimmed by `isPending`, until the new ones land.
- An empty query returns `[]` synchronously, which is a settled answer; the memo does not become pending for it, so no spinner shows.
- Bind a controlled input to `value={latest(query)}` because the write to `query` is held while results load. An uncontrolled input needs no binding.
- Debounce in the event handler. A debounce written as an effect that copies one signal into another after a delay is the relay pattern that produces a one-flush lag and a second source of truth.

**Several requests on one page.** Create all memos where the page is created so they start together, and give each region its own boundary.

```tsx
import { Loading, createMemo } from "solid-js";
function ProductPage(props: { id: string }) {
	const product = createMemo(() => api.product(props.id));
	const reviews = createMemo(() => api.reviews(props.id));
	const related = createMemo(() => api.related(props.id));

	return (
		<article>
			<Loading fallback={<ProductSkeleton />}>
				<ProductHeader product={product()} />
			</Loading>
			<Loading fallback={<ReviewsSkeleton />}>
				<ReviewList reviews={reviews()} />
			</Loading>
			<Loading fallback={<RelatedSkeleton />}>
				<RelatedGrid products={related()} />
			</Loading>
		</article>
	);
}
```

On a subject change, all three requests restart and the update is held until all three answer, so the page swaps as one. If a slow section must not delay the others, give it `on={props.id}`: it stops holding the update, shows its skeleton from the swap, and fills in when its own data lands.

**Dependent requests.** Only when the second request needs a value from the first response. If the input is already available from props or the route, read it directly so both start together; if the dependency is intrinsic, join the requests server-side.

**Pagination.** A page number is an input. Keep rows in a derived store so identity survives page changes, and read the page through `latest` in the pager.

```tsx
import { For, Loading, createSignal, createStore, isPending, latest } from "solid-js";
function OrderHistory() {
	const [page, setPage] = createSignal(1);
	const [orders] = createStore(
		async () => api.orders({ page: page() }),
		[] as Order[]
	);

	return (
		<>
			<Loading fallback={<TableSkeleton />}>
				<table class={{ stale: isPending(() => orders.length) }}>
					<For each={orders}>{(order) => <OrderRow order={order} />}</For>
				</table>
			</Loading>
			<Pager page={latest(page)} onChange={setPage} />
		</>
	);
}
```

Page 1 stays visible and dimmed until page 2 arrives; the pager shows page 2 selected immediately; rows present on both pages keep their DOM. If each page should show a skeleton instead, move the choice to the boundary with `on={page()}`.

**Infinite scroll.** Accumulate with the async memo's previous-value argument.

```ts
import { createMemo, createSignal } from "solid-js";
const [page, setPage] = createSignal(1);
const orders = createMemo(async (previous: Order[] = []) => {
	const next = await api.orders({ page: page() });
	return [...previous, ...next];
});
```

Each run receives the last committed list and returns the longer one. To reset on a filter change, read the filter in the memo and start over when it differs, or keep the accumulated list in a store keyed by filter; the simplest reset is a `Show` keyed on the filter around the list, which remounts it with `page` back at 1.

**Share one request.** Two components that create the same memo make two requests. Create it once in a common ancestor and pass the accessor down or through context; passing the accessor keeps the read lazy, so nothing waits until a component reads it.

```tsx
import { createContext, createMemo, useContext } from "solid-js";
import type { Accessor, ParentProps } from "solid-js";
type Cart = { items: { id: string }[] };
const CartContext = createContext<Accessor<Cart>>();

function StorefrontLayout(props: ParentProps) {
	const cart = createMemo(() => api.cart());
	return <CartContext value={cart}>{props.children}</CartContext>;
}

function CartBadge() {
	const cart = useContext(CartContext);
	return <span>{cart().items.length}</span>;
}
```

For deduplication by argument across routes, use `query(fn, "name")` from `@solidjs/router`: same name plus same arguments returns the same in-flight promise, the result is retained briefly after the last reader leaves, and a mutation's revalidation key refreshes it.

**Freshness.** A memo answers once and keeps the answer until an input changes. When the world changes instead, call `refresh(source)`.

```tsx
import { createMemo, onSettled, refresh } from "solid-js";
const stats = createMemo(() => api.dashboardStats());

onSettled(() => {
	const interval = setInterval(() => refresh(stats), 30_000);
	return () => clearInterval(interval);
});
```

A bare refresh re-asks the same question, so `isPending` stays `false` and the new value lands quietly. When the reload should be visible, mark it: `affects(stats)` inside an action before the refresh makes readers report pending until it lands. When the server can push, consume a `live` source instead of polling; each yielded value becomes the next answer.

**Mutate, then refetch.** Run the write and the refetch in one `action`, with the optimistic write before the `yield` and `refresh(source)` after it, so the list updates once when fresh data lands. The mechanics belong to the mutations branch.

## Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| The search box lags behind what was typed | The input is bound to `query()`, whose write is held by the request | Bind `value={latest(query)}` or leave the input uncontrolled |
| Opening another item keeps showing the old one | Default held behavior after a first answer | Add `on={itemId()}` to the boundary, or accept the hold and dim with `isPending` |
| Two components make the same request | Each created its own memo; each memo is a request | Create it once in an ancestor and pass the accessor or provide it through context; use `query` across routes |
| `refresh` runs but nothing shows as loading | A bare refresh re-asks the same question, so `isPending` stays `false` | Call `affects(source)` inside an action before the refresh |
| One request waits for another it does not need | A memo reads a value from another response that was available from props or the route | Read the available input directly so both start together; join real dependencies server-side |
| The value renders once and never updates | The read is in the component body, outside a tracking scope | Read it in JSX, a memo, or an effect compute function |
| Nothing happens, and the not-ready path is never taken | `on` or another dependency list received the accessor instead of a call | Write `on={id()}`, not `on={id}` |
| A failed search shows success styling | `isPending` is the only read of the value, so the rejection is swallowed | Keep a plain read inside `Errored` |

See also: `references/routing-and-server.md` for mutations, form actions, and server-side revalidation.

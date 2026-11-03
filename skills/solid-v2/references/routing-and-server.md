# Routing and server functions

This branch covers the fullstack surface: Solid Router as the owner of the URL, route data through `preload` and `query`, server functions and their transport, mutations, forms, and the three layers that guard a protected section.

## Mount and create
Create the router once at module scope. A `createRouter` call inside a component rebuilds the route tree and its history on every run, and a second router inside the first fights it for the URL.
```tsx
// src/router.ts
import { lazy } from "solid-js";
import { createRouter, intentPreload, pendingLinks } from "@solidjs/router";
export const Router = createRouter({
	routes: [
		{ path: "/", component: lazy(() => import("./pages/Home")) },
		{ path: "/products/:id", component: lazy(() => import("./pages/Product")) },
		{ path: "*404", component: lazy(() => import("./pages/NotFound")) },
	],
	preloadLinks: intentPreload(),
	links: pendingLinks,
});
export const { paths } = Router;
```
`Router` is both the provider component and the application-wide instance. `paths` is inferred from the route literals: `paths()` is `/`, `paths.products("mug")` is `/products/mug`, and `paths.products()` without an argument is a type error.
Mount it once at the root. The function child is the app shell; it is never part of a match, stays mounted while pages change, and receives the matched page as `props.children`.
```tsx
// src/App.tsx
import { Loading } from "solid-js";
import { paths, Router } from "./router";
export default function App() {
	return (
		<Router>
			{(props) => (
				<>
					<header>
						<a href={paths()}>Store</a>
					</header>
					<Loading fallback={<main>Loading…</main>}>
						<main>{props.children}</main>
					</Loading>
				</>
			)}
		</Router>
	);
}
```
The `Loading` boundary gives the first load a fallback while a lazy page or its data is pending. Later navigations keep the current page on screen, so the fallback does not flash.
With the file-system adapter, `src/routes` supplies the tree: `index.tsx` becomes `/`, `[id].tsx` becomes `/:id`, `[...404].tsx` becomes the catch-all, and `products.tsx` next to a `products/` directory is a layout for everything inside it. `fileRoutes(pageRoutes)` converts the generated manifest into the same route objects, and a route module's named `route` export (from `defineFileRoute("/products/:id", { preload, matchFilters, search })`) supplies its route config.
A hand-written array assigned to a variable first widens its literals to `string`, which silently accepts typos. Wrap it in `defineRoutes` to keep the literal types.

## Links
There is no link component. Write an `<a>`.
The router intercepts clicks on same-origin anchors inside the router and turns them into a client-side navigation; the header keeps its DOM and the document does not reload. It leaves an anchor alone when it is outside the router, points at another origin, or carries `target`, `rel="external"`, `download`, or a non-HTTP scheme. With `explicitLinks: true`, only anchors carrying `link` are handled.
Build every URL with `paths`.
```tsx
// Avoid: a string the type checker cannot connect to a route
<a href={"/products/" + product.id}>{product.name}</a>
// Prefer: a node from the route tree
<a href={paths.products(product.id)}>{product.name}</a>
```
Rename the route and the string version becomes a dead link to the catch-all that nothing reports; the `paths` version stops compiling until every call site is updated.
`replace` replaces the history entry, `noscroll` keeps the scroll position, `state` supplies `location.state` for the destination, and `preload="false"` opts the link out of every preload strategy. `preload="viewport"` and `preload="eager"` mark links for those strategies.
A static route is the bare node — `paths.account`, not `paths.account()`. Path nodes convert to a string in `href`, `navigate()`, and `redirect()` on their own; call a node only when an API insists on a `string`.

## Navigate from code
Navigation that is part of the interface is an anchor. Navigation that is a consequence — a saved form, a timeout, a completed wizard — uses `useNavigate`.
```tsx
import { useNavigate } from "@solidjs/router";
import { paths } from "../router";
function CheckoutButton() {
	const navigate = useNavigate();
	return (
		<button onClick={() => navigate(paths.checkout, { replace: true })}>
			Check out
		</button>
	);
}
```
Options mirror the link attributes: `replace`, `scroll`, `state`, plus `resolve`. With `resolve: true` (the default), a string starting with `/` resolves under the router's `base` and any other string resolves against the current location like a relative URL. A number moves through history: `navigate(-1)` is back.
When a mutation ends in a navigation, do not navigate from the caller at all. Return `redirect(paths.account.orders(id))` from the server function; the mounted router applies the navigation in the same update as the revalidation, so the destination never paints stale data.
```ts
import { redirect } from "@solidjs/web";
// Prefer: the mutation's own response carries the destination
export async function updateAccount(name: string) {
	"use server";
	await database.users.rename(currentUserId(), name);
	return redirect(paths.account);
}
```
Navigating from an effect or callback after the write commits the current page first and navigates after it.

## Location and params
`useLocation()` returns a reactive object; each field tracks on its own, so a memo reading `pathname` does not re-run when only the hash changes.
```tsx
import { useLocation } from "@solidjs/router";
const location = useLocation();
location.pathname; // "/products/mug"
location.search; // "?ref=home"
location.query; // { ref: "home" }
location.hash;
location.state;
location.key; // changes on every navigation
```
`useParams()` returns the merged parameters of the current match. Pass a typed path node as a witness to narrow the keys; the witness is not matched at runtime.
```tsx
import { useParams } from "@solidjs/router";
import { Router } from "../router";
const params = useParams(Router.paths.products);
params.id; // string
```
Inside a route component, `props.params` is that same object, already typed when the component is declared with `RouteProps<typeof Router.paths.products>`. Read `props.params.id` where it is displayed, never in a `const` at the top of the body — the body runs once, so the heading freezes at the first id and development prints `[STRICT_READ_UNTRACKED]`.
Parameter values are decoded: `/products/caf%C3%A9` gives `id: "café"`. An encoded slash stays inside its parameter, so `%2F` in one segment reads as `/` in one value, while `location.pathname` keeps the URL's encoding.

## Search params
Search parameters are the home for state a refresh must preserve and a shared link must reproduce: filters, sort order, page number.
`useSearchParams` returns a reactive read and a setter that merges into the current query string and navigates without scrolling. Setting a key to `""`, `undefined`, or `null` removes it.
```tsx
import { useSearchParams } from "@solidjs/router";
const [search, setSearch] = useSearchParams();
setSearch({ page: 2 });
```
Without a schema every value is a string or an array of strings. Give the route a `search` schema to get parsed, typed values, then pass the path node to the hook.
```ts
import * as v from "valibot";
{
	path: "/search",
	search: v.object({
		q: v.optional(v.string(), ""),
		page: v.optional(v.pipe(v.unknown(), v.transform(Number)), 1),
	}),
	component: Search,
}
```
```tsx
import { useSearchParams } from "@solidjs/router";
import { Router } from "../router";
const [search, setSearch] = useSearchParams(Router.paths.search);
search.page; // number
setSearch({ page: search.page + 1 });
```
The query string holds only strings, so the schema is where `"2"` becomes `2`; a plain `v.number()` would reject every value. Schemas run synchronously — an asynchronous schema throws `Async Standard Schema validation is not supported for search params`, and a value that needs a server round trip to validate is a query, not a search parameter. A schema that reports issues is skipped for that read, so the raw strings remain instead of the page throwing. The router runs the schemas of every route in the current match, root to leaf, and merges the outputs over the raw values.
Schema output is still user input. Anything read from the URL and sent to a server function must be validated again inside the function.
A controlled input that writes to the URL lags during a held navigation, because the write is held with the data. Read it through `latest` so the control the user touched shows the new value while the old results stay on screen.
```tsx
import { latest } from "solid-js";
import { useSearchParams } from "@solidjs/router";
const [search, setSearch] = useSearchParams();
<input
	value={latest(() => search.q ?? "")}
	onInput={(event) => setSearch({ q: event.currentTarget.value })}
/>;
```

## Active and pending links
The router sets two attributes on the anchors it handles, and both are styled in CSS with no component code:

- `aria-current="page"` when the path and the query match, ignoring parameter order and the hash.
- `data-active` on an exact or descendant path match, ignoring the query, so the Account link is active on `/account/orders/42`.
The root path `/` is active only on an exact match; otherwise it would be active on every page. An `aria-current` value you set yourself, such as `aria-current="step"`, is left alone.
`data-pending` marks the target of an in-flight link click or `navigate()` call, and needs the plugin:
```ts
import { createRouter, pendingLinks } from "@solidjs/router";
export const Router = createRouter({ routes, links: pendingLinks });
```
```css
nav a[aria-current="page"] { font-weight: 600; }
nav a[data-active] { color: var(--accent); }
a[data-pending] { opacity: 0.6; cursor: progress; }
```
For a component that is not an anchor, or an anchor that needs the state in JSX, `useLinkState(() => href, { end: true })` returns `active`, `current`, and `pending` accessors; its `pending` works without the plugin, and `end: true` asks for exact matching.

## Navigation guards
`useIsRouting()` is an accessor that is true while a navigation waits on route work — use it for a top-of-page progress bar. `useMatch(() => pattern)` tests a pattern against the current pathname without needing a route for it, and `useRouteMatches()` returns the matched definitions with their `info`, which is how a breadcrumb reads route metadata.
For unsaved changes, register a leave guard:
```tsx
import { useBeforeLeave } from "@solidjs/router";
useBeforeLeave((event) => {
	if (!dirty()) return;
	event.preventDefault();
	if (window.confirm("Discard unsaved changes?")) {
		event.retry(true);
	}
});
```
`preventDefault()` blocks the navigation. `retry(true)` re-issues it and skips the guards, so the confirmation does not appear twice. The guard runs for router navigations and for the history traversal the router can intercept; it cannot stop the user closing the tab, so pair it with a `beforeunload` listener when that matters.

## Route data
A route's `preload` runs when the route is matched, before the component exists, with the matched `params`, the target `location`, and an `intent`:

| `intent` | When |
| --- | --- |
| `"initial"` | First render, including the server render |
| `"navigate"` | A link click or `navigate()` call |
| `"native"` | Browser back or forward |
| `"preload"` | A link preload strategy or `usePreloadRoute` |

Use it to skip work too expensive to run on a hover. Return `void` and start the work.
```tsx
preload: ({ params, intent }) => {
	void getProduct(params.id);
	if (intent !== "preload") void getReviews(params.id);
},
```
Whatever `preload` returns is captured once when the route matches and arrives as `props.data`, so returning the product makes a param change show the old product forever. Return a value only for something that must not change while the route stays matched.
```tsx
// Avoid: props.data is captured once, so a param change shows the old product
preload: async ({ params }) => getProduct(params.id),
// Prefer: start the request and let the page read it reactively
preload: ({ params }) => void getProduct(params.id),
```
Links do not preload until a strategy is configured. `intentPreload()` warms on hover after a short delay, on focus, and on touch; `tapPreload()` warms on `pointerdown`; `viewportPreload()` and `eagerPreload()` apply only to links marked `preload="viewport"` and `preload="eager"` and do not run route preloads by default. Pass `{ data: true }` or `{ data: false }` to change that. Opt an expensive or side-effecting link out with `preload="false"`. `usePreloadRoute()` warms a route from code with `{ preloadData: true }`.
`query(fn, name)` gives a read a cache key: the name plus a stable serialization of the arguments. Its `.key` and `.keyFor(args)` are what `revalidate` takes.
```ts
import { query } from "@solidjs/router";
import { database } from "./database";
export const getProduct = query(async (id: string) => {
	"use server";
	return database.products.find(id);
}, "product");
```
The cache lifetime differs by side. On the server it lives for one request, so two components rendering the same product make one call and the next request starts empty. In the browser a fresh result is reused for a few seconds so a preload and the following navigation share it; afterwards the entry stays alive while something reads it and is swept a few minutes after the last reader leaves, which is why back and forward are usually instant.
`revalidate(key)` marks matching entries stale and re-runs the ones being read. Keys match by prefix, so `getProduct.key` reaches every id. Calling it by hand is rare; a mutation response usually carries the keys.
`query` declares a plain server function as `GET`, so reads are cacheable and exempt from the mutation path. A function you call outside `query` needs its own `GET()` declaration.

## Server functions
`"use server"` is the first statement of a function body, or the first line of a module to make every export a server function. A directive inside a class method, getter, or setter has no effect and the compiler rejects it; declare the function at module level and call it.
The build keeps the body on the server under a stable id and leaves a typed stub in the browser. Imports referenced only inside the body — a database client, a validation schema — are removed from the client build with it.
```ts
import { database } from "./database";
export async function getProduct(id: string) {
	"use server";
	return database.products.find(id);
}
```
The body runs at module top level on the server, so it may read its parameters, module-scope bindings, and globals. It may not read a variable declared between module scope and the function.
```tsx
// Avoid: the body reads a variable from the component's scope
function AddToCart(props: { productId: string }) {
	const productId = props.productId;
	async function add() {
		"use server";
		await database.cart.add(productId);
	}
	return <button onClick={add}>Add to cart</button>;
}
// Prefer: pass the value as an argument
function AddToCart(props: { productId: string }) {
	return (
		<button onClick={() => addToCart(props.productId)}>Add to cart</button>
	);
}
```
The `Avoid` version does not build: the extracted body would read a variable that does not exist where it runs, and the compiler names it with file and line.
In the browser a call is `POST /_server/data/<id>` carrying the encoded argument list. The bare `/_server/<id>` answers plain HTTP for HTML form posts and scripts, which is why every argument is untrusted. During server rendering the same call runs in-process under a request event derived from the page request, with no HTTP, and sees the same `locals`.
Two kinds of wrapper behave differently. A module-level wrapper inside a `"use server"` module is part of the registered implementation, so it runs for every call path, including a direct HTTP request. Declaration wrappers — `GET()`, `live()`, `broadcast()`, `withMeta()` — wrap a function-level reference from the outside, configure how it is called, and run no server-side policy.
```ts
import { GET } from "@solidjs/web/server-functions";
export const getProduct = GET(async (id: string) => {
	"use server";
	return database.products.find(id);
});
```
`GET()` expects a server-function reference, not a plain async function; wrapping a plain function throws `GET expects a server function reference` and leaves the database import in the client bundle.
Read identity from `getRequestEvent()?.locals`, never from an argument. A caller can put any id, flag, or price in the request body, and TypeScript types do not exist at runtime.

## Reads and streams
Server functions use `POST` by default, with a same-origin check, and responses leave with `Cache-Control: no-store`.
Declare `GET()` only for a read that is safe and idempotent and is called outside `query`. A `GET()` call puts its arguments in the URL, which is written to browser history, access logs, and cache keys — never put a session token or secret there. When the encoded URL exceeds the transport's length limit, the client silently sends a `POST` instead and the answer is not cached. A function that never declared `GET()` answers a `GET` with status 405.
A cache entry needs both the declaration and a header:
```ts
import { respond } from "@solidjs/web";
import { GET } from "@solidjs/web/server-functions";
import { database } from "./database";
export const getCatalog = GET(async () => {
	"use server";
	const products = await database.products.all();
	return respond(products, {
		headers: { "cache-control": "public, max-age=60" },
	});
});
```
Returning an async iterable streams each yielded value over the open response. Ending the iteration in the browser with `break` or `return` aborts the request and fires the server's `request.signal`. A stream owns one connection and does not reopen; it suits a sequence of events the consumer accumulates.
`live(fn)` declares a value-shaped source: each yield is the current answer to one question, not an event to add to a list. It declares `GET` itself and yields the current value first on every invocation, which is the contract a reconnect depends on.
```ts
import { live } from "@solidjs/web/server-functions";
export const stockLevel = live(async function* (productId: string) {
	"use server";
	yield await inventory.count(productId);
	for await (const change of inventory.subscribe(productId)) {
		yield change.count;
	}
});
```
Read it through one memo: every call site that invokes a live source holds its own connection and reconnects on its own, so two components calling `stockLevel(id)` hold two streams. Hoist the memo to the nearest common parent and pass the value down.
The returned source has an optional `onstatus` callback receiving `"connected"`, `"reconnecting"`, or `"closed"`. Show reconnecting next to the value when the user should know it may be behind; put freshness timestamps in the yielded value, because connection status is a transport fact. A failure before the first value, or a 4xx, rejects like a normal call; after a connection, transient failures retry with exponential backoff.
`broadcast(fn)` is `live(fn)` on the client. On the server the body runs for every caller, so gates, redirects, and `respond()` work as usual, while the answer returned from the body is produced once per argument set and shared. That answer may read the function's parameters and module scope, never the body's other locals — every later caller would otherwise receive the first caller's data, so the compiler rejects it. The shared producer runs under its own request event, where `getRequestEvent()` finds no request.

## Mutations and responses
A mutation is a server function that writes, called from an `action` (the reactive transaction from `solid-js`) or submitted by a form action.
```ts
import { reload, respond } from "@solidjs/web";
export async function addToCart(productId: string, quantity = 1) {
	"use server";
	if (!Number.isInteger(quantity) || quantity < 1) {
		throw respond(
			{ field: "quantity", message: "Quantity must be a whole number" },
			{ status: 400 }
		);
	}
	await database.cart.add(currentSessionId(), productId, quantity);
	return reload({ revalidate: getCart.key });
}
```
```tsx
import { action } from "solid-js";
const add = action(function* (productId: string) {
	yield addToCart(productId);
});
<button onClick={() => add(props.productId)}>Add to cart</button>;
```
`respond(value, { status, headers })` pairs a value with response metadata. The function's inferred return type is the value's type, so a caller receives the product, not the envelope. At runtime it is a real `Response`, so a fetch-style handler without Solid knowledge can return it as-is.
`redirect(path, { revalidate })` returns a redirect `Response`. Return it when the redirect is the successful outcome; throw it when it is an early exit, as a sign-in check does. Both reach the caller the same way. A mounted router navigates without a page load; a form post without JavaScript follows the 302; code with no router receives the `Response` object as the resolved value.
`reload({ revalidate })` asks an integration to refresh the named keys without navigating. The keys travel in the `X-Revalidate` header; the matching rule is the router's, and keys match by prefix.
A `POST` from a server function or form action that declares no keys revalidates every query on screen — the safe assumption after a write. Reads are exempt when they go through `query` or are declared with `GET()`. A `POST` that changes nothing declares an empty scope: `respond(results, { revalidate: "" })`.
Errors split on who branded them. A returned or thrown `Response` or envelope is control flow, and its status, headers, and value are preserved. Any other thrown value is replaced with `Internal Server Error` in production, so a driver's failing query cannot reach the browser. The line is the build, not `NODE_ENV`.
For a structured failure the caller should see, throw the envelope. Returning it makes the caller's promise resolve successfully whatever the status.
```ts
import { respond } from "@solidjs/web";

// Avoid: returned, so the caller's promise resolves with the issues
return respond({ issues }, { status: 400 });
// Prefer: thrown, so the caller's promise rejects with the issues
throw respond({ issues }, { status: 400 });
```
`markSafeError(new Error(message))` brands an error you constructed so its message and own properties cross the boundary in production. Do not brand an error from a driver or third-party client; it can carry anything in its properties.
An optimistic store write goes before the `yield`, so the prediction and the revalidated server state commit as one update:
```tsx
import { action, createOptimisticStore } from "solid-js";
const [cart, setCart] = createOptimisticStore(
	() => getCart(),
	[] as CartLine[]
);
const add = action(function* (productId: string) {
	setCart((draft) => {
		draft.push({ productId, quantity: 1, pending: true });
	});
	yield addToCart(productId);
});
```
The new line appears at once. When the call returns, the revalidated cart replaces it, or it disappears if the server rejected it, with no frame of the old cart in between. A failing `yield` rejects, so catch it when the page must show a message.

## Forms
A form action comes from the router. `action` from `solid-js` is the reactive transaction and has no URL, so `action={coreAction}` is a type error and renders nothing usable.
```ts
import { formAction } from "@solidjs/router";
import { redirect } from "@solidjs/web";
export const submitAddress = formAction(async (form: FormData) => {
	"use server";
	await database.addresses.save(Object.fromEntries(form));
	return redirect("/checkout/shipping");
});
```
```tsx
<form method="post" action={submitAddress}>
	<label>
		Name
		<input name="name" required />
	</label>
	<label>
		Postal code
		<input name="postalCode" required pattern="[0-9]{5}" />
	</label>
	<button type="submit">Continue</button>
</form>
```
Only `POST` forms are accepted; a `GET` form throws `Only POST forms are supported for Actions`, because a GET describes a URL, not a mutation. The form action serializes to a URL in the HTML, so the form works before JavaScript loads: the server runs the function, sees the redirect, and answers 302.
Keep inputs uncontrolled — the browser assembles the `FormData` on submit, and Solid does not read their values on every keystroke. `required` and `pattern` are browser convenience; anyone can post to the URL with `curl`, so validate on the server with a schema and throw `respond(issues, { status: 400 })`.
Read the failure reactively. `useSubmissions(action)` returns a reactive array of settled records, each with `input`, `result` or `error`, `retry()`, and `clear()`. A thrown envelope's value is `submission.error`; a submission that redirected or returned nothing does not stay in the list.
```tsx
import { Show } from "solid-js";
import { useSubmissions } from "@solidjs/router";
const submissions = useSubmissions(submitAddress);
const issues = () =>
	(submissions.at(-1)?.error as { issues?: Record<string, string> } | undefined)
		?.issues ?? {};
<Show when={issues().postalCode}>
	{(message) => <p role="alert">{message()}</p>}
</Show>;
```
While a scripted submission runs, the router sets `aria-busy="true"` on the form and removes it when the call and any revalidation settle, so style pending state in CSS. Busy state is keyed by the form's action URL, and a value you set yourself is not removed.
Without JavaScript the runtime cannot hand the 400 to a script: it stores the thrown value in a one-shot cookie and redirects back to the form, and the router reads that cookie during the next server render. `useSubmissions` sees the same entry either way.
Arguments known where the form renders are bound with `.with(boundArgs)` instead of hidden inputs; the bound values travel in the form action's URL, so the no-JavaScript path receives them too:
```tsx
<form method="post" action={removeFromCart.with(line.productId)}>
	<button>Remove</button>
</form>
```
For an optimistic form there is no action body to write in, so `.onSubmit` runs before the mutation is sent, inside the same transaction:
```tsx
submitAddress.onSubmit((form) => {
	setAddresses((draft) => {
		draft.push({
			name: String(form.get("name")),
			id: "unsaved",
			pending: true,
		});
	});
});
```
The whole pass is: `query` for the list, `reload({ revalidate: getAddresses.key })` from the server function, `createOptimisticStore` for the read, and the form action wrapping the write. The pending row is discarded when the action settles, on success and failure alike, and the revalidated list replaces it.

## Protected routes
Decide once — is there a `userId` on the request event — and run that decision in three layers. Each covers an entry the others cannot see.

1. **Inside every server function** protects the data. It runs for a page render, a client navigation, a form post, and `curl` alike, because all of them reach the function through a request event.
2. **A pathless route with a `preload` and a component** protects the navigation. It turns a missing session into a redirect before the guarded pages render, on the server and in the browser.
3. **Middleware** protects the full page request. It answers a request for the section before any rendering starts.
A route guard alone leaves the server function callable by anyone who knows its URL. A server function check alone leaves the page rendering without data: in the browser the read receives a response object instead of a navigation. Middleware alone never sees a client-side navigation, because a navigation inside the router makes no page request.
```ts
import { query } from "@solidjs/router";
import { getRequestEvent, redirect } from "@solidjs/web";
const getOrders = query(async () => {
	"use server";
	const userId = getRequestEvent()?.locals.userId;
	if (!userId) throw redirect(paths["sign-in"]);
	return database.orders.forCustomer(userId);
}, "orders");
```
Group the guarded pages under a route with no `path`. It adds to the match without adding to the URL, so `/account/orders` still matches three sections.
```tsx
{
	preload: ({ location }) =>
		void requireUser(location.pathname + location.search),
	component: RequireUser,
	children: [
		{ path: "/account", component: AccountLayout, children: accountRoutes },
	],
},
```
```ts
import { query } from "@solidjs/router";
import { redirect } from "@solidjs/web";

export const requireUser = query(async (next: string) => {
	"use server";
	const user = await getCurrentUser();
	if (!user) throw redirect(paths["sign-in"]({ next }));
	return user;
}, "require-user");
```
The preload starts the check as soon as the match exists; the memo in `RequireUser` holds the navigation until it answers. Throw the redirect inside the function the `query` wraps, not from an effect or callback after the page committed — the read stays pending and the sign-in page replaces the target before anything paints. A hover preload uses the `"preload"` intent and does not act on the outcome, so hovering never redirects.
Keep the sign-in route a sibling of the group, never a child: a sign-in page inside the guard redirects to itself, and the router stops after 100 redirects with `Too many redirects`.
Validate `next` on the server with a `safeNext(value)` helper, where it becomes a `Location` header. The hidden field is caller-controlled, and `//attacker.example` or `/\attacker.example` resolves to another origin. Accept only a path starting with a single `/`, rejecting `//`, `/\`, and the sign-in page itself; treat the copy in the form as a convenience.
Middleware goes after the session middleware, because order in the array is order of execution, and returns a redirect without calling `next()`:
```ts
import { getRequestEvent } from "@solidjs/web";

async function requireAccountSession(request: Request, next: () => Promise<Response>) {
	const url = new URL(request.url);
	if (url.pathname.startsWith("/account") && !getRequestEvent()?.locals.userId) {
		const target = paths["sign-in"]({ next: url.pathname + url.search });
		return Response.redirect(new URL(target, request.url), 302);
	}
	return next();
}
```
The middleware matches paths, and a path prefix is not a permission: the server functions the pages call live at their own URLs, so the check inside each function stays. Middleware also does not see `/_server` calls or client-side navigations, which is why it is added to the route guard, not substituted for it.

## Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| A link reloads the whole document | The anchor is outside the router, has `target`, names another origin, or lacks `link` under `explicitLinks` | Render it inside `<Router>` and drop the opt-out attributes |
| `paths.products` is a type error | The route is `/products/:id`, so the node needs its parameter | Call it: `paths.products(id)`; static routes stay bare |
| The active style is on every link | The style targets `data-active` on `/`, which is a parent of everything | Use `aria-current="page"` for home, or `useLinkState` with `end: true` |
| `search.page` is a string | No `search` schema on the route, or the path node was not passed | Add a schema with a transform to `Number` and call `useSearchParams(paths.search)` |
| A server function call resolves to a `Response` | The function returned `redirect()` or `reload()` and no router is subscribed to the transport | Call it with the router mounted, or return a value and navigate in the caller |
| Build error: `server functions cannot capture non-top-level variables` | The body reads a component prop or loop variable | Pass the value as an argument |
| The database import is in the client bundle | A value outside a `"use server"` body references it | Move the read into a server function or a `"use server"` module |
| The function body runs in the browser | The `serverFunctions` transform is off | Enable it in the Vite config; otherwise `"use server"` is an ignored string |
| `Cannot call server function outside of a request` | Server code called it at module load, from a timer, or in a test without an event | Call it from a render, middleware, or another server function; provide an event in tests |
| `action` is not a function, or the form attribute renders source | The form got the core `action` from `solid-js` | Import `formAction` from `@solidjs/router` |
| The production message is `Internal Server Error` | A plain `Error`, string, or object was thrown | `throw respond(value, { status })`, or `markSafeError` for your own `Error` |
| The 400 arrives as a successful result | `respond(value, { status: 400 })` was returned | Throw it: only a thrown outcome rejects the caller |

See also: `references/async.md` for held updates, `isPending`, and the read side of route data.

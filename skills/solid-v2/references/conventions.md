# Project conventions

The project-level rules to apply before creating, moving, or reviewing any file: layout, imports, naming, where state lives, tooling, the consolidated review checklist, and the 2.0 name check. The mechanics live in the sibling references; this file is what you consult first and check a diff against last.

## Project layout

A start-mode project has two authored root files and generated entries around them:

```
src/
  App.tsx                 default-exported root: router, site layout, Loading boundary
  Document.tsx            default-exported HTML shell; app arrives as props.children
  router.ts               createRouter({ routes }) once, exports Router and paths
  routes/
    index.tsx             /
    users.tsx             layout wrapping every page under /users
    users/[id].tsx        /users/:id, with data loading
    [...404].tsx          catch-all
  components/
    Counter.tsx           reusable component
    Counter.test.tsx      its colocated test
  data/
    products.ts           server functions, query() reads, formAction() wrappers
  server/
    session.ts            server-only modules: database, session, env
    session.test.ts       Node test beside it
  types/
    elements.d.ts         module augmentation for custom elements
vite.config.ts            solid({ start: true, ssr: true, diagnostics: true })
```

- `src/App.tsx` default-exports the root component. The router, the site-wide layout, a default `<Title>`, and a `Loading` boundary around `props.children` live here; anything belonging to one page lives in that page's route module.
- `src/Document.tsx` default-exports the full `<html>` element, receives the app as `props.children`, renders `{props.children}` in `<body>`, and includes `<HydrationScript />` once in `<head>` before the app markup when `ssr` is on. Without it, input between HTML arrival and hydration is lost; with it in a static build, the handler strips the output for free.
- `src/router.ts` creates the router once at module scope with `createRouter({ routes })` and exports `Router` and `paths`. A second `createRouter` call inside a component gives every parent update a new router.
- `src/routes/**` is the file-route tree: `index.tsx` → `/`; `[id].tsx` → `/:id`; `users.tsx` plus a `users/` directory → a layout plus its pages; `[...404].tsx` → the catch-all. A default export makes a page; a layout renders its children. Keep data modules out of `src/routes/**`: with `httpMethods` on, an uppercase HTTP-method export turns that module into an API route.
- `src/components/**` holds reusable components with colocated `Component.test.tsx`.
- `src/data/**` holds server functions, `query()` reads, and `formAction()` wrappers — the modules a page imports instead of talking to a database.
- `src/server/**` holds server-only modules (database, session, env) with Node tests beside them.
- `src/types/**/*.d.ts` holds module augmentation for custom elements and global types.

## Imports and package boundaries

| Symbol | Package |
| --- | --- |
| `createSignal`, `createMemo`, `createEffect`, `untrack`, `flush`, `onCleanup`, `onSettled`, `action`, `isPending`, `latest`, `onFlush`, `refresh`, `affects`, `until`, `from`, `isHydrating`, `onHydrationEnd` | `solid-js` |
| `createStore`, `createProjection`, `createOptimisticStore`, `snapshot`, `reconcile`, `deep`, `merge`, `omit` | `solid-js` |
| `createContext`, `useContext`, `children`, `createUniqueId`, `createRoot`, `getOwner`, `runWithOwner`, `getObserver`, `isDisposed` | `solid-js` |
| `Loading`, `Errored`, `Reveal`, `For`, `Repeat`, `Show`, `Switch`, `Match`, `lazy`, `lazyModule`, `dynamicComponent` | `solid-js` |
| `render`, `hydrate`, `isServer`, `isDev`, `dynamic`, `Portal`, `clientOnly`, `HydrationScript`, `getRequestEvent`, `respond`, `redirect`, `reload`, `markSafeError`, `isHref`, `JSX` (type), `Href` (type) | `@solidjs/web` |
| `GET`, `live`, `broadcast`, `withMeta`, `invoke`, `configureServerFunctionsClient` | `@solidjs/web/server-functions` |
| `createRouter`, `Router`, `paths`, `query`, `revalidate`, `formAction`, `useSubmissions`, `useNavigate`, `useLocation`, `useParams`, `useSearchParams`, `useMatch`, `useRouteMatches`, `useBeforeLeave`, `useIsRouting`, `useLinkState`, `intentPreload`, `pendingLinks`, `RouteProps` (type) | `@solidjs/router` |
| `Title`, `Meta`, `Link` | `@solidjs/meta` |

There is one entry point per layer: every reactive and store export comes from `solid-js`, every DOM, SSR, and request/response export comes from `@solidjs/web`. The old subpath names are listed in [Names removed in 2.0](#names-removed-in-20).

## Naming

- Custom primitives are `createX` and are called during setup: `createDebouncedSignal`, `createCart`, `createMediaQuery`.
- Signal pairs are `[value, setValue]`; accessors read as nouns (`count`, `product`), never `getCount`.
- Booleans are `isX` / `hasX`; event props are `onX`; internal handlers are `handleX`.
- Server reads are `getX` (`getProduct`), writes are `addX` / `saveX` / `updateX`.
- A `query` name matches the noun it caches: `query(getProduct, "product")`. A cache key you cannot guess from the function name is a key you will miss when revalidating.
- Every `createMemo` and `createEffect` that a diagnostic could name takes a `name` matching its identifier: `createMemo(fn, { name: "visible" })` makes the `[why-run]` output and the diagnostics endpoint readable.

## Components

- Ordinary components are function declarations with a typed `props` parameter: `export function Card(props: CardProps)`. Use `Component<P>` only when the component is a value — a map entry, a `dynamic` target, a `lazy` result.
- Default export only for route modules. A component with two exports and a default gives the router a page it did not mean to publish.
- Children contracts: `ParentProps` for ordinary children, `VoidProps` for a component that takes none, `FlowProps` for render-callback children.
- `merge` supplies defaults and `omit` splits rest props; both keep `props` reactive.
- Keep `props` whole and read `props.x` at the point of use. `class` accepts a string, an object, or nested arrays.

## State placement

| Kind | Home | Rule |
| --- | --- | --- |
| Local | Signal or store in the rendering component | Default. Lifting costs only prop passing, because props are reactive. |
| Shared subtree | Store in a context provider, read via `useContext` | Only when a second component needs it. |
| App-wide | A provider mounted once in `App` | Still a provider: a module-scope store is one store per process, not per request. |
| Shareable navigation | Search params | When a copied link must reproduce the view. |
| Authoritative | Server functions and `query` | When the server must decide. |

A context provider module exports `createX()` (state plus actions), the context object, a `Provider`, and a `useX()` hook. Reactive state contexts have no default value: `createContext<Cart>()` makes `useContext` throw `ContextNotFoundError` outside the provider instead of returning a silently dead snapshot. Pass the store and its accessors, never `{ count: cart.items.length }`.

## Async

- Default: an async memo read under a `Loading` boundary. A loading flag, a request counter, and a manual stale-response check are three pieces of state doing what the memo already does.
- Read every reactive input before the first `await` in an async computation; a later read is not tracked, and a later async read throws in development.
- `isPending` on content that is held, `latest` on the control the user touched, a plain read on committed content.
- `Loading on={key()}` only when a subject change should show a fallback again. `on` is tracked, so it must read the signal.
- `createStore(async () => ...)` when a list or tree must keep row identity across a refetch.

## Server

- `"use server"` is the first statement of the function, or of the module for a whole server module. It cannot capture a component variable or a loop variable; pass arguments instead.
- Validate and authorize inside the body. A caller can invoke the endpoint directly, so arguments are untrusted and identity comes from `getRequestEvent()?.locals`, never from an argument.
- `throw respond(value, { status })` for a failure the client should render. A plain `throw new Error(...)` becomes `Internal Server Error` in production, and a returned `respond(..., { status: 400 })` resolves successfully at the call site.
- `redirect` and `reload` are control flow: return them for success, throw them for an early exit. Each accepts `{ revalidate }`.
- `markSafeError` only wraps an error you constructed.
- Cacheable reads use `GET()` outside `query`, or `query()` for a shared, revalidatable read.

## Forms

- `formAction` from `@solidjs/router` for every form. The core `action` from `solid-js` is the reactive transaction wrapper and has no URL, so `action={coreAction}` does not type-check and reloads the page if it runs.
- Inputs stay uncontrolled with `name` attributes; `required` and `pattern` cover UX only, and the server re-validates the parsed `FormData` with a schema.
- `useSubmissions(action)` gives settled submissions for inline errors; the router sets `aria-busy` while a call is in flight, so pending styling is CSS only.
- Optimistic writes go inside an `action` before the `yield`, on a `createOptimisticStore`.

## Routing

- Links are plain `<a href>`; the router intercepts same-origin navigation. `useNavigate` is for navigation that is a consequence of an action.
- Build every URL with `paths`; a renamed route then fails the type check instead of the link.
- Shareable view state goes in search params with a route `search` schema; the schema validates input, so the server validates again.
- A route `preload` starts work and returns `void`; the page reads the same data reactively.
- Guards go in three layers: authorization inside every server function, a pathless route for navigation, middleware for a full page request.

## Lists

- Store-backed data, or a stable key. `For` for identity lists, `Repeat` for positional windows.
- Filter and sort as a derived array, never as stored state.
- Selection is a store keyed by id, not one signal read by every row.

## Tooling

- `tsconfig.json`: `jsx: "preserve"`, `jsxImportSource: "@solidjs/web"`, `strict: true`. The `JSX` namespace comes from `@solidjs/web`.
- Enable `eslint-plugin-solid/configs/v2` (or `v2-strict`) and run the linter after an edit; it reports destructured props, a single-argument effect, a store write outside the setter, and a write in a pure computation before the code runs.
- Enable `diagnostics: true` in the `@solidjs/vite-plugin` options: the dev server then serves `/__solid/diagnostics` for `begin`, `end`, `active`, `whyDidRun`, and `costs`.
- Name memos and effects, so attribution and the endpoint report identifiers instead of anonymous scopes.
- Tests call `flush()` after an interaction before asserting; the DOM updates in a microtask batch.

## Anti-patterns (review checklist)

Every row is a defect to fix, not a preference. The code is the consequence.

### Reads and writes

| Avoid | Why it fails | Prefer |
| --- | --- | --- |
| Reading a reactive value in the component body | One-time snapshot; `[STRICT_READ_UNTRACKED]` | Read in JSX, a memo, or an effect's compute function, or return a derived function |
| Destructuring props, or `const quantity = props.quantity` | The getter is read once; the value freezes | Keep `props` and read `props.quantity` where it is used |
| Passing an accessor where a value is expected: `<Results query={query} />` | The child renders a function or nothing, and never updates | Call it at the attribute: `query={query()}` |
| Writing the store proxy directly: `cart.items.push(x)` | The write is silently ignored | Write on the setter's draft |
| A path setter: `setCart("coupon", "SAVE10")` or `setCart("items", 0, "quantity", 2)` | 2.0 has no path setters; the call cannot type-check | Write the same path on the draft: `setCart((draft) => { draft.coupon = "SAVE10"; })` |
| Rebuilding a collection inside a store setter: `draft.items = draft.items.map(...)` | New objects rebuild every row; `[IMMUTABLE_UPDATE_IN_STORE]` | Mutate the one property that changed |
| Writing a signal from a memo, a compute function, or the component body | `[REACTIVE_WRITE_IN_OWNED_SCOPE]` | Write from an event handler, `onSettled`, or an `action` |
| An effect copying one signal into another | The copy lags by one flush; `[EFFECT_RELAY_TEAR]` | Derive it with a memo or function, or use a writable derivation |

### Effects and ownership

| Avoid | Why it fails | Prefer |
| --- | --- | --- |
| `createEffect(fn)` with one argument | `[MISSING_EFFECT_FN]` | `createEffect(compute, apply)` |
| Reading a second dependency inside the effect function | Untracked, so the effect does not re-run | Read every input in `compute` |
| Creating an effect or primitive in an event handler or ref callback | No owner, never disposed; `[NO_OWNER_EFFECT]`, `[NO_OWNER_CLEANUP]` | Create it during setup and gate it on a signal |
| `onCleanup` inside `onSettled` | `[CLEANUP_IN_FORBIDDEN_SCOPE]` | Return the cleanup from `onSettled` |
| Creating primitives inside `onSettled` | `[PRIMITIVE_IN_FORBIDDEN_SCOPE]` | Create them in the component body |
| `createRoot` to share app state | Manual lifetime, no request scope | A context provider |

### Async

| Avoid | Why it fails | Prefer |
| --- | --- | --- |
| A loading flag plus a request counter plus manual stale-response discard | Races, and three sources of truth for one request | An async memo: it returns the request and drops superseded results |
| Reading a reactive value after the first `await` in an async computation | The dependency is never tracked; a dev error fires | Read every input before the first `await` |
| Reading an async value in the component body | `[PENDING_ASYNC_UNTRACKED_READ]` | Read it under `Loading` in JSX |
| An async read with no `Loading` above it | The root holds; `[ASYNC_OUTSIDE_LOADING_BOUNDARY]` | Add the boundary around that region |
| `on={accessor}` | Reads nothing, so the boundary never re-arms | `on={accessor()}` |
| The same data read outside a `Loading on` boundary | The fallback can never show; `[LOADING_ON_OUTSIDE_HOLD]` | Move every reader inside the boundary |
| A manual `AbortController` with no `onCleanup` | The request outlives the run that started it | Register cleanup before the first `await` |
| `isPending` as the only read of a value | The error is swallowed and never reported | Keep a plain read inside `Errored` |

### State and lists

| Avoid | Why it fails | Prefer |
| --- | --- | --- |
| A module-scope signal or store under SSR | Shared by every request and never disposed; `[SERVER_WRITE]`, data leaks | Create it in a provider or per request |
| A context value built from a snapshot: `{ count: cart.items.length }` | Readers never update | Pass the store and its accessors |
| A context with a silent default for reactive state | The missing-provider bug hides until the page is wrong | `createContext<T>()` with no default |
| Local UI state in the URL or a global store | Wrong lifetime; every keystroke becomes history or shared state | Keep it local; URL only for shareable navigation state |
| New objects per update handed to `For` | Every row rebuilds; `[UNSTABLE_LIST_IDENTITY]` | Store-backed data, `reconcile`, or `keyed={(item) => item.id}` |
| Selection as one signal read by every row | Fan-out to the whole list; `[HUGE_FAN_OUT]` | A selection store keyed by id |
| A filtered or sorted list stored in a signal | Stale duplicate state that drifts | Derive it |
| `Repeat` for a list that reorders | Rows are positional, so state lands on the wrong item | `For` |

### SSR

| Avoid | Why it fails | Prefer |
| --- | --- | --- |
| `window`, `document`, or `localStorage` in the body or module scope | `window is not defined`, and the server render dies | `onSettled`, an effect function, `isServer`, or `clientOnly` |
| `Math.random()`, `Date.now()`, `crypto.randomUUID()`, `navigator.language` deciding structure | Hydration mismatch | Compute it once on the server and pass it as data |
| A counter or random value for `id` / `for` | Hydration mismatch | `createUniqueId()` |
| Nesting the browser rewrites: a `<div>` inside `<p>`, a `<tr>` in a `<table>` without `<tbody>` | Structure mismatch during hydration | Use valid HTML nesting |

### Server and forms

| Avoid | Why it fails | Prefer |
| --- | --- | --- |
| `"use server"` capturing a component variable | Build error: the body cannot reference it | Pass it as an argument |
| Trusting arguments, or a caller-supplied identity | Auth bypass: the caller reaches the endpoint directly | Read identity from `getRequestEvent()?.locals` and validate every input |
| A plain `throw new Error(...)` for a user-visible failure | Production renders `Internal Server Error` | `throw respond(value, { status })` |
| Returning `respond(..., { status: 400 })` for a failure | The caller resolves successfully and renders stale success | Throw it |
| `action={coreAction}` on a form | Type error, and no URL to post to | `formAction` from `@solidjs/router` |
| An open redirect from a `next` parameter | Phishing through your domain | `safeNext` on the server, single-slash same-origin paths only |

### Routing and rendering

| Avoid | Why it fails | Prefer |
| --- | --- | --- |
| String-concatenated hrefs | Break silently when a route is renamed | `paths.x(...)` |
| A `preload` that returns data | Captured once, stale after a param change | `void getX(...)`, read reactively in the page |
| `useNavigate` for an ordinary link | Loses anchor semantics, middle-click, and `href` | `<a href>` |
| `Loading` around the whole page | One slow region hides everything | A boundary per region |
| An async read above every boundary in SSR | The whole shell waits for it | A boundary around the region; `deferStream` only for crawler-critical reads |

## Names removed in 2.0

Check this table when code from memory uses an old name; it is a name check, not an upgrade walkthrough.

| Removed | Use instead |
| --- | --- |
| `solid-js/web` | `@solidjs/web` |
| `solid-js/store` | `solid-js` |
| `Suspense` | `Loading` |
| `SuspenseList` | `Reveal` |
| `ErrorBoundary` | `Errored` |
| `mergeProps` | `merge` |
| `splitProps` | `omit` |
| `unwrap` | `snapshot` |
| `onMount` | `onSettled` |
| `createResource` | An async `createMemo`, or `createStore(fn)`, read under `Loading` |
| `createSelector` | `createProjection` |
| `createComputed` | `createMemo`, or a two-function `createEffect` |
| `batch` | Automatic microtask batching; `flush()` applies staged writes now |
| `on()` | The compute half of `createEffect` |
| `startTransition` / `useTransition` | Built-in held updates plus `isPending()` |
| `Index` | `<For keyed={false}>` |
| `indexArray` | `mapArray` |
| `createMutable` | `createStore` with draft setters |
| `onError` / `catchError` | `<Errored>`, or the `error` option of `createEffect` |
| `classList` | `class={{ active: isActive() }}` |
| `use:` directives | `ref={factory(args)}` |
| `Context.Provider` | `<Context value={...}>` |
| `equalFn` | `isEqual` |
| `getListener` | `getObserver` |

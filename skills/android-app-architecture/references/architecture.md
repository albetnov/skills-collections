# Architecture

Module layout, layer rules, Metro graph setup, platform wiring, and ViewModel injection. One file on purpose: every branch here (layout, wiring, scoping, tests) reads the same three contracts.

## Modules and layers

```
:app                    Single Activity, navigation graph, Application subclass
:feature:home           Screens, ViewModels, navigation entry for one feature
:core:ui                Theme, shared Composables, design-system components
:core:domain            Use cases, domain models, repository interfaces (pure Kotlin)
:core:data              Repository implementations, Retrofit APIs, Room DAOs
```

Dependency rules, enforced by module `implementation` edges, not by convention:

| Module | May depend on | Must never import |
| --- | --- | --- |
| `:app` | everything (wiring only) | business logic of its own |
| `:feature:*` | `:core:domain`, `:core:ui`, navigation contracts | another `:feature:*` internal, `:core:data` |
| `:core:ui` | `:core:domain` models for display | `:core:data`, ViewModels |
| `:core:domain` | Kotlin stdlib, coroutines/`Flow` | `android.*`, Retrofit, Room |
| `:core:data` | `:core:domain`, libraries | `:feature:*`, `:core:ui` |

A repository interface lives in `:core:domain` next to the use case that calls it; its implementation lives in `:core:data` and is contributed into the graph. Features receive the interface, never the implementation type.

## Metro setup

Apply the Gradle plugin; it adds the runtime and wires the compiler plugin. Pin the version once in the version catalog under a `metro` reference rather than scattering literals:

```kotlin
// settings / catalog (symbolic version, resolve at build time)
plugins {
  id("dev.zacsweers.metro")
}
```

A scope is a marker annotation; declare one per lifetime (typically just `AppScope` plus one per logged-in-style extension):

```kotlin
@Scope
annotation class AppScope
```

The graph is an interface annotated with `@DependencyGraph`. Its scope doubles as the aggregation scope: `@ContributesBinding(AppScope::class)` implementations resolve into it automatically. Accessors are the graph's public surface — expose interfaces and ViewModel factories, never third-party types directly:

```kotlin
@DependencyGraph(AppScope::class)
interface AppGraph : ViewModelGraph, MetroAppComponentProviders {
  val homeRepository: HomeRepository
}
```

Prefer `@Inject` constructors for everything owned; reserve `@Provides` for foreign types, grouped in a contributed binding container so they join every matching graph without graph boilerplate:

```kotlin
@Inject
class HomeRepositoryImpl @Inject constructor(
  private val api: ShopApi,
) : HomeRepository

@ContributesTo(AppScope::class)
@BindingContainer
object NetworkBindings {
  @Provides
  fun provideShopApi(client: OkHttpClient): ShopApi = ...

  @Provides
  fun provideOkHttpClient(cache: Cache): OkHttpClient = ...
}
```

Use explicit `@Binds` in the graph only when the binding needs graph-local qualification (a qualified variant of an interface, a test-only override point). A `@Provides` return type must be explicit; providers cannot be overridden by subtypes.

### Scoping

`@SingleIn(AppScope::class)` on the class or provider caches one instance per graph of that scope. Rules: an unscoped graph exposes no scoped bindings; a scoped binding's scope must equal the graph's scope. For in-memory caches tied to app lifetime, scope the repository implementation, not the graph accessor.

For a logged-in subgraph with its own lifetime, use a `@GraphExtension` reached through an accessor or factory on the parent graph; it inherits parent bindings and adds its own. Parent-private implementation details stay hidden with `@GraphPrivate`.

### Runtime inputs

Values known only at runtime (user id, build config) cross through a `@DependencyGraph.Factory`: `@Provides`-annotated parameters become bindings, `@Includes`-annotated parameters expose another type's accessors. Create them with `createGraphFactory()`:

```kotlin
@DependencyGraph.Factory
fun interface Factory {
  fun create(@Provides userId: UserId): AppGraph
}
```

## Application and Activity wiring

The `Application` creates the graph once and implements `MetroApplication`; the graph implements `MetroAppComponentProviders` so the MetroX `AppComponentFactory` can constructor-inject Activities and Services (requires min SDK 28). Constructor-injected components are contributed with the matching map key (`@ActivityKey`, `@ServiceKey`, and friends):

```kotlin
@ContributesIntoMap(AppScope::class, binding<Activity>())
@ActivityKey
class MainActivity @Inject constructor(
  private val metroVmf: MetroViewModelFactory,
) : ComponentActivity()
```

If the project uses a custom `AppComponentFactory`, exclude Metro's in the manifest with `tools:replace` and replicate its lookup.

## ViewModels in Compose

Setup order: graph extends `ViewModelGraph`; one `@Inject @SingleIn` `MetroViewModelFactory` subclass carries the three provider maps; each ViewModel is `@Inject` plus `@ViewModelKey @ContributesIntoMap(AppScope::class)`; the Activity provides the factory through `LocalMetroViewModelFactory`; screens call `metroViewModel()`. Assisted ViewModels (navigation arguments) use `@AssistedInject` with a `@ViewModelAssistedFactoryKey` factory and `assistedMetroViewModel()` at the call site. When an intermediate base class would otherwise capture the binding, bind explicitly to `binding<ViewModel>()`.

## Testing

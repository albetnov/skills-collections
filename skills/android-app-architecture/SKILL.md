---
name: android-app-architecture
description: "Compose-first Android app structure with Metro DI. Use when laying out feature modules and layers, placing UI/domain/data code, defining Metro graphs and bindings, scoping singletons, injecting ViewModels in Compose, or reviewing layer violations."
---

# Android app architecture

Prescriptive structure for new or restructured Android apps: single-Activity Compose UI, a pure-Kotlin domain core, data hidden behind consumer-owned interfaces, and one Metro graph owning all wiring. Data-runtime patterns (Retrofit/Room setup, paging, offline cache, error mapping) live in the `android-data-layer` skill; build the skeleton here first, then reach for it.

This skill supersedes the legacy Hilt + Fragments shape (Hilt plugins, `@HiltAndroidApp` / `@AndroidEntryPoint`, Fragment-hosted UI). The replacement rule is simple: Metro's Gradle plugin instead of Hilt/KSP, constructor injection everywhere instead of field injection, and Compose screens instead of Fragments. Derived from [awesome-android-agent-skills](https://github.com/new-silvermoon/awesome-android-agent-skills) under Apache-2.0; substantially rewritten, no upstream text reproduced.

## The model

Dependencies point inward: `UI -> domain -> data`. Each layer programs against the next layer's interfaces and never names its implementations. A Metro `@DependencyGraph` is the only place implementations meet interfaces: `@Inject` constructors advertise what a class needs, `@Provides` containers cover what you cannot construct, `@ContributesBinding` files the implementation under its interface, and the graph resolves the rest at compile time. The `Application` holds the graph; the Activity reads it; Compose screens read ViewModels. Nothing else holds a reference to anything.

## Non-negotiables

1. Compose-only UI layer. One Activity hosts the app; screens are `@Composable` functions. No Fragments, no `@AndroidEntryPoint` field injection.
2. Layers depend strictly inward: UI depends on domain, domain depends on nothing Android, data implements domain-owned interfaces. Data never imports UI; domain never imports data or `android.*`.
3. Domain is pure Kotlin: use cases, domain models, and repository interfaces only. No `android.*` imports, no framework types in signatures.
4. ViewModel owns `StateFlow`. Screens collect immutable `StateFlow` for state and a one-shot event channel for effects. No state hoisting into singletons, no state held in Composables that must survive navigation.
5. Metro graph owns all wiring. Constructor injection (`@Inject`) is the default; `@Provides` exists only for third-party types you cannot annotate. No `object` service locators, no package-level `lateinit` globals, no manual `new`-up wiring in Activities.
6. Interfaces are bound once, in one way. Prefer `@ContributesBinding(Scope::class)` on the `@Inject` implementation; use an explicit `@Binds` accessor in the graph only when the binding needs graph-local qualification.
7. Scope matches graph. A `@SingleIn(AppScope::class)` binding lives only in a graph declared with that scope. Unscoped graphs expose no scoped bindings.
8. Feature-module layout. A feature owns its screens, ViewModels, and navigation entry; shared UI lives in `:core:ui`, contracts in `:core:domain`, implementations in `:core:data`. Features never import each other's internals.
9. Main wires, nothing dangles. The `Application` creates the graph once in `onCreate` and exposes it; Activities resolve the factory from the graph. No dependency outlives the graph that made it.
10. Repository interfaces are consumer-owned. The interface lives in domain beside the use case that calls it; the data layer implements it and contributes the implementation. Repositories expose main-safe `suspend` functions and `Flow`s; dispatcher switches live inside data, never in ViewModels.

## Canonical shapes

One graph, created once, read everywhere:

```kotlin
@DependencyGraph(AppScope::class)
interface AppGraph : ViewModelGraph, MetroAppComponentProviders {
  val homeRepository: HomeRepository
}

class ShopApp : Application(), MetroApplication {
  private lateinit var appGraph: AppGraph

  override fun onCreate() {
    super.onCreate()
    appGraph = createGraph<AppGraph>()
  }

  overner
object NetworkBindings {
  @Provides
  fun provideShopApi(client: OkHttpClient): ShopApi = ...
}
```

Activity as entry point, Compose as UI, ViewModel from the graph:

```kotlin
@Inject
@ViewModelKey
@ContributesIntoMap(AppScope::class)
class HomeViewModel(
  private val homeRepository: HomeRepository,
) : ViewModel() {
  private val _uiState = MutableStateFlow(HomeUiState.Loading)
  val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()
}

@Inject
class MainActivity(
  private val metroVmf: MetroViewModelFactory,
) : ComponentActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    setContent {
      CompositionLocalProvider(LocalMetroViewModelFactory provides metroVmf) {
        ShopNav()
      }
    }
  }
}

@Composable
fun HomeScreen(viewModel: HomeViewModel = metroViewModel()) {
  val state by viewModel.uiState.collectAsStateWithLifecycle()
  ...
}
```

Runtime inputs cross the graph boundary through a factory, never through globals:

```kotlin
@DependencyGraph(AppScope::class)
interface AppGraph {
  val sessionRepository: SessionRepository

  @DependencyGraph.Factory
  fun interface Factory {
    fun create(@Provides userId: UserId): AppGraph
  }
}

val graph = createGraphFactory<AppGraph.Factory>().create(UserId("u1"))
```

## Reference router

| Task | Read |
| --- | --- |
| Module layout, layer boundaries, graph setup, scoping, Application/Activity wiring, ViewModel injection, testing | [architecture](references/architecture.md) |

Read `architecture.md` before creating modules, defining a graph, or reviewing a diff for layer violations.

## Red flags

- A Fragment, framework field injection into an Activity, or a ViewModel not contributed through the graph.
- An `import android.*` inside `:core:domain` or any domain file.
- A repository interface implemented in the UI layer, or a ViewModel importing a DAO, Retrofit API, or Room entity.
- Field injection (`@Inject lateinit var`) instead of constructor injection.
- An `object` locator, a top-level `lateinit var graph`, or `ClassName()` manual wiring inside an Activity or Composable.
- A `@Provides` function for a class the project owns (give it an `@Inject` constructor instead).
- A scoped binding (`@SingleIn`) exposed from an unscoped graph, or a scope mismatch between binding and graph.
- Mutable state (`MutableStateFlow`, `mutableStateOf`) exposed publicly from a ViewModel, or state held in a Composable that must survive navigation.
- A feature module importing another feature's internals (`feature.cart.internal`).
- `Dispatchers.IO` (or any dispatcher switch) inside a ViewModel.
- A ViewModel contributed without `@ViewModelKey` / `@ContributesIntoMap`, or read via `viewModel()` instead of `metroViewModel()` under the provided factory.

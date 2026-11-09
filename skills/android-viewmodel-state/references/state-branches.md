# State branches

Vanilla+ is the default. Orbit MVI is the upgrade path for concurrency. Reach this file when the router sends you; pick one branch per screen.

## Vanilla+ shapes

Single immutable state surface: the ViewModel owns a private mutable implementation of a public read-only interface (or a data class of snapshot-backed fields). Compose reads the snapshot State directly — no `collectAsState` call is needed for snapshot reads because reads inside composition already subscribe.

List/detail with loading and error:

```kotlin
data class NewsUiState(
  val isLoading: Boolean = true,
  val articles: List<Article> = emptyList(),
  val error: String? = null,
)

class NewsViewModel @Inject constructor(
  private val repository: NewsRepository,
) : ViewModel() {
  var uiState by mutableStateOf(NewsUiState())
    private set

  fun refresh() = viewModelScope.launch {
    uiState = uiState.copy(isLoading = true, error = null)
    runCatching { repository.latest() }
      .onSuccess { uiState = NewsUiState(isLoading = false, articles = it) }
      .onFailure { uiState = uiState.copy(isLoading = false, error = it.message) }
  }
}

@Composable
fun NewsScreen(viewModel: NewsViewModel = metroViewModel()) {
  NewsContent(state = viewModel.uiState, onRefresh = viewModel::refresh)
}
```

One-shot events in vanilla+: a `SharedFlow` never replays, a `Channel` delivers exactly once. Prefer the channel for navigation and snackbar effects:

```kotlin
class EditViewModel : ViewModel() {
  private val _effects = Channel<EditEffect>(Channel.BUFFERED)
  val effects: Flow<EditEffect> = _effects.receiveAsFlow()

  fun save() = viewModelScope.launch {
    repository.save()
    _effects.send(EditEffect.NavigateBack)
  }
}

@Composable
fun EditScreen(viewModel: EditViewModel = hiltViewModel()) {
  LaunchedEffect(Unit) { viewModel.effects.collect(::handleEffect) }
  EditContent(state = viewModel.state, onSave = viewModel::save)
}
```

Vanilla+ test: advance coroutines, then assert the snapshot:

```kotlin
@Test
fun refreshEmitsArticles() = runTest {
  viewModel.refresh()
  advanceUntilIdle()
  assertEquals(listOf(article), viewModel.uiState.articles)
}
```

## Orbit shapes

Use when the gate fires: two or more racing intents, cancel/retry flows, exactly-once ordered effects, shared KMP logic. The container serializes intents, so concurrent `intent` blocks reduce in order instead of interleaving writes.

State, side effect, and container:

```kotlin
data class SearchState(
  val query: String = "",
  val results: List<Result> = emptyList(),
  val isLoading: Boolean = false,
)

sealed interface SearchEffect {
  data class OpenResult(val id: String) : SearchEffect
}

class SearchViewModel @Inject constructor(
  private val repository: SearchRepository,
) : ViewModel(), ContainerHost<SearchState, SearchEffect> {
  override val container = container<SearchState, SearchEffect>(SearchState())

  fun onQueryChange(query: String) = intent {
    reduce { state.copy(query = query) }
  }

  fun search() = intent {
    reduce { state.copy(isLoading = true) }
    runCatching { repository.search(state.query) }
      .onSuccess { reduce { state.copy(isLoading = false, results = it) } }
      .onFailure { reduce { state.copy(isLoading = false) } }
  }

  fun open(result: Result) = intent {
    postSideEffect(SearchEffect.OpenResult(result.id))
  }
}
```

Compose subscription on pure Android:

```kotlin
@Composable
fun SearchScreen(viewModel: SearchViewModel = metroViewModel()) {
  val state by viewModel.collectAsState()
  viewModel.collectSideEffect { effect ->
    when (effect) {
      is SearchEffect.OpenResult -> navigator.open(effect.id)
    }
  }
  SearchContent(state = state, onQuery = viewModel::onQueryChange)
}
```

`collectAsState` and `collectSideEffect` follow the composable lifecycle and subscribe only when the view is at least `STARTED`.

Orbit test: assert the ordered state and side-effect sequence:

```kotlin
@Test
fun searchEmitsLoadingThenResults() = runTest {
  viewModel.test(SearchState()) {
    run("search") { viewModel.search() }
    expectState(SearchState(isLoading = true))
    expectState(SearchState(results = listOf(result)))
    expectNoSideEffects()
  }
}
```

## Gate examples

Stays vanilla+: settings form with one save path; article list with pull-to-refresh as the only producer; detail screen loading one repository call.

Moves to Orbit: search-as-you-type where keystrokes race the in-flight request; checkout where submit, retry, and cancel touch the same `isPlacingOrder` flag; a flow that must emit loading, then either results or exactly one error effect, in order.

## KMP note

Orbit's `ContainerHost` lives in `commonMain`, so the container, intents, and `orbit-test` assertions can be shared with iOS and desktop. Vanilla+ snapshot State stays Android-only. When the shared-logic row of the gate fires, put the Orbit container in `commonMain` and keep only the `collectAsState` / `collectSideEffect` subscription in Android code.

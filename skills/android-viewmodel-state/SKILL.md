---
name: android-viewmodel-state
description: "Per-screen ViewModel state for Compose: snapshot State or Orbit MVI. Use when choosing vanilla snapshot State vs Orbit MVI for a screen, exposing immutable ViewModel state, handling one-shot events, writing ViewModel or Orbit container tests, or sharing state logic in KMP commonMain."
---

# Android ViewModel state

Pick one pattern per screen, then follow it. Compose-only; no XML section. The legacy `StateFlow` plus `SharedFlow` plus XML pattern is superseded by the two branches below. Derived from [awesome-android-agent-skills](https://github.com/new-silvermoon/awesome-android-agent-skills) under Apache-2.0; substantially rewritten, no upstream text reproduced.

## Decision gate

Default to vanilla+ when the screen is unknown, simple, CRUD, or single-producer. Choose Orbit MVI when the screen has two or more racing intents, cancel or retry flows, exactly-once ordered effects, or shared KMP logic.

| Screen | Branch |
|---|---|
| Unknown during triage, simple form, CRUD list/detail, one producer of state | Vanilla+ snapshot State |
| Two or more racing intents on shared state | Orbit MVI |
| Cancel, retry, debounce, or `collectLatest` flow logic | Orbit MVI |
| Exactly-once ordered one-shot effects under concurrency | Orbit MVI |
| State logic shared with iOS/desktop via KMP `commonMain` | Orbit MVI |

Both branches coexist in one app. One screen uses exactly one branch, never both. Migration trigger: the moment a second racing intent lands on a vanilla+ screen, move that screen to Orbit.

## Non-negotiables

1. The public state surface is immutable. Compose sees reads only; every write path goes through the ViewModel.
2. Launch all ViewModel work in `viewModelScope` (Orbit `intent` blocks already do this).
3. One-shot events are never replayed. A recreated screen or second collector sees current state, never a stale event.
4. No dispatcher switches in the ViewModel. Repositories and dispatchers already live behind the data-layer and architecture skills; the ViewModel calls suspend functions and never names `Dispatchers`.
5. Vanilla+ tests assert the state snapshot after advancing coroutines; Orbit tests assert the ordered state and side-effect sequence.
6. One screen, one `ViewModel`, one state holder. Cross-screen sharing goes through the repository, not a shared ViewModel.

## Canonical shapes

Vanilla+ state — ViewModel exposes a snapshot State interface, Compose reads it directly with no collection call:

```kotlin
interface DetailState {
  val isLoading: Boolean
  val title: String
}

class DetailViewModel : ViewModel() {
  private class MutableState : DetailState {
    override var isLoading by mutableStateOf(false)
    override var title by mutableStateOf("")
  }

  private val mutableState = MutableState()
  val state: DetailState = mutableState

  fun refresh() = viewModelScope.launch {
    mutableState.isLoading = true
    mutableState.title = repository.title()
    mutableState.isLoading = false
  }
}

@Composable
fun DetailScreen(viewModel: DetailViewModel = metroViewModel()) {
  DetailContent(state = viewModel.state)
}
```

Orbit MVI — `ContainerHost` with `intent`, `reduce`, and `postSideEffect`; Compose reads with `collectAsState` and handles effects with `collectSideEffect`:

```kotlin
class CheckoutViewModel : ViewModel(), ContainerHost<CheckoutState, CheckoutEffect> {
  override val container = container<CheckoutState, CheckoutEffect>(CheckoutState())

  fun submit() = intent {
    reduce { state.copy(isPlacingOrder = true) }
    runCatching { checkoutRepository.placeOrder(state.cart) }
      .onSuccess { postSideEffect(CheckoutEffect.NavigateToConfirmation(it.id)) }
      .onFailure { reduce { state.copy(isPlacingOrder = false, error = it.message) } }
  }
}

@Composable
fun CheckoutScreen(viewModel: CheckoutViewModel = metroViewModel()) {
  val state by viewModel.collectAsState()
  viewModel.collectSideEffect { effect ->
    when (effect) {
      is CheckoutEffect.NavigateToConfirmation -> navigator.openConfirmation(effect.orderId)
    }
  }
  CheckoutContent(state = state, onSubmit = viewModel::submit)
}
```

## Reference router

| Task | Read |
|---|---|
| Vanilla+ shapes, one-shot channel events, Orbit state/side-effect/test shapes, gate examples, KMP note | [state-branches](references/state-branches.md) |

## Red flags

- `MutableStateFlow` or `MutableSharedFlow` exposed publicly, or a `StateFlow` used for a navigation event.
- A one-shot event that replays after rotation or reaches a second collector.
- Two state holders for one screen, or one screen mixing snapshot State and an Orbit container.
- `Dispatchers.IO` or `withContext` inside the ViewModel.
- Business logic in the composable, or a composable reaching past the ViewModel into the repository.
- A second racing intent patched onto a vanilla+ screen instead of migrating that screen to Orbit.
- Orbit `intent` calling `postSideEffect` for persistent screen state that belongs in `reduce`.

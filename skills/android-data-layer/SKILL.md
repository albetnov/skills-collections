---
name: android-data-layer
description: "Offline-first Android data layer with Store5, Room, and Retrofit. Use when wiring a repository cache, Room source of truth, Retrofit fetcher, StoreReadResponse tiers, stale-while-revalidate reads, offline writes, or mapping network errors to Result."
---

# Android data layer

Every read flows through Store5. Room is the single source of truth, Retrofit fetches over the network, and `Store<Key, Output>.stream()` emits the cache/network tiers. Store owns the refresh, the tiers, and the write-back. Derived from [awesome-android-agent-skills](https://github.com/new-silvermoon/awesome-android-agent-skills) under Apache-2.0; substantially rewritten, no upstream text reproduced.

## Non-negotiables

1. Route every read through `Store<Key, Output>.stream()`. No manual DAO-plus-API refresh function.
2. Room is the source of truth on pure-Android. The SOT reader returns `Flow<Output?>` from a DAO;
   the writer persists fetcher payloads back through the DAO.
3. Retrofit plus OkHttp is the fetcher on pure-Android, with the kotlinx.serialization converter.
   One `suspend fun` per endpoint; the fetcher returns model types, never `Response` wrappers.
4. Ktor plus ContentNegotiation lives only in shared KMP code, never in an Android-only module.
5. Convert at the boundary: `Converter.fromNetworkToLocal` maps fetcher output to Room entities;
   `Converter.fromOutputToLocal` maps domain writes to entities. Network, local, and output types
   stay distinct.
6. Freshness is a `Validator`, built with `Validator.by { ... }`. Store re-fetches invalid items;
   network responses themselves are never validated.
7. Writes land in the source of truth first, then sync through a WorkManager outbox. Never mutate
   local state and await the network inline.
8. Consume the stream tiers: `Data` with origin `Cache`, `SourceOfTruth`, or `Fetcher` for
   stale-while-revalidate; `Loading` for in-flight; `NoNewData` when the fetcher is empty;
   `Error` mapped to `Result` or a domain error. Errors never kill the flow.
9. Invalidate with `Store.clear(key)` and `clearAll()` (the latter is experimental). Wire SOT
   `delete`/`deleteAll`, or the purge clears memory only.
10. Proto DataStore is for small key-value config only, never for lists or entities.

## Canonical shapes

Store wiring — fetcher, Room source of truth, converter:

```kotlin
val store = StoreBuilder
  .from(
    fetcher = Fetcher.of(fetch = api::getNews),
    sourceOfTruth = SourceOfTruth.of(
      reader = dao::observeNews,
      writer = { _, network -> dao.upsert(network.map(::toEntity)) },
      delete = dao::clear,
      deleteAll = dao::clearAll,
    ),
    converter = Converter.Builder<NewsDto, NewsEntity, List<News>>()
      .fromNetworkToLocal { dto -> dto.map(::toEntity) }
      .fromOutputToLocal { news -> news.map(::toEntity) }
      .build(),
  )
  .validator(Validator.by { news -> news.isNotEmpty() })
  .build()
```

Stale-while-revalidate read — cached emission first, fetcher refresh alongside:

```kotlin
store.stream(StoreReadRequest.cached(key, refresh = true)).collect { response ->
  when (response) {
    is StoreReadResponse.Data -> render(response.value)
    is StoreReadResponse.Loading -> showRefreshIndicator()
    is StoreReadResponse.NoNewData -> Unit // keep showing cached data
    is StoreReadResponse.Error -> showError(response.errorMessageOrNull())
    is StoreReadResponse.Initial -> Unit
  }
}
```

## Reference router

| Task | Read |
|---|---|
| Store wiring, Room shapes, Retrofit and Ktor fetchers, write path, error mapping | [data-pipeline](references/data-pipeline.md) |

## Red flags

- A repository holding both a DAO and an API with a manual `refresh()` or `sync()` function.
- A fetcher that throws instead of returning `FetcherResult.Error`; Store never catches those.
- A DAO entity reused as the network DTO or the domain model.
- Ktor client code in an Android-only module.
- Lists or entities stored in DataStore.
- `StoreReadResponse.Error` or `NoNewData` unhandled, or the flow rebuilt per emission.
- `clear(key)` expected to wipe Room without an SOT `delete` wired.
- Business logic branching on `StoreReadResponseOrigin.Fetcher.name` outside a fallback setup.

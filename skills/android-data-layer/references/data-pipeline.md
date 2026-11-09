# Data pipeline

Store5 owns the read path end to end: `Fetcher` fetches, `Converter` translates, `SourceOfTruth`
persists, `Store.stream()` emits. Room backs the SOT on pure-Android; Retrofit feeds the fetcher
on pure-Android; Ktor appears only in shared KMP code. Versions below are symbolic — resolve the
current release in the version catalog at setup time.

## Dependencies (symbolic)

```toml
# Store5 (group verified; pin the current release)
# org.mobilenativefoundation.store:store5
# Room + KSP (pure-Android)
# com.google.devtools.ksp plugin, androidx.room:room-runtime + room-compiler
# Network (pure-Android default)
# com.squareup.retrofit2:retrofit + first-party kotlinx-serialization converter + okhttp
```

The third-party `retrofit2-kotlinx-serialization-converter` is deprecated upstream in favor of
Retrofit's first-party kotlinx-serialization converter — use the first-party artifact.

## Room source of truth

Entities are persistence models only, never network or domain types:

```kotlin
@Entity(tableName = "news")
data class NewsEntity(
  @PrimaryKey val id: String,
  val title: String,
  val synced: Boolean = true,
)

@Dao
interface NewsDao {
  @Query("SELECT * FROM news ORDER BY id")
  fun observeAll(): Flow<List<News>>

  @Upsert
  suspend fun upsert(rows: List<NewsEntity>)

  @Query("DELETE FROM news WHERE id = :key")
  suspend fun clear(key: String)

  @Query("DELETE FROM news")
  suspend fun clearAll()
}
```

Pure-Android database (KSP processes `@Entity`/`@Dao`; KMP needs platform builders instead):

```kotlin
@Database(entities = [NewsEntity::class], version = 1)
abstract class AppDatabase : RoomDatabase() {
  abstract fun newsDao(): NewsDao
}

val db = Room.databaseBuilder(context, AppDatabase::class.java, "app.db").build()
```

Wire the SOT with the flowing overload so Room's `Flow` drives collectors; `delete`/`deleteAll`
are what let `Store.clear(key)` / `clearAll()` reach disk (otherwise the purge is memory-only,
and `clearAll()` stays behind the experimental API gate):

```kotlin
SourceOfTruth.of(
  reader = { dao.observeAll() },
  writer = { _, network: List<NewsDto> -> dao.upsert(network.map(::toEntity)) },
  delete = { dao.clear(it) },
  deleteAll = dao::clearAll,
)
```

## Fetchers

Pure-Android default is Retrofit with the kotlinx.serialization converter — one `suspend fun` per
endpoint, model types in and out:

```kotlin
interface NewsApi {
  @GET("news")
  suspend fun getNews(): List<NewsDto>
}

val retrofit = Retrofit.Builder()
  .baseUrl(baseUrl)
  .addConverterFactory(Json.asConverterFactory("application/json".toMediaType()))
  .build()

val fetcher = Fetcher.of(fetch = api::getNews)
```

`Fetcher.of(fetch)` wraps each value in `FetcherResult.Data` and each thrown exception in
`FetcherResult.Error`; thrown exceptions anywhere else propagate untouched. For multi-emission
protocols use `Fetcher.ofFlow(flowFactory)`; for explicit error values build the fetcher with
`Fetcher.ofResult(fetch)` and return `FetcherResult.Data` / `FetcherResult.Error` yourself.

KMP/CMP only — never in an Android-only module:

```kotlin
val client = HttpClient {
  install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
}
```

## Read path

```kotlin
val store = StoreBuilder
  .from(fetcher, sourceOfTruth, converter)
  .validator(Validator.by { news -> news.isNotEmpty() })
  .build()
```

Pick the request per screen need: `StoreReadRequest.cached(key, refresh = true)` is the
stale-while-revalidate default (cache first, fetcher alongside); `fresh(key)` skips caches on
pull-to-refresh; `freshWithFallBackToSourceOfTruth(key)` serves disk when the fetch fails;
`localOnly(key)` disables the fetcher for offline screens; `skipMemory(key, refresh)` bypasses
the in-memory tier. `Validator` decides cached-item freshness — Store re-fetches invalid items
and never validates network responses.

Every `stream()` emission is one tier — handle all five:

- `Data(value, origin)` — render; `origin` is `Cache`, `SourceOfTruth`, or `Fetcher`.
- `Loading(origin)` — refresh indicator; the cached value stays on screen.
- `NoNewData` — fetcher came back empty; keep showing cached data.
- `Error` (`Exception` / `Message` / `Custom`) — map to `Result` or a domain error via
  `errorMessageOrNull()` / `dataOrNull()`; the flow stays alive for the next emission.
- `Initial` — stream opened, nothing yet.

`Converter` keeps the three types apart: `fromNetworkToLocal` maps fetcher output to entities,
`fromOutputToLocal` maps domain writes to entities for `MutableStore` local updates.

## Write path

Local first, network second. Apply the change to the source of truth (direct DAO write so the
observing `reader` re-emits immediately), mark the row unsynced, and enqueue a WorkManager
one-shot with a network constraint to push it:

```kotlin
suspend fun rename(id: String, title: String) {
  dao.updateTitle(id, title, synced = false)
  syncWork.enqueueUnique(id)
}
// Worker: api.rename(id, title); dao.markSynced(id) on success.
```

Map network failures at the worker boundary: retryable (`IOException`, 5xx) rethrows for backoff,
terminal (4xx, validation) marks the row failed with a user-visible error. Never block the UI
write on the network call, and never let the worker write throw terminal errors into an
infinite retry loop.

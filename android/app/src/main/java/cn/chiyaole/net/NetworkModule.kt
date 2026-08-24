package cn.chiyaole.net

import android.content.Context
import cn.chiyaole.BuildConfig
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit

/**
 * `BuildConfig.API_BASE_URL` is debug/release-specific (staging vs. production — see
 * app/build.gradle.kts). `usesCleartextTraffic="false"` in the manifest means both must be
 * HTTPS, which they are — spec §3.1 makes HTTPS mandatory server-side too.
 */
object NetworkModule {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true; encodeDefaults = true }

    @Volatile private var apiService: ApiService? = null

    fun api(context: Context): ApiService =
        apiService ?: synchronized(this) {
            apiService ?: build(context).also { apiService = it }
        }

    private fun build(context: Context): ApiService {
        val auth = DeviceAuth(context)
        val authInterceptor = Interceptor { chain ->
            // ★ Must be X-Device-Token, not "Authorization: Bearer" — confirmed live
            // (server 422s on every device-authenticated call otherwise): app/deps.py's
            // device_patient dependency reads Header(..., alias="X-Device-Token")
            // specifically. FastAPI treats a missing required header as a 422 validation
            // error, not a 401, so this looked like a body/schema problem, not an auth one.
            val request = chain.request().newBuilder().apply {
                auth.deviceToken?.let { addHeader("X-Device-Token", it) }
            }.build()
            chain.proceed(request)
        }
        val logging = HttpLoggingInterceptor().apply {
            level = if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BASIC else HttpLoggingInterceptor.Level.NONE
        }
        val client = OkHttpClient.Builder()
            .addInterceptor(authInterceptor)
            .addInterceptor(logging)
            // ★ OkHttp's 10s default is fine for the JSON endpoints but times out
            // /api/asr and /api/qa in practice — each is a real DashScope round trip
            // (transcribe, then intent classification + phrasing), not a local DB query.
            // Confirmed live: a real hold-to-speak question hit SocketTimeoutException at
            // the default before either call had a chance to return.
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(45, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()

        return Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE_URL)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(ApiService::class.java)
    }
}

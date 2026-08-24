package cn.chiyaole.net

import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

/** Elder-device endpoints only (spec §6.2) — the caregiver-side endpoints (§6.1) belong to
 * the caregiver web page, not this APK. */
interface ApiService {
    @POST("/api/device/register")
    suspend fun register(@Body body: DeviceRegisterRequest): DeviceRegisterOut

    /** PairingActivity — the formal pairing flow, authenticated by a short-lived code
     * instead of an already-known patient_id (see server/app/api/device.py's pair_device
     * docstring). */
    @POST("/api/device/pair")
    suspend fun pair(@Body body: DevicePairRequest): DeviceRegisterOut

    @GET("/api/schedule")
    suspend fun schedule(@Query("since") sinceIso: String): ScheduleOut

    /** Idempotent by each event's client-generated [EventIn.id] — safe to retry (spec §6.2). */
    @POST("/api/events")
    suspend fun postEvents(@Body body: EventsRequest): EventsOut

    /** Raw body, not a typed DTO — [cn.chiyaole.util.RemoteConfigStore.save] parses it, and
     * fields on the device side are a deliberate subset of the full remote_config.json. */
    @GET("/api/config")
    suspend fun config(): ResponseBody

    @GET("/api/doctor-view/{patientId}")
    suspend fun doctorView(@Path("patientId") patientId: String): DoctorViewOut

    /** Hold-to-speak (wireframe C1) uploads the clip here first. No escalation loop on the
     * far side of [qa] — see server/app/api/device.py's module docstring. */
    @Multipart
    @POST("/api/asr")
    suspend fun asr(@Part file: MultipartBody.Part): AsrOut

    @POST("/api/qa")
    suspend fun qa(@Body body: QaRequest): QaOut
}

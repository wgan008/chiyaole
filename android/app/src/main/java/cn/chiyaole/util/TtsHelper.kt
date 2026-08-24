package cn.chiyaole.util

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import java.util.Locale

/**
 * Thin wrapper over Android's on-device system TTS — offline, zero cost, zero latency
 * (spec §2 stack table). Rate is intentionally not below 0.7: "0.85 measured as comfortable
 * for 70+ listeners... below 0.7 starts sounding condescending" (remote_config.json
 * `tts._comment_rate`).
 *
 * Does NOT decide when to speak relative to the screen turning on — spec §3.4-③ requires
 * "screen on, THEN speech, 300-500ms gap" on low-end SoCs; that sequencing is the caller's
 * (AlarmActivity's) responsibility because only it knows when the screen actually turned on.
 */
class TtsHelper(context: Context, config: RemoteConfig.TtsConfig) {
    private var ready = false
    private val pendingUtterances = mutableListOf<Pair<String, () -> Unit>>()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val callbacks = mutableMapOf<String, () -> Unit>()

    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { status ->
        if (status == TextToSpeech.SUCCESS) {
            ready = true
            mainHandler.post {
                pendingUtterances.forEach { (text, onDone) -> doSpeak(text, onDone) }
                pendingUtterances.clear()
            }
        } else {
            Log.e("TtsHelper", "TTS init failed, status=$status")
        }
    }.apply {
        language = Locale.CHINA
        setSpeechRate(config.rate)
        setPitch(config.pitch)
        setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) = Unit
            override fun onDone(utteranceId: String?) {
                val callback = utteranceId?.let { callbacks.remove(it) } ?: return
                mainHandler.post { callback() }
            }
            @Deprecated("required override")
            override fun onError(utteranceId: String?) {
                val callback = utteranceId?.let { callbacks.remove(it) } ?: return
                mainHandler.post { callback() }
            }
        })
    }

    /** [onDone] fires once playback finishes (or fails) — a real completion signal, not a
     * fixed delay guess. Callers that don't care can omit it. */
    fun speak(text: String, onDone: () -> Unit = {}) {
        if (ready) doSpeak(text, onDone) else pendingUtterances.add(text to onDone)
    }

    private fun doSpeak(text: String, onDone: () -> Unit) {
        val utteranceId = "${text.hashCode()}-${System.nanoTime()}"
        callbacks[utteranceId] = onDone
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
    }

    fun shutdown() {
        tts.stop()
        tts.shutdown()
    }
}

package cn.chiyaole.ui

import android.Manifest
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import cn.chiyaole.ChiYaoLeApp
import cn.chiyaole.net.NetworkModule
import cn.chiyaole.net.QaRequest
import cn.chiyaole.ui.components.BigButton
import cn.chiyaole.ui.components.SecondaryButton
import cn.chiyaole.ui.theme.ChiYaoLeTheme
import cn.chiyaole.ui.theme.Dimens
import cn.chiyaole.ui.theme.MutedText
import cn.chiyaole.ui.theme.PrimaryGreen
import cn.chiyaole.ui.theme.SecondaryBg
import cn.chiyaole.util.TtsHelper
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody

/**
 * Hold-to-speak Q&A (wireframe C1/C2/C3) — reinstated without the caregiver-reply loop
 * (C3→C4). A refused question already comes back with a spoken decline that tells the elder
 * to ask their caregiver themselves (agent/qa.py's `_refused`); there is nothing further to
 * wait for, so C2 (can answer) and C3 (can't) share this one result screen instead of the
 * original two.
 *
 * ★ Deliberately NOT a WorkManager job like button-tap confirmations: losing an in-flight
 * question to a process death just means the elder asks again — unlike a medication
 * confirmation, nothing here is lost data that must survive at all costs.
 */
class QaActivity : ComponentActivity() {
    private lateinit var tts: TtsHelper
    private var recorder: MediaRecorder? = null
    private var audioFile: File? = null

    private val requestAudioPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (!granted) {
                Toast.makeText(this, "需要麦克风权限才能问问题", Toast.LENGTH_SHORT).show()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tts = TtsHelper(this, (application as ChiYaoLeApp).remoteConfigStore.current().tts)

        setContent {
            ChiYaoLeTheme {
                var state by remember { mutableStateOf<QaUiState>(QaUiState.Idle) }
                QaScreen(
                    state = state,
                    onBack = { finish() },
                    onPress = {
                        if (hasAudioPermission()) {
                            state = QaUiState.Listening
                            startRecording()
                        } else {
                            requestAudioPermission.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    },
                    onRelease = {
                        if (state is QaUiState.Listening) {
                            state = QaUiState.Processing
                            val file = stopRecording()
                            if (file == null) {
                                state = QaUiState.Error
                            } else {
                                processRecording(file) { result -> state = result }
                            }
                        }
                    },
                    onAskAgain = { state = QaUiState.Idle },
                    onDone = { finish() },
                )
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        tts.shutdown()
        recorder?.let { runCatching { it.release() } }
    }

    private fun hasAudioPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun startRecording() {
        val file = File(cacheDir, "qa_${System.currentTimeMillis()}.m4a")
        audioFile = file
        val r = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(this) else @Suppress("DEPRECATION") MediaRecorder()
        recorder = r
        runCatching {
            r.setAudioSource(MediaRecorder.AudioSource.MIC)
            r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            r.setOutputFile(file.absolutePath)
            r.prepare()
            r.start()
        }.onFailure { Log.e(TAG, "recorder start failed", it) }
    }

    /** Returns null on failure — mirrors AlarmActivity's own `runCatching` + explicit log
     * pattern (a silent MediaRecorder failure on the emulator cost a debugging session
     * earlier in this project; never repeat that with a bare getOrNull()). */
    private fun stopRecording(): File? = runCatching {
        recorder?.apply { stop(); release() }
        recorder = null
        audioFile
    }.onFailure { Log.e(TAG, "recorder stop failed", it) }.getOrNull()

    private fun processRecording(file: File, onResult: (QaUiState) -> Unit) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val api = NetworkModule.api(this@QaActivity)
                val body = file.asRequestBody("audio/mp4".toMediaType())
                val part = MultipartBody.Part.createFormData("file", file.name, body)
                val asr = api.asr(part)
                val qa = api.qa(QaRequest(text = asr.text))
                withContext(Dispatchers.Main) {
                    onResult(QaUiState.Result(question = asr.text, answer = qa.spoken, refused = qa.refused))
                    tts.speak(qa.spoken)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.e(TAG, "qa round-trip failed", e)
                withContext(Dispatchers.Main) { onResult(QaUiState.Error) }
            } finally {
                file.delete()
            }
        }
    }

    private companion object {
        const val TAG = "QaActivity"
    }
}

private sealed class QaUiState {
    object Idle : QaUiState()
    object Listening : QaUiState()
    object Processing : QaUiState()
    object Error : QaUiState()
    data class Result(val question: String, val answer: String, val refused: Boolean) : QaUiState()
}

@Composable
private fun QaScreen(
    state: QaUiState,
    onBack: () -> Unit,
    onPress: () -> Unit,
    onRelease: () -> Unit,
    onAskAgain: () -> Unit,
    onDone: () -> Unit,
) {
    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(Dimens.screenPadding),
        ) {
            // ★ Spec: "All tap. No swiping, anywhere." — the elder can't be relied on to know
            // the system back gesture/button, so every state (including mid-listen) needs an
            // explicit, large way out back to HomeActivity.
            Row(modifier = Modifier.fillMaxWidth()) {
                TextButton(onClick = onBack) {
                    Text(text = "‹ 返回", fontSize = Dimens.minTextSp, fontWeight = FontWeight.Bold)
                }
            }
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = Dimens.buttonSpacing),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                when (state) {
                    is QaUiState.Idle, is QaUiState.Listening ->
                        HoldToSpeakArea(listening = state is QaUiState.Listening, onPress = onPress, onRelease = onRelease)
                    is QaUiState.Processing ->
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            CircularProgressIndicator(color = PrimaryGreen)
                            Text(
                                text = "我在想…",
                                fontSize = Dimens.minTextSp,
                                color = MutedText,
                                modifier = Modifier.padding(top = 16.dp),
                            )
                        }
                    is QaUiState.Error ->
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(text = "没听清，再说一次", fontSize = Dimens.minTextSp, fontWeight = FontWeight.Bold)
                            BigButton(
                                text = "再问一句",
                                backgroundColor = PrimaryGreen,
                                contentColor = Color.White,
                                onClick = onAskAgain,
                                modifier = Modifier.padding(top = Dimens.buttonSpacing),
                            )
                        }
                    is QaUiState.Result ->
                        ResultArea(state = state, onAskAgain = onAskAgain, onDone = onDone)
                }
            }
        }
    }
}

@Composable
private fun HoldToSpeakArea(listening: Boolean, onPress: () -> Unit, onRelease: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = if (listening) "我在听…" else "问一问",
            fontSize = Dimens.primaryTextSp,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = if (listening) "松手就好" else "比如「我今天吃药了没」",
            fontSize = Dimens.minTextSp,
            color = MutedText,
            modifier = Modifier.padding(top = 8.dp, bottom = Dimens.screenPadding),
        )
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(Dimens.buttonMinHeight)
                .background(if (listening) PrimaryGreen else SecondaryBg, RoundedCornerShape(16.dp))
                .pointerInput(Unit) {
                    detectTapGestures(onPress = {
                        onPress()
                        val released = tryAwaitRelease()
                        if (released) onRelease()
                    })
                },
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = if (listening) "松开" else "按住说话",
                fontSize = Dimens.minTextSp,
                fontWeight = FontWeight.Bold,
                color = if (listening) Color.White else PrimaryGreen,
            )
        }
    }
}

@Composable
private fun ResultArea(state: QaUiState.Result, onAskAgain: () -> Unit, onDone: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        // ★ Shows the raw ASR transcript first (wireframe C2 annotation) so the elder can
        // notice a mis-transcription rather than just get a confidently-wrong answer.
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(SecondaryBg, RoundedCornerShape(8.dp))
                .padding(12.dp),
        ) {
            Text(text = "你问：${state.question}", fontSize = Dimens.minTextSp, color = MutedText)
        }
        Text(
            text = state.answer,
            fontSize = Dimens.primaryTextSp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(vertical = Dimens.screenPadding),
        )
        SecondaryButton(text = "再问一句", onClick = onAskAgain, modifier = Modifier.fillMaxWidth())
        BigButton(
            text = "知道了",
            backgroundColor = PrimaryGreen,
            contentColor = Color.White,
            onClick = onDone,
            modifier = Modifier.padding(top = Dimens.buttonSpacing),
        )
    }
}

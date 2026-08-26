package cn.chiyaole.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.lifecycleScope
import cn.chiyaole.net.DeviceAuth
import cn.chiyaole.net.DevicePairRequest
import cn.chiyaole.net.NetworkModule
import cn.chiyaole.net.SyncWorker
import cn.chiyaole.ui.components.BigButton
import cn.chiyaole.ui.theme.ChiYaoLeTheme
import cn.chiyaole.ui.theme.Dimens
import cn.chiyaole.ui.theme.MutedText
import cn.chiyaole.ui.theme.PrimaryGreen
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * First-run pairing (formal replacement for the old debug-only "connect test server"
 * button, which only ever worked against a hardcoded patient over an emulator-only
 * address). Launched by [HomeActivity] whenever [DeviceAuth.isRegistered] is false, before
 * anything else — a doses-of-today screen has nothing to show for a device that isn't
 * attached to a patient yet.
 *
 * The caregiver generates a short-lived, single-use code on setup.html and reads it aloud
 * to whoever is installing this APK; POST /api/device/pair exchanges it for a device_token
 * (server/app/api/device.py's pair_device docstring covers the "why not just the
 * patient_id" reasoning).
 */
class PairingActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            ChiYaoLeTheme {
                var code by remember { mutableStateOf("") }
                var loading by remember { mutableStateOf(false) }
                var error by remember { mutableStateOf<String?>(null) }

                PairingScreen(
                    code = code,
                    loading = loading,
                    error = error,
                    onCodeChange = { code = it.filter(Char::isDigit).take(6); error = null },
                    onSubmit = {
                        if (code.length != 6) {
                            error = "配对码是 6 位数字"
                        } else {
                            pair(code, setLoading = { loading = it }, setError = { error = it })
                        }
                    },
                )
            }
        }
    }

    private fun pair(code: String, setLoading: (Boolean) -> Unit, setError: (String?) -> Unit) {
        setLoading(true)
        setError(null)
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val api = NetworkModule.api(this@PairingActivity)
                val result = api.pair(DevicePairRequest(code = code))
                DeviceAuth(this@PairingActivity).apply {
                    // ★ POC simplification shared with the register()/TEST_PATIENT_ID path
                    // this replaces (deps.py device_patient's own docstring): device_token
                    // IS the patient id, so there's no separate field to read off the
                    // response for it.
                    deviceToken = result.device_token
                    patientId = result.device_token
                    patientDisplayName = result.display_name
                }
                // ★ Confirmed live: without this, a freshly-paired device shows "今天没有
                // 安排" until SyncWorker's own periodic timer happens to fire — up to 6
                // hours away, and that timer is set once ever (ExistingPeriodicWorkPolicy.
                // KEEP in SyncWorker.enqueuePeriodic), not reset on pairing. Nothing else
                // was pulling the schedule down at the one moment it's most needed.
                SyncWorker.enqueue(this@PairingActivity)
                withContext(Dispatchers.Main) {
                    startActivity(Intent(this@PairingActivity, HomeActivity::class.java))
                    finish()
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    setLoading(false)
                    setError("配对码不对或者已经过期了，跟家人确认一下再试一次")
                }
            }
        }
    }
}

@Composable
private fun PairingScreen(
    code: String,
    loading: Boolean,
    error: String?,
    onCodeChange: (String) -> Unit,
    onSubmit: () -> Unit,
) {
    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(Dimens.screenPadding),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(text = "配对老人手机", fontSize = Dimens.primaryTextSp, fontWeight = FontWeight.Bold)
            Text(
                text = "请家人在手机上生成配对码，输入在下面",
                fontSize = Dimens.minTextSp,
                color = MutedText,
                modifier = Modifier.padding(top = 8.dp, bottom = Dimens.screenPadding),
            )
            OutlinedTextField(
                value = code,
                onValueChange = onCodeChange,
                enabled = !loading,
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                textStyle = TextStyle(fontSize = 32.sp, fontWeight = FontWeight.Bold, letterSpacing = 8.sp),
                colors = TextFieldDefaults.colors(focusedIndicatorColor = PrimaryGreen),
                modifier = Modifier.fillMaxWidth(),
            )
            if (error != null) {
                Text(
                    text = error,
                    fontSize = Dimens.minTextSp,
                    color = Color.Red,
                    modifier = Modifier.padding(top = 12.dp),
                )
            }
            if (loading) {
                CircularProgressIndicator(
                    color = PrimaryGreen,
                    modifier = Modifier.padding(top = Dimens.buttonSpacing),
                )
            } else {
                BigButton(
                    text = "配对",
                    backgroundColor = PrimaryGreen,
                    contentColor = Color.White,
                    onClick = onSubmit,
                    modifier = Modifier.padding(top = Dimens.buttonSpacing),
                )
            }
        }
    }
}

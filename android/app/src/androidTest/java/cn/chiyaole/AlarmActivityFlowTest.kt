package cn.chiyaole

import android.content.Context
import android.content.Intent
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import cn.chiyaole.alarm.EXTRA_DOSE_ID
import cn.chiyaole.alarm.EXTRA_RING_INDEX
import cn.chiyaole.alarm.EXTRA_SCHEDULED_AT_MILLIS
import cn.chiyaole.data.AppDatabase
import cn.chiyaole.data.DoseEntity
import cn.chiyaole.ui.AlarmActivity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Instrumented UI test for the elder-facing ring screen (wireframe A1/A2). Proves the
 * button-tap -> Room-write wiring on a real emulator/device — NOT the OEM
 * background-killing defenses CLAUDE.md is explicit an emulator cannot reproduce; see
 * docs/testing/manual_e2e.md for that half, which needs a physical Huawei/Honor/Xiaomi
 * device.
 *
 * Seeds [DoseEntity] directly into the on-device Room DB (the same DB AlarmActivity itself
 * reads via ScheduleRepository) rather than going through a real AlarmManager firing, since
 * this test is about the screen's wiring, not the scheduler (AlarmSchedulerTest already
 * covers that as a pure-JVM unit test).
 */
@RunWith(AndroidJUnit4::class)
class AlarmActivityFlowTest {
    @get:Rule
    val composeRule = createEmptyComposeRule()

    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test
    fun tappingTaken_writesConfirmationEvent() {
        val doseId = "e2e-test-dose-${System.currentTimeMillis()}"
        val scheduledAt = System.currentTimeMillis()

        runBlocking {
            AppDatabase.get(context).doseDao().upsertAll(
                listOf(
                    DoseEntity(
                        doseId = doseId,
                        medicationId = "e2e-test-med",
                        scheduledAtMillis = scheduledAt,
                        genericName = "阿莫西林",
                        dosePerTake = 1.0,
                        timingNote = "饭后服用",
                        photoLocalPath = null,
                        state = "pending",
                    ),
                ),
            )
        }

        val intent = Intent(context, AlarmActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            putExtra(EXTRA_DOSE_ID, doseId)
            putExtra(EXTRA_RING_INDEX, 1)
            putExtra(EXTRA_SCHEDULED_AT_MILLIS, scheduledAt)
            putExtra(AlarmActivity.EXTRA_ALARM_FIRED_AT_MILLIS, scheduledAt)
        }

        ActivityScenario.launch<AlarmActivity>(intent).use {
            composeRule.onNodeWithText("吃了").performClick()
            composeRule.waitForIdle()

            val takenCount = runBlocking {
                AppDatabase.get(context).confirmationEventDao().takenCountForDose(doseId)
            }
            assertEquals(1, takenCount)
        }
    }
}

package cn.chiyaole.alarm

import cn.chiyaole.data.DoseEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Pure ring-series math (spec §8.2 style: pure functions get a parametrized table, no
 * Android framework dependency, runs off-device). Ring offsets match
 * data/remote_config.json `alarm.ring_series`: 0, +10 min, +30 min from scheduled_at.
 */
class AlarmSchedulerTest {
    private val ringOffsetsMs = listOf(0L, 600_000L, 1_800_000L) // ring 1/2/3
    private val scheduledAt = 1_000_000_000_000L // arbitrary fixed epoch millis
    private val dose = DoseEntity(
        doseId = "d1",
        medicationId = "m1",
        scheduledAtMillis = scheduledAt,
        genericName = "AMLODIPINE",
        dosePerTake = 1.0,
        timingNote = null,
        photoLocalPath = null,
        state = "pending",
    )

    @Test
    fun `before scheduled time returns ring 1 at scheduled_at`() {
        val target = AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt - 1, ringOffsetsMs)
        assertEquals(AlarmScheduler.RingTarget("d1", 1, scheduledAt, scheduledAt), target)
    }

    @Test
    fun `exactly at ring 1's trigger time rolls to ring 2, never re-fires ring 1`() {
        val target = AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt, ringOffsetsMs)
        assertEquals(AlarmScheduler.RingTarget("d1", 2, scheduledAt + 600_000L, scheduledAt), target)
    }

    @Test
    fun `just before ring 2's trigger time still returns ring 2`() {
        val target = AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt + 600_000L - 1, ringOffsetsMs)
        assertEquals(2, target?.ringIndex)
        assertEquals(scheduledAt + 600_000L, target?.triggerAtMillis)
    }

    @Test
    fun `just before ring 3's trigger time returns ring 3`() {
        val target = AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt + 1_800_000L - 1, ringOffsetsMs)
        assertEquals(3, target?.ringIndex)
        assertEquals(scheduledAt + 1_800_000L, target?.triggerAtMillis)
    }

    @Test
    fun `at or after the last ring, nothing is left to schedule for this dose`() {
        assertNull(AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt + 1_800_000L, ringOffsetsMs))
        assertNull(AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt + 10_000_000L, ringOffsetsMs))
    }

    @Test
    fun `a single-ring series never rolls past ring 1`() {
        val target = AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt - 1, ringOffsetsMs = listOf(0L))
        assertEquals(1, target?.ringIndex)
        assertNull(AlarmScheduler.nextRingFor(dose, nowMillis = scheduledAt, ringOffsetsMs = listOf(0L)))
    }
}

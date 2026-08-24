package cn.chiyaole.util

import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteConfigTest {
    @Test
    fun `fillTemplate substitutes every placeholder`() {
        val result = "{name}，该吃药了".fillTemplate("name" to "王阿姨")
        assertEquals("王阿姨，该吃药了", result)
    }

    @Test
    fun `fillTemplate leaves unmatched placeholders untouched`() {
        val result = "我这就去问{caregiver}".fillTemplate("name" to "王阿姨")
        assertEquals("我这就去问{caregiver}", result)
    }

    @Test
    fun `DEFAULT ring series matches remote_config json baseline (0, 10min, 30min)`() {
        assertEquals(listOf(0L, 600_000L, 1_800_000L), RemoteConfig.DEFAULT.alarm.ringSeriesMs)
    }
}

package cn.chiyaole.net

import org.junit.Assert.assertEquals
import org.junit.Test

class DtoTest {
    @Test
    fun `isoToMillis parses an explicit offset, not just Z`() {
        // Regression test: the server serializes scheduled_at with its actual session
        // timezone offset (confirmed live: a Postgres session in China time produces
        // "...+08:00", not "...Z"). Instant.parse() only accepts "Z" and threw here,
        // silently killing every SyncWorker run.
        val millis = "2026-08-13T06:30:00+08:00".isoToMillis()
        val utcMillis = "2026-08-12T22:30:00Z".isoToMillis()
        assertEquals(utcMillis, millis) // 06:30+08:00 is the same instant as 22:30Z the day before
    }

    @Test
    fun `isoToMillis still parses plain Z timestamps`() {
        val expected = java.time.Instant.parse("2026-08-13T00:00:00Z").toEpochMilli()
        assertEquals(expected, "2026-08-13T00:00:00Z".isoToMillis())
    }

    @Test
    fun `toIso round-trips through isoToMillis`() {
        val original = 1_786_600_000_000L
        assertEquals(original, original.toIso().isoToMillis())
    }

    @Test
    fun `isoToMillis falls back to the system zone when the server has no offset at all`() {
        // Regression test, confirmed live against a SQLite-backed dev server (no
        // docker/postgres): SQLite has no timezone-aware datetime type, so a
        // DateTime(timezone=True) column silently loses its offset there — the wire value
        // comes back as a bare "2026-08-17T10:34:12.140392", which OffsetDateTime.parse()
        // rejects outright (it requires an offset). Only a SQLite dev server hits this;
        // production is always Postgres, which never loses the offset.
        val expected = java.time.LocalDateTime.parse("2026-08-17T10:34:12.140392")
            .atZone(java.time.ZoneId.systemDefault())
            .toInstant()
            .toEpochMilli()
        assertEquals(expected, "2026-08-17T10:34:12.140392".isoToMillis())
    }
}

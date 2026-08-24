# Manual end-to-end test (physical device)

`server/tests_e2e/` (`make e2e-web`) and `android/app/src/androidTest/`
(`./gradlew connectedDebugAndroidTest`, an emulator in CI) cover everything that can be
proven without real hardware. They cannot prove the one thing CLAUDE.md calls out as the
project's actual #1 technical risk: **Chinese-OEM background-process-killing** (spec §4).
An emulator has no Huawei/Honor/Xiaomi/OPPO/vivo battery-management stack to defeat, so this
procedure has to run on a real device.

## What this proves that nothing automated does

- Screen-on-before-speech timing on real (slow) hardware (spec §3.4-③, ≤500ms gap).
- Full-screen-over-lock-screen actually works on a real OEM lock screen.
- The alarm still fires after the OEM's own task manager kills the app.
- The vendor autostart deep link (`vendor/VendorAutoStart.kt`) actually opens the right
  settings screen on a real ROM, not just a `resolveActivity()` check.

## Setup

1. **Bring up the server** (from repo root):
   ```
   make db-up
   make migrate
   make run
   ```
   Note the machine's LAN IP (`ifconfig`/`ipconfig`) — the phone needs to reach it, not
   `localhost`. `data/remote_config.json`'s `base_url` and the debug APK's
   `BuildConfig.API_BASE_URL` (`android/app/build.gradle.kts`) both assume HTTPS in
   non-debug builds; for this manual pass, either run the debug variant (already points at
   `10.0.2.2`/cleartext for the *emulator* — swap it to your LAN IP + port, and add a
   matching entry to `android/app/src/debug/res/xml/network_security_config.xml`) or tunnel
   HTTPS (e.g. `ngrok http 8000`) and skip editing the cleartext config at all.

2. **Seed a patient + caregiver:**
   ```
   cd server && .venv/bin/python scripts/seed_test_patient.py
   ```
   Prints `patient_id` and `access_token`.

3. **Onboard a real medication through the actual caregiver web app** — this is no longer a
   hypothetical step; `server/web/` is implemented. On a phone or laptop browser:
   ```
   http://<server-host>:8000/web/<patient_id>/upload?t=<access_token>
   ```
   Photograph (or upload) a real pill box, click 识别, go to 确认用药, check the strength
   box, confirm. Note the `medication_id` FastAPI's `/docs` or the browser network tab shows
   you (or query it: `sqlite3`/`psql` `select id from medications;`).

4. **Seed a dose a few minutes out** so you don't wait for a real schedule slot:
   ```
   .venv/bin/python scripts/seed_near_future_dose.py <medication_id> 3
   ```

5. **Install the debug APK** on the physical device:
   ```
   cd android && ./gradlew installDebug
   ```

6. **Connect the device to the seeded patient.** `HomeActivity`'s debug-only
   "🔗 连接测试服务器并同步" button registers against a *hardcoded* `TEST_PATIENT_ID`
   (`ui/HomeActivity.kt`) — update that constant to the `patient_id` from step 2 and
   reinstall, or `adb shell` write the same value directly via `DeviceAuth`'s SharedPreferences
   keys if you'd rather not edit code for a one-off run. Tap the button; it should toast
   "已连接测试服务器，正在同步日程".

## Procedure

1. **Screen-on-before-speech**: wait for the seeded dose to ring. Confirm the screen lights
   up *before* TTS starts speaking (not simultaneously) — the gap is
   `remote_config.json`'s `alarm.screen_on_to_speech_delay_ms` (400ms default).
2. **Full-screen over lock screen**: lock the phone before the alarm fires; confirm
   `AlarmActivity` still appears full-screen without unlocking.
3. **OEM survival**: after installing, walk `PermissionSetupActivity`'s checklist
   (exact-alarm, notifications, battery-optimization exemption, autostart) — confirm each
   vendor deep link (`vendor/VendorAutoStart.kt`) actually opens the correct settings screen
   for this device's manufacturer, not just the generic app-info fallback. Then kill the app
   via the OEM's own task-manager "clean up"/"boost" feature (not just swiping it from
   Recents — that's a different, less aggressive kill path) and seed another near-future
   dose; confirm the alarm still fires.
4. **Button taps**: confirm 吃了/等会儿吃/这次不吃 all write locally instantly (screen
   dismisses without waiting on network) and eventually show up via
   `GET /api/patient/<patient_id>/today?t=<token>` on the dashboard
   (`/web/<patient_id>/dashboard?t=<token>`).
## What "pass" means

All four steps above complete without: the app being silently killed and never recovering,
a screen appearing over an active phone call, or an unrequested permission dialog.

## Note: voice Q&A (wireframe C1-C3) is wired, C3->C4 (caregiver reply) is not

The elder's 🎤 问一问 button on `HomeActivity` opens `QaActivity`: hold to speak → ASR →
refusal check → an answer or a spoken decline, all in one screen. This was built once with
a full caregiver-reply loop (an escalation record, a caregiver inbox, the device polling for
a reply), deliberately removed (it duplicated WeChat's own instant messaging, and there was
no real push channel to either party), then reinstated WITHOUT that loop — a refused
question tells the elder to ask their caregiver themselves, not that the app has (or will)
relay it. To manually check it: on the running app, tap 🎤 问一问, hold the button, ask a
question like "我今天吃药了没", release, and confirm both a transcript and a spoken answer
appear. `agent/escalation.py` stays dormant server-side; revisit it only if a real push
channel ever makes the full C3→C4 loop worth its surface area.

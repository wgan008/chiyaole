# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ChiYaoLe (吃药了) is a medication-adherence system for elderly users in mainland China. The
adult child photographs the pill boxes once; from then on the elder only has to listen and
press one large button. Full product rationale is in `README.md` and `docs/design/`
(`00_INDEX.md` is the reading order). **`docs/design/05_Technical_Spec_EN.md` is the
spec-driven-development input** — read the relevant section before touching a module; it
contains contracts, prohibited behaviors, and acceptance criteria that are not restated here.

Three non-negotiable product boundaries (see README "Lines this product does not cross"):
1. Transcribe / compare / enlarge only — **never interpret medical meaning**. Crossing this
   makes the product a regulated medical device.
2. AI parses → the adult child confirms each item → only then does it take effect. Never
   fully automatic.
3. A promise spoken to the elder must already be true (e.g. never say "I told your daughter"
   before delivery is confirmed — see the escalation state machine below).

## Repository layout

```
server/     FastAPI + SQLAlchemy + APScheduler backend
  app/      HTTP layer: config, db, schemas, models
  agent/    reasoning modules — pure functions, no framework dependency
  web/      caregiver mobile web (Jinja2 + vanilla JS, no build step)
  tests/       unit tests (in-process ASGI, mocked agent/llm.py)
  tests_e2e/   browser-driven golden-path test (Playwright, `make e2e-web`)
android/    elder-side APK: Kotlin + Jetpack Compose, minSdk 26 / targetSdk 35
data/       drug_alias.json, lab_codes.json, pim_cn_2017.json, interactions.json, remote_config.json
evals/      golden pill boxes, NL-query/refusal cases, ASR samples
docs/design/  the design docs (read 05_Technical_Spec_EN.md before implementing)
```

## Commands

```bash
# Server
cp .env.example .env          # DashScope / OSS / PushPlus credentials
make db-up                    # postgres 16 in docker
make install                  # pip install -e ".[dev]" (server/)
make migrate                  # alembic upgrade head
make run                      # uvicorn app.main:app --reload → :8000, docs at /docs

make lint                     # ruff check .
make fmt                      # ruff format .
make typecheck                # mypy agent/  (strict mode, see server/pyproject.toml)
make unit                     # pytest server/tests/ -v
make eval                     # pytest evals/ -v --eval  (hits DashScope, needs API key)
make check                    # everything CI runs on push: lint + typecheck + unit

# Single test
cd server && pytest tests/test_normalize.py -v
cd server && pytest tests/test_normalize.py::test_resolve_drug -v

# Android
cd android && ./gradlew assembleDebug
make android-test             # ./gradlew testDebugUnitTest lint
```

**Android must be verified on physical Chinese-OEM devices, not emulators** — emulators
cannot reproduce the background-process-killing behavior the app defends against
(`scripts/precheck.sh` is the device-compatibility pre-flight for a connected `adb` device).

CI (`.github/workflows/ci.yml`) runs three independent jobs: `server` (lint/typecheck/unit,
always), `evals` (needs `DASHSCOPE_API_KEY` secret, PR-only, still blocking), `android`
(`testDebugUnitTest lint`).

## Architecture

### End-to-end flow

```
AlarmManager (USE_EXACT_ALARM) → full-screen intent → AlarmActivity (elder taps Taken/Snooze/Skip)
  → Room writes confirmation_event locally, screen off immediately (no network wait)
  → WorkManager syncs to server in background, retries up to 7 days
  → server computes confidence → caregiver's three-state dashboard (confirmed/pending/unknown)
```

Server pipeline for onboarding a medication: `POST /api/assets` (raw photo → OSS, kept
forever) → `agent/vision.py` (photo → structured JSON, transcription only) →
`agent/normalize.py` (drug/lab-code → canonical form, or `None` — never guessed) →
`agent/safety.py` (duplicate-generic / PIM / interaction screen — **blocks** schedule
generation on any hit) → caregiver confirms each item → `agent/schedule.py` (dosage text →
concrete clock times, or `Ambiguous` — never guessed) → schedule becomes active.

Voice Q&A pipeline (orchestrated by `agent/qa.py`): ASR →
**`agent/guard.py` (refusal check) runs before anything else** → `agent/intents.py`
(classifies into one of 6 enums + slots — **deliberately not text-to-SQL**) →
`agent/queries.py` (hand-written parameterized SQL, one function per intent) →
`phrase()` (LLM turns the already-computed result into speech; never sees the raw
utterance, so it cannot be talked into answering something the guard would have refused).

Wired up: `POST /api/asr` / `POST /api/qa` (`app/api/device.py`), hold-to-speak on the
elder's `HomeActivity` (🎤 问一问 → `QaActivity`, wireframe C1/C2/C3). **Deliberately
smaller than the original design**: the caregiver-reply loop (C3→C4 — an escalation record,
a caregiver inbox, polling for a reply) was built once, fully removed (it duplicated
WeChat's own instant messaging and had no real push channel to either party), and only the
plain Q&A half was reinstated. A refused question gets a spoken decline that tells the
elder to ask their caregiver themselves (`agent/qa.py`'s `_refused`, using the copy in
`data/remote_config.json`) — never a promise that the app relayed anything, since it
didn't. The wireframe doc's own annotation on C3→C4 ("C3 → C4 才是产品，C2 只是功能") argues
this is the less valuable half of the original design; revisit `agent/escalation.py`
(still dormant) if a real push channel ever makes the full loop worth its surface area
again.

### The one design rule that governs every `agent/` module

> When a value cannot be resolved, return `None` / `Ambiguous` / `Refuse`. **Never return
> the closest match.** The caller branches into "refuse" or "flag for the caregiver."

This is why `agent/__init__.py`, `normalize.py`, `schedule.py`, `vision.py`, `intents.py`
all lead their docstrings with a "Prohibited" section before describing behavior
(docs/spec §10.2 rule 1: "write Prohibited before Behaviour" — the AI will otherwise
helpfully cross the boundary that gives this product its value).

Each `agent/` module is a pure function with no framework dependency; only `vision.py`,
`intents.py`, and the ASR/phrase paths call DashScope (`agent/llm.py` is the single,
isolated point of contact with the model, which is why the rest of `agent/` runs its test
suite fully offline).

### Naming carries safety meaning — do not "clean up" these names

- `confirmation_events`, not `medication_taken` — the system records that a button was
  pressed, not that a pill was swallowed.
- `agent/escalation.py`'s outbox state machine binds elder-facing wording to state as an
  **assertion**, not a style convention: only `DELIVERED` may use the past-tense "已经"
  (already). `OPEN`/`SENT` must say the future-tense "我这就去问…" (I'll go ask…). A test
  asserts no pre-delivery string contains 已经 — see `data/remote_config.json`
  `copy.escalation_state_messages` for the exact wording and
  `docs/design/05_Technical_Spec_EN.md` §7.6.
- `resolve_drug` / `resolve_lab` / `synthesize` return `None`/`Ambiguous` rather than
  raising — an unresolvable input is a routine, expected outcome, not an error condition.
- `medications.status` can only become `'active'` if `confirmed_at IS NOT NULL` — enforced
  by a DB `CHECK` constraint (`active_requires_confirm`), not just application logic.

### Android: the #1 technical risk is OEM background-killing, not app logic

Per spec §0/§4: Chinese OEM ROMs (Huawei/Honor, Xiaomi, OPPO, vivo) aggressively kill
background processes, and a reminder that doesn't fire is worth zero. Three layers of
defence, in `android/app/src/main/java/cn/chiyaole/`:

1. `alarm/` — `USE_EXACT_ALARM` (normal permission, API 33+) with `SCHEDULE_EXACT_ALARM`
   fallback (pre-granted on API 31-32, must be requested at runtime on 33+ via
   `canScheduleExactAlarms()`), `setExactAndAllowWhileIdle()`, `BootReceiver` reschedules
   on reboot.
2. A foreground service whose persistent notification doubles as the "pending dose" card.
3. `vendor/` — per-manufacturer allow-list deep links (`Build.MANUFACTURER` branch), walked
   by the adult child at install time, **never** left to the elder. Vendor Activity names
   change between ROM versions — every deep link must be wrapped so a resolution failure
   falls back to the app-details settings page and **never crashes**.

Version floor is deliberate: `minSdk 26` because elders run 5-8-year-old hand-me-down
phones and API 26 introduced `NotificationChannel`. `targetSdk 35` because
`USE_EXACT_ALARM` requires ≥33. Never swap in `SCHEDULE_EXACT_ALARM` as the primary
mechanism — it is denied by default on fresh Android 14+ installs.

Test matrix requirement (spec §3.2/§4.4): **both** an older HarmonyOS/EMUI device (can't
surface the Android 14+ permission-default problem) **and** an Android 14/15 device
(can't surface OEM background-killing or low-end cold-start lag) — passing on only one end
proves nothing. Acceptance gate is 72 consecutive hours, ≥24 alarms, zero missed, before
any business logic beyond alarms gets written.

### Data model invariants (`docs/design/05_Technical_Spec_EN.md` §5 has the full DDL)

- `assets` (original photos/audio) are kept forever in OSS — the arbiter of truth if a
  parse is ever disputed or a model is upgraded and history needs re-running.
- `lab_items.code` is `NULL` when unresolved and is **never guessed**; same rule as
  `normalize.resolve_lab`.
- `escalations` is a durable outbox (PostgreSQL-backed, not in-memory) so retries survive a
  restart — see `agent/escalation.py`'s `deliver_loop` (APScheduler, exponential backoff,
  up to 7 days).

### Configuration that must never require a new APK build

`data/remote_config.json` — wording, timings (ring series, snooze minutes, screen-on-to-
speech delay), and feature flags. The elder device fetches it once daily and falls back to
values baked into the APK if it has never fetched successfully. Edit this file, not
hard-coded strings in `android/`, when changing copy or timing.

## Regulatory/deployment constraints that shape engineering decisions

- POC server is Hong Kong-region (Alibaba Cloud) specifically to avoid mainland ICP filing
  (~20 days) blocking the build; migrate to a mainland region only at scale-up.
- The caregiver web page **requires HTTPS** — `<input capture>` (camera access) is disabled
  outright by browsers on non-HTTPS pages, and it must work inside WeChat's in-app browser.
- No Google-service dependency anywhere (no FCM, not on Google Play) — this is deliberate,
  not an oversight, since the target devices are Huawei/Xiaomi/OPPO/vivo without GMS.

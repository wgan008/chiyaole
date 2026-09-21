# 吃药了 · ChiYaoLe

> The adult child photographs the pill boxes once. From then on the elder only has to
> listen, and press one large button.

<!-- ★ TODO before open-sourcing: the first screen of this README must be five photos of how
     elders actually take their pills today — the drawer of loose boxes, the pen marks on the
     blister pack, the note taped to the fridge. Not the tech stack. See spec §9. -->

**Who uses it**: the elder is the daily active user; the adult child is the payer and the gatekeeper.
**Where**: mainland China.
**Stage**: design complete, 14-day POC in progress.

---

## The argument, in one paragraph

Nationally, hypertension is **treated in 45.8% of cases and controlled in only 16.8%**.
The prescription was written. The medicine went home. **Most of those 29 lost percentage
points are not in the hospital — they are in the house.** That stretch is the blind spot of
every piece of existing healthcare infrastructure.

## Three layers of pain

| Layer | Pain | Why existing products don't solve it |
|---|---|---|
| **P1 · Execution** | The dose isn't taken on time | Smart pill boxes and alarm clocks already cover most of this. **We do not differentiate here** |
| **P2 · Comprehension** | They don't know what they are taking | 84% can't read the insert, 58% can't parse the terminology. **A pill box does not know what is inside it** |
| **P3 · Ground truth** | The remote child can't find out what actually happened | Every channel of information passes through a filter that is either motivated or impaired |

**P1 builds the habit → P2 builds the moat → P3 builds willingness to pay.**
All three share one button; the marginal cost of the last two is near zero.

## Lines this product does not cross

1. **Transcribe, compare, enlarge — never interpret medical meaning.**
   Crossing that line makes this a regulated medical device, with a registration cycle measured
   in years. **This is not an ethics question; it is a question of whether we can ship at all.**
2. **AI parses → the adult child confirms each item → only then does it take effect.** Never fully automatic.
3. **Record events, not content.** No always-on microphone, no always-on camera.
4. **The data must never be used as a KPI to grade a caregiver** — that manufactures false data directly.
5. **A promise spoken aloud must be true.** We do not say "I've told your daughter" before delivery is confirmed.

---

## Repository layout

```
吃药了/
├── docs/
│   ├── spec/        ★ spec-driven development input — hand a whole file to a coding agent
│   ├── design/      the original design documents (solution summary, wireframe, naming, POC plan)
│   ├── pain.md      problem data + sources
│   ├── constraints.md  why an APK and not a WeChat Mini Program
│   ├── safety.md    refusal boundaries, failure modes, disclaimer
│   └── a11y.md      low-vision / colour-deficiency / cataract rationale
├── server/          FastAPI + SQLAlchemy + APScheduler
│   ├── app/         HTTP layer: routes, models, services
│   ├── agent/       the reasoning modules — one pure function, one contract, one test set each
│   ├── web/         caregiver mobile web (Jinja2 + vanilla JS, no build step)
│   └── tests/
├── android/         elder-side APK (Kotlin + Compose, minSdk 26 / targetSdk 35)
├── data/            drug aliases, lab codes, PIM list, remote config
├── evals/           golden pill boxes, intent cases, refusal cases, ASR samples
├── field-notes/     notes from every home visit — the most persuasive part of this repo
└── scripts/         precheck.sh — device compatibility pre-flight (development tool, not product)
```

---

## Quick start

### Server

```bash
cp .env.example .env          # fill in DashScope / OSS / PushPlus credentials
make db-up                    # postgres 16 in docker
make install                  # pip install -e ".[dev]"
make migrate                  # alembic upgrade head
make run                      # http://localhost:8000 · docs at /docs
```

Run everything CI runs:

```bash
make check                    # ruff + mypy + pytest
```

The pure-function agent modules (`normalize`, `safety`, `schedule`, `guard`, `escalation`)
have **no network dependency** and their tests run with no API key.
Only `vision`, `intents` and `phrase` call DashScope.

### Android

```bash
cd android && ./gradlew assembleDebug
```

Then, **on a physical Chinese-OEM device** — emulators cannot reproduce any of the
background-killing behaviour that matters (spec §3.3):

```bash
./scripts/precheck.sh         # 0 = clear · 1 = manual steps needed · 2 = incompatible
```

---

## The one technical risk that outranks everything

**Chinese OEM ROMs killing background processes — not LLM quality.**
A reminder app that doesn't ring is worth exactly zero.

Three layers of defence (spec §4): `USE_EXACT_ALARM` → foreground service → vendor allow-list
onboarding walked by the adult child at install time.

> **Acceptance gate: 72 consecutive hours on real hardware, ≥24 alarms, zero missed.**
> Until that is green, no business logic gets written and day 11 does not happen.

**Test both ends of the range.** The target user's older HarmonyOS device (API 31)
**cannot surface** the Android 14+ permission problem; a new flagship cannot surface the
cold-start problem of a 2018 SoC. Passing on either end alone proves nothing.

---

## Visual rules

- Primary button green `#0B6B33` — 7.4:1 against white, AAA
- Brand yellow `#FFD500` + true black `#0A0A0A` — 15:1
- **Colour never carries information**: everything still works in greyscale
- Elder-side minimum 24 sp; primary information ≥ 40 sp
- Tap only. No swiping, anywhere.

---

## License

[Business Source License 1.1](LICENSE) — source-available, not open source. Free to read,
run, and modify for non-production, personal, educational, and research use. Running it (or
a derivative) as a hosted service, or operating it as a paid medication-adherence product,
requires a commercial license until the Change Date (2030-09-21), after which it converts
to Apache License 2.0.

---

*Disclaimer: this product explicitly does not provide diagnostic advice and does not recommend
adjusting or stopping any medication. Regulatory notes here are a summary of public information,
not legal advice.*

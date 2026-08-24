# Deploying to Alibaba Cloud (Hong Kong region)

Matches `docs/design/05_Technical_Spec_EN.md` §3.1's POC deployment target. Hong Kong,
not mainland: mainland requires ICP filing (~20 days) before a domain can serve traffic at
all, which would block everything. Migrate to a mainland region only at real scale-up.

Two containers (`postgres`, `app`, per `docker-compose.yml`) plus a third (`caddy`) added
by the production overlay for automatic HTTPS. Nothing else — no Redis, no Celery, no
managed Kubernetes; this runs on a 2 vCPU / 2 GB box.

★ **2GB is a deliberately tight budget** — Postgres + the Python app + Caddy + the OS +
Docker daemon leaves little headroom (roughly 500–800MB baseline before serving a single
request). Step 4 below adds swap specifically to survive the one place this bites hardest:
`docker compose build` compiling `psycopg`'s C extension, which can transiently spike well
past idle memory. If cost allows moving to 4GB later, that removes this risk entirely
rather than just cushioning it — worth it once real users are on this box.

## 1. Provision the server

1. Alibaba Cloud console → **Simple Application Server** (轻量应用服务器), **not** ECS —
   it's cheaper and bundles the security group/snapshot UI the POC doesn't need to
   configure by hand.
2. Region: **Hong Kong**.
3. Image: **Ubuntu 22.04 LTS**.
4. Plan: **2 vCPU / 2 GB RAM** (the smallest tier with real headroom — see the note above;
   Hong Kong's SWAS lineup has no 1 vCPU option and the 0.5–1GB tiers below this one are
   too tight to run three containers on).
5. In the instance's firewall/security-group rules, open:
   - `22` (SSH) — restrict to your own IP if you can, rather than `0.0.0.0/0`.
   - `80`, `443` (HTTP/HTTPS) — required, Caddy needs `80` for the ACME HTTP-01 challenge
     even though the app is only ever served over `443`.
   - Leave `8000` and `5432` **closed** to the internet — they're only reached
     container-to-container over the compose network, never from outside.
6. Note the instance's public IP.

## 2. Point a domain at it

1. Buy/use any domain (`.cn` domains need ICP-linked ownership info even outside the
   mainland region rule above — a non-`.cn` TLD like `.com`/`.dev` sidesteps that
   entirely, which is why the spec doesn't require a `.cn` domain for the POC).
2. Add an **A record** for the API host (e.g. `api.chiyaole.cn` or
   `staging-api.yourdomain.com`) pointing at the instance's public IP.
3. Wait for DNS to propagate (`dig +short your-domain` from your own machine) before
   step 6 below — Caddy's first HTTPS request fails permanently-cached if it can't
   validate ownership on the first try, and every subsequent attempt is rate-limited by
   Let's Encrypt.

## 3. Install Docker

SSH in, then:

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # log out/in once for this to take effect
```

## 4. Add swap (do this before building anything)

At 2GB RAM this isn't optional — without it, `docker compose build` compiling
`psycopg`'s C extension is a realistic way to get OOM-killed before the app ever runs.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # survives reboot
free -h   # confirm the Swap row shows 2.0Gi
```

2GB of swap, matching RAM 1:1, is a reasonable floor here — it's a safety net for build
spikes and the occasional burst, not something this workload should lean on continuously
(swap is slow; if you see it in steady use under normal traffic, that's a signal to move
to the 4GB plan, not to add more swap).

## 5. Get the code onto the server

This repo has no git remote configured yet. Either:

- **Set one up** (push to a private GitHub/Gitee repo) and `git clone` it on the server —
  the normal path once you're deploying more than once, and gets you `git pull` for every
  future update.
- **Or rsync it directly**, if you just want this box running today:

  ```bash
  rsync -az --exclude-from=.dockerignore --exclude .git \
      /Users/ganwei/Projects/吃药了/ your-user@your-server-ip:~/chiyaole/
  ```

Either way, land it at `~/chiyaole` on the server (the paths below assume that).

## 6. Configure `.env`

```bash
cd ~/chiyaole
cp .env.example .env
```

Fill in, at minimum:

| Variable | Value |
|---|---|
| `DASHSCOPE_API_KEY` | your real key |
| `OSS_ENDPOINT` / `OSS_BUCKET` / `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | see the note below — **optional for the POC**, `storage.py` falls back to local disk (now durable via the `app_storage` volume, see `docker-compose.yml`) |
| `BASE_URL` | `https://your-domain` (the same one from step 2) |
| `CHIYAOLE_DOMAIN` | the same domain again, bare (no `https://`) — this is the one Caddy reads |
| `ENV` | `prod` |
| `PUSHPLUS_TOKEN` | only if you're using the WeChat escalation push (currently dormant, see `agent/escalation.py`'s own docstring) |

`DATABASE_URL` does **not** need to be set — `docker-compose.yml` overrides it to point at
the `postgres` container regardless of what's in `.env`.

> **On OSS**: `app/services/storage.py` is explicitly a local-disk stand-in for real OSS
> (its own docstring says so) — nothing in this repo talks to OSS yet even though
> `oss2` is already a declared dependency and `.env.example` has the fields. The
> `app_storage` docker volume added in this change makes local-disk storage durable
> across container restarts, which is enough for a POC. Swapping in real OSS is a real
> follow-up (`save()`/`url_for()` are the only two functions any caller depends on), not
> done as part of this deploy — say the word if you want it built.

## 7. Bring it up

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

This builds the `app` image, runs `alembic upgrade head` on first boot (see the `app`
service's `command:` in `docker-compose.yml`), and starts Caddy, which requests its
Let's Encrypt certificate on first request to your domain.

## 8. Verify

```bash
curl https://your-domain/health
# {"status":"ok"}
```

Then, from a phone (ideally inside WeChat's in-app browser, since that's the real target
environment — spec §3.1): open `https://your-domain/web/start`, walk through creating a
test elder, and confirm the camera capture (`<input capture>`) on the 拍照识别/拍化验单
pages actually opens — that's the concrete proof HTTPS is correctly terminated, not just
that `/health` responds.

Also check actual memory headroom now that real containers are running, given the tight
budget this plan started with:

```bash
free -h            # how much of the 2GB + 2GB swap is actually in use at idle
docker stats --no-stream   # per-container breakdown — postgres vs app vs caddy
```

If `postgres` + `app` + `caddy` are already close to the 2GB line at idle with no traffic,
that's the moment to move to the 4GB plan — before real users make it worse, not after.

## Updating after a code change

```bash
cd ~/chiyaole && git pull   # or re-rsync
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

`alembic upgrade head` re-runs on every `app` container start, so schema migrations are
picked up automatically; nothing else needs a manual step.

## What this guide does not cover

- **OSS integration** — see the note in step 6.
- **Backups** — `pgdata` and `app_storage` are named Docker volumes on a single VPS disk;
  there's no offsite backup configured. Fine for a POC, not fine once real patient data
  accumulates.
- **Migrating to a mainland region at scale-up** — new ICP filing, new security group
  rules, likely a managed RDS instance instead of the `postgres` container. Out of scope
  here; the spec calls it out as a deliberately separate, later step.

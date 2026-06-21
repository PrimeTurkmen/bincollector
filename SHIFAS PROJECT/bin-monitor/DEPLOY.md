# Deploy — AIMS Bin Collection Monitor on AWS EC2

Single-host Docker Compose deploy: one FastAPI app container + one Postgres container.
No PostGIS required (geometry is done in Python).

## 1. EC2 instance
- Type: **t3.small** (2 vCPU / 2 GB) is enough for the 3-truck pilot; t3.medium for full fleet.
- OS: Ubuntu 24.04 LTS, 20 GB disk.
- Security group inbound: **22** (SSH, your IP only), **80** (HTTP). Add **443** if you put TLS in front.

## 2. Install Docker
```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER   # re-login after this
```

## 3. Copy the project
From your machine:
```bash
scp -r bin-monitor ubuntu@<EC2_PUBLIC_IP>:~/bin-monitor
```

## 4. Configure
```bash
cd ~/bin-monitor
cp .env.example .env
nano .env        # set PILOT_USER/PASS, APP_SECRET, DASHBOARD_PASS, DB_PASSWORD
```

## 5. First-run seed (once)
Put the trial source files in `seed-data/` (only needed to load the 3-day lift history;
geozones + bins also come from Pilot):
```
seed-data/report.xlsx          # the compiled report (for bin master attributes)
seed-data/raw/*.xlsx           # the 9 sensor-tracing files
```
Then:
```bash
SEED=1 docker compose up -d --build      # seeds, then serves
# once it's up and seeded, set SEED=0 in .env so restarts don't re-seed
```
For an ongoing (non-trial) deploy, leave `SEED=0` and rely on Pilot:
- geozones + vehicles seed automatically;
- set the admin feed (`PILOT_ADMIN_*`) so the scheduler pulls angle history and detects lifts.

## 6. Use
- Dashboard: `http://<EC2_PUBLIC_IP>/` — login with `DASHBOARD_USER` / `DASHBOARD_PASS`.
- On-demand live refresh: the **↻ Refresh live** button.
- Historical pull: `POST /api/pull?days=7` (needs admin feed for lifts).

## 7. Operate
```bash
docker compose logs -f app     # logs
docker compose restart app     # restart app
docker compose down            # stop (data persists in the pgdata volume)
docker compose exec db pg_dump -U aims aims_bin > backup_$(date +%F).sql   # backup
```

## Production hardening (recommended before go-live)
- Put **HTTPS** in front (Caddy/Nginx + Let's Encrypt, or an AWS ALB).
- Move Postgres to **RDS** (change `DATABASE_URL` only) and take automated snapshots.
- Self-host Leaflet assets + add SRI (currently from CDN).
- Rotate `APP_SECRET`, use a strong `DASHBOARD_PASS`, restrict SG to known IPs.
- Switch the angle feed to the **admin API** for fully-automated lift detection.

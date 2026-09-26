# Deploying Trazo to production

This is the runbook for putting Trazo on the public internet: one Linux server,
one domain, automatic HTTPS, and sign-in required. It takes about twenty minutes
on a fresh machine.

The local stack in `docker-compose.yml` is for development only. It publishes
every service port, uses default credentials, and has no sign-in. Never expose
it to a network you do not control. Production uses
`docker-compose.prod.yml`, described below.

---

## What production changes

| | Development (`docker-compose.yml`) | Production (`docker-compose.prod.yml`) |
|---|---|---|
| Transport | Plain HTTP on localhost | HTTPS only, certificate issued and renewed automatically |
| Dashboard and read API | Open | Password sign-in, or the API key as a bearer token |
| Ingest and policy API | API key | API key |
| Published ports | Every service | Only 80 and 443, on the reverse proxy |
| Database, Redis, OPA | Reachable from the host | Internal network with no route to the internet |
| Secrets | Development defaults | Generated per install; startup refuses weak or default values |
| Containers | Default | Non-root, all Linux capabilities dropped, `no-new-privileges`, memory limits |
| API docs, `/metrics` | Served | Not served publicly |
| Security headers | None | HSTS, CSP, frame, referrer, and permissions policies |
| Sign-in brute force | Not applicable | Per-client lockout after 5 failed attempts in 15 minutes |

## Requirements

- A Linux server (Ubuntu 22.04 or 24.04 recommended) with at least **2 vCPU, 2 GB
  RAM, and 20 GB disk**. Any provider works — DigitalOcean, Hetzner, AWS
  Lightsail, Linode, and similar.
- A domain or subdomain you control, for example `trazo.example.com`.
- Docker Engine 24 or later with the Compose v2 plugin.
- Python 3.10 or later, only to run the setup script.

## Step 1 — Point DNS at the server

Create an `A` record (and an `AAAA` record if the server has IPv6) for your
domain pointing at the server's public IP. Confirm it resolves before continuing:

```bash
dig +short trazo.example.com
```

Certificate issuance fails until this returns the server's address.

## Step 2 — Open the firewall

Allow inbound 22 (SSH), 80 (HTTP, used for certificate issuance and the redirect
to HTTPS), and 443 (HTTPS, TCP and UDP). Nothing else. With `ufw`:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443
sudo ufw enable
```

Also check the provider's own cloud firewall, if it has one, allows the same.

Docker writes its own iptables rules and can bypass `ufw` for published ports.
The production stack publishes only 80 and 443, so this does not widen exposure
here — but do not add `ports:` entries to other services.

## Step 3 — Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # then log out and back in
docker compose version            # must report v2
```

## Step 4 — Get the code and generate secrets

```bash
sudo mkdir -p /opt/trazo && sudo chown "$USER" /opt/trazo
git clone https://github.com/naveen-astra/Trazo.git /opt/trazo
cd /opt/trazo

make prod-init DOMAIN=trazo.example.com EMAIL=ops@example.com
```

This writes `deploy/.env.production` with fresh random values for every secret
and prints the dashboard password and API key **once**. Store both in a password
manager now.

The file is gitignored and written owner-read-only. Do not commit it, copy it
into an image, or paste it into a ticket.

## Step 5 — Start the stack

```bash
make prod-up
```

The first run builds the images and requests the certificate, which takes a few
minutes. Watch it:

```bash
make prod-ps      # every service should reach "healthy" or "running"
make prod-logs    # Ctrl-C to stop following
```

## Step 6 — Verify the deployment

Run these from your own machine, not the server:

```bash
# HTTPS works and the certificate is valid
curl -sS https://trazo.example.com/healthz
# -> {"status":"ok","version":"0.1.0"}

# HTTP redirects to HTTPS
curl -sI http://trazo.example.com | head -1
# -> HTTP/1.1 308 Permanent Redirect

# Data is not readable without signing in
curl -sS -o /dev/null -w "%{http_code}\n" https://trazo.example.com/v1/runs
# -> 401

# Internal endpoints are not served publicly
curl -sS -o /dev/null -w "%{http_code}\n" https://trazo.example.com/metrics
# -> 404

# The datastores are not reachable from outside (both must fail to connect)
nc -zv -w 3 trazo.example.com 5432
nc -zv -w 3 trazo.example.com 6379
```

Then open `https://trazo.example.com`, sign in with the dashboard password, and
confirm the Overview loads.

## Step 7 — Point your agents at it

Agents send events with the API key over HTTPS:

```bash
export TRAZO_ENDPOINT=https://trazo.example.com
export TRAZO_API_KEY=<the API key from step 4>
```

```python
import trazo

trazo.init(project="my-agent")   # reads TRAZO_ENDPOINT and TRAZO_API_KEY
```

The CLI and replay use the same variables:

```bash
trazo --endpoint "$TRAZO_ENDPOINT" tail <run_id>
```

---

## Operations

### Backups

`scripts/prod/backup.sh` writes a PostgreSQL dump and a blob-store archive to
`./backups` (gitignored), and removes backups older than 14 days. It is safe to
run while the stack is serving. Schedule it nightly:

```bash
crontab -e
# add:
15 3 * * * cd /opt/trazo && scripts/prod/backup.sh >> /var/log/trazo-backup.log 2>&1
```

A backup on the same disk does not survive losing that disk. Copy `backups/` off
the server — to object storage, or another machine — on the same schedule.

### Restoring from a backup

```bash
cd /opt/trazo
COMPOSE="docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml"

$COMPOSE stop control-plane caddy

# Database: replaces the current contents
$COMPOSE exec -T postgres sh -c \
  'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < backups/trazo-db-<timestamp>.dump

# Blob store
$COMPOSE run --rm --no-deps -T --entrypoint sh control-plane -c \
  'rm -rf /var/lib/trazo/blobs/* && tar -C /var/lib/trazo -xzf - && chown -R 10001:10001 /var/lib/trazo/blobs' \
  < backups/trazo-blobs-<timestamp>.tar.gz

$COMPOSE up -d
```

Test a restore on a spare server before you need one.

### Updating

```bash
cd /opt/trazo
scripts/prod/backup.sh
git pull
make prod-up
```

Database migrations run automatically when the control plane starts.

### Rotating credentials

Edit `deploy/.env.production`, then run `make prod-up` to apply it.

| Credential | Effect of changing it |
|---|---|
| `TRAZO_DASHBOARD_PASSWORD` | New password; every current session is signed out |
| `TRAZO_SESSION_SECRET` | Every current session is signed out |
| `TRAZO_API_KEY` | Every agent and CLI must be updated to the new key |
| `REDIS_PASSWORD` | Transparent; both sides read it from the file |
| `POSTGRES_PASSWORD` | **Do not change it in the file alone.** The database keeps its original password. Change it inside Postgres first (`ALTER USER trazo PASSWORD '...'`), then in the file |

Generate replacement values with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(36))"
```

### Logs

Every container logs to stdout with rotation (10 MB per file, 5 files), so logs
cannot fill the disk. The reverse proxy writes one JSON line per request.

```bash
make prod-logs
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml logs caddy
```

### Uptime monitoring

Point an external monitor at `https://trazo.example.com/healthz` for liveness,
and `https://trazo.example.com/readyz` to also check the database and Redis. Both
are public and return no sensitive data.

---

## Security model

- **Transport.** TLS terminates at Caddy. HTTP only redirects to HTTPS. HSTS is
  set for two years, but without `includeSubDomains`, so other hosts under the
  same domain are not affected.
- **Browser access.** One shared dashboard password. A successful sign-in sets
  an `HttpOnly`, `Secure`, `SameSite=Strict`, `__Host-` prefixed session cookie,
  so page scripts cannot read it, it is never sent cross-site, and no subdomain
  can set or read it. Sessions expire after `TRAZO_SESSION_TTL_HOURS` (default
  12).
- **Programmatic access.** The API key, as `Authorization: Bearer <key>`, is
  required to send events or evaluate policy, and is also accepted for reads, so
  the SDK and CLI work against a protected deployment. A browser session can
  read but never write.
- **Brute force.** Five failed sign-ins from one client within fifteen minutes
  locks that client out for the rest of the window. Successful sign-ins are
  never throttled by other clients' failures.
- **Network.** Only Caddy has a published port or a route to the internet. The
  database, Redis, and OPA are on a network with no route out; the control plane
  and dashboard are reachable only through Caddy.
- **Containers.** The control plane runs as an unprivileged user. Every container
  drops all Linux capabilities except the few it needs, runs with
  `no-new-privileges`, and has a memory limit. The dashboard and OPA containers
  run with a read-only filesystem.
- **Startup safeguards.** In production the control plane refuses to start if any
  secret is missing, shorter than its minimum, or still a development default,
  and it lists every problem at once.

### Known limits

- **One shared password, not user accounts.** There is no per-user audit trail
  of who viewed what, and no roles. Share the password only with people who
  should see every run. Per-user accounts and SSO are on the roadmap.
- **A single server.** The sign-in throttle is per process, and there is no
  high-availability failover. This is sized for a team, not a public service.
- **Trace data is as sensitive as what your agents handle.** The SDK redacts
  common credential fields before sending, but model prompts, tool arguments,
  and results are stored as recorded. Review `TRAZO_REDACT_KEYS` before pointing
  an agent that handles personal data at this deployment.

---

## Troubleshooting

**The certificate is never issued.** Caddy's logs (`make prod-logs`) will show
the ACME error. Almost always, either DNS does not yet point at this server
(`dig +short <domain>`), or port 80 is blocked by a firewall — the HTTP challenge
needs it. Fix the cause and Caddy retries on its own.

**`compose up` fails with "required variable ... is missing a value".**
`deploy/.env.production` is missing or incomplete. Run `make prod-init`.

**The control plane restarts in a loop with "refusing to start in production".**
A secret in `deploy/.env.production` is missing, too short, or a placeholder. The
log lists every one. Regenerate with `make prod-init` on a fresh install, or fix
the listed values.

**The control plane cannot connect to the database after reinstalling.** The
database volume kept its original password, but a newly generated
`deploy/.env.production` has a different one. Restore the original file, or on
an install with no data worth keeping, remove the volume:
`docker compose -f deploy/docker-compose.prod.yml down --volumes`.

**The dashboard's live indicator says "offline", but pages load.** The live
event stream (`/v1/live/*`, Server-Sent Events) is being buffered or compressed
somewhere between the browser and the control plane. The bundled Caddyfile
already exempts it. If you put a CDN or another proxy in front, configure it to
neither buffer nor compress `text/event-stream`. This is easy to miss because
`curl` sends no `Accept-Encoding` header, so the stream works when tested from
the command line while failing in every browser.

**Signing in always says "Too many failed attempts".** That client made five
failed attempts within fifteen minutes. Wait for the window to pass, or restart
the control plane to clear it.

**Ports 80 or 443 are already in use.** Another web server is running on the
host. Stop it, or set `HTTP_PORT` and `HTTPS_PORT` in `deploy/.env.production`
and put that server in front instead — automatic certificates then need extra
configuration.

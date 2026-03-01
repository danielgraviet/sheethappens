# SheetHappens Runbook

Operational guide for common incidents and maintenance tasks.

---

## Validating Service Health

```bash
curl https://<your-railway-domain>/health
# Expected: {"status":"ok","service":"sheethappens"}

curl https://<your-railway-domain>/sync
# Expected: {"status":"ok","total_fetched":N,"skipped_duplicates":N,"newly_inserted":N,"failures":0}
```

Check Railway logs for `ALERT:` prefixed lines to identify issues quickly.

---

## Railway Deployment

### Initial Setup
1. Create a new Railway project and connect the GitHub repo.
2. Railway auto-detects `railway.toml` — no manual build config needed.
3. Add all environment variables in Railway → project → Variables:

| Variable | Value |
|---|---|
| `CANVAS_TOKEN` | Canvas personal access token |
| `CANVAS_DOMAIN` | e.g. `byu.instructure.com` |
| `SPREADSHEET_ID` | Google Sheet ID from URL |
| `REDIS_URL` | Upstash Redis connection string (`rediss://...`) |
| `GOOGLE_CREDS_JSON` | Full stringified service account JSON (see note below) |

> **Note on `GOOGLE_CREDS_JSON`:** On Railway, paste the raw JSON string directly as the variable value — Railway injects it as a true env var, so the dotenv `\n` parsing issue does not apply. Do not use a file path here.

### CRON Job Setup
1. In your Railway project, click **New** → **Cron Job**.
2. Set the schedule to `0 */6 * * *` (every 6 hours).
3. Set the command to:
   ```
   curl -s https://<your-railway-domain>/sync
   ```
4. Railway will trigger this on schedule and log the response.

---

## Rotating Credentials

### Canvas Token
1. In Canvas → Account → Settings → Approved Integrations → delete old token → create new one.
2. In Railway → Variables → update `CANVAS_TOKEN`.
3. Railway redeploys automatically. Verify with `/health`.

### Google Service Account Credentials
1. In Google Cloud Console → IAM → Service Accounts → select account → Keys → Add Key → JSON.
2. Minify the downloaded JSON:
   ```bash
   cat new-key.json | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)))"
   ```
3. In Railway → Variables → update `GOOGLE_CREDS_JSON` with the new value.
4. Revoke the old key in Google Cloud Console after confirming the new one works.

---

## Recovering from Outages

### Redis Outage (Upstash)
- **Symptom:** `/sync` logs Redis connection errors; assignments may be re-inserted on next run.
- **Impact:** Idempotency guard is down — duplicate rows possible until Redis recovers.
- **Recovery:**
  1. Check Upstash dashboard for service status.
  2. Verify `REDIS_URL` is correct in Railway variables.
  3. Once Redis recovers, manually delete duplicate rows from the Google Sheet.
  4. Redis keys auto-expire after 90 days — no manual cleanup needed.

### Google Sheets Outage
- **Symptom:** `/sync` returns `failures > 0`, logs show `SheetsAPIError`.
- **Impact:** Assignments not written; Redis not marked — will retry cleanly on next sync.
- **Recovery:**
  1. Check [Google Workspace Status](https://www.google.com/appsstatus).
  2. Verify the service account still has Editor access to the sheet.
  3. Verify `SPREADSHEET_ID` is correct.
  4. Trigger a manual sync via `curl https://<domain>/sync` once resolved.

### Canvas API Outage
- **Symptom:** `/sync` logs `ALERT: Canvas API unreachable`.
- **Impact:** No assignments fetched — no data loss, sync simply skips the run.
- **Recovery:**
  1. Check Canvas status page for your institution.
  2. If token expired, rotate it (see above).
  3. Sync will resume automatically on next CRON trigger.

---

## Manually Triggering a Sync

```bash
curl https://<your-railway-domain>/sync
```

---

## Clearing Redis State (full re-sync)

If you need all assignments to be re-inserted (e.g. sheet was accidentally cleared):

```bash
# Connect to Upstash via redis-cli or Upstash console
# Delete all sheethappens keys:
redis-cli -u $REDIS_URL --scan --pattern "sheethappens:seen:*" | xargs redis-cli -u $REDIS_URL del
```

Then trigger a manual sync — all assignments will be re-inserted.

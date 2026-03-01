# 🎓 SheetHappens: Canvas-to-Sheets Automation

Because when school gets busy, **SheetHappens**. This is a lightweight Python service designed to bridge the gap between Canvas LMS and Google Sheets, ensuring your academic life is automatically organized.

---

## 🛠️ Tech Stack
- **Language:** Python 3.11+
- **Framework:** FastAPI
- **Database (State):** Upstash Redis (Serverless)
- **Deployment:** Railway
- **External APIs:** Canvas LMS API, Google Sheets API (v4)

---

## 🏗️ System Architecture



### 1. The Adapter Pattern
The service uses an **Adapter Layer** to maintain decoupling. It converts the nested JSON returned by the Canvas API into a flat, standardized dictionary format for Google Sheets.

### 2. Idempotency & Deduplication
To prevent duplicate rows:
- Each Canvas assignment has a unique `assignment_id`.
- The service checks **Upstash Redis** for the ID before writing.
- If the ID is missing, it syncs the data and caches the ID in Redis.

### 3. Automated Sync (CRON)
A **Railway CRON job** triggers the `/sync` endpoint every 6 hours, keeping the spreadsheet updated without manual intervention.

---

## 🔄 Logic Flow
1. **Trigger:** Railway CRON sends a GET request to `/sync`.
2. **Fetch:** FastAPI queries Canvas API for upcoming assignments.
3. **Adapt:** Data is cleaned via the `AssignmentAdapter`.
4. **Deduplicate:** Service cross-references `assignment_id` with Upstash.
5. **Load:** New assignments are appended to Google Sheets.
6. **Finalize:** Successfully synced IDs are stored in Redis.

---

## 🔑 Environment Variables Required
| Variable | Description |
| :--- | :--- |
| `CANVAS_TOKEN` | Personal Access Token from Canvas |
| `CANVAS_DOMAIN` | Your school's Canvas URL |
| `SPREADSHEET_ID` | The ID of your Google Sheet |
| `REDIS_URL` | Upstash Redis Connection String |
| `GOOGLE_CREDS_JSON` | **Full Stringified JSON** from your Service Account key |
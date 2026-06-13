# Docker Desktop Setup

This runs the CSP Agent API/frontend and a local Postgres database together.

## 1. Install Docker Desktop

Install Docker Desktop for Mac and open it once. Wait until Docker says it is running.

## 2. Confirm your `.env`

Keep your real keys in `.env`. Do not commit that file.

The app container reads `.env`, and Docker Compose also provides:

```text
DATABASE_URL=postgresql://csp_agent:csp_agent_dev_password@db:5432/csp_agent
```

## 3. Start the app and database

From the project folder:

```bash
docker compose up --build
```

Then open:

```text
http://127.0.0.1:8000
```

## 4. See the database in Docker Desktop

In Docker Desktop:

- Go to Containers
- Open `csp-agent`
- You should see `csp-agent-app` and `csp-agent-db`

## 5. Connect to Postgres from terminal

```bash
docker compose exec db psql -U csp_agent -d csp_agent
```

Useful checks:

```sql
\dt
SELECT * FROM recommendation_runs LIMIT 5;
SELECT * FROM user_decisions LIMIT 5;
```

Exit Postgres:

```sql
\q
```

## 6. Stop everything

```bash
docker compose down
```

This stops the containers but keeps the database volume.

## 7. Reset the local database

Only do this if you want to delete all local Postgres data:

```bash
docker compose down -v
docker compose up --build
```

## Current state

Postgres is created and the schema is initialized. The app still uses the local JSON paper store for now.

Next step: migrate `paper_store.py` to write recommendation runs, user decisions, paper orders, and positions into Postgres using `DATABASE_URL`.

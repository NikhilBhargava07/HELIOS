# Docker Desktop Setup

This runs the CSP Agent API/frontend and a local Postgres database together.

## 1. Install Docker Desktop

Install Docker Desktop for Mac and open it once. Wait until Docker says it is running.

## 2. Confirm your `.env`

Keep your real keys in `.env`. Do not commit that file.

The app container and Postgres service read these local-only values from `.env`:

```text
POSTGRES_DB=your_database_name
POSTGRES_USER=your_database_user
POSTGRES_PASSWORD=your_local_database_password
DATABASE_URL=postgresql://your_database_user:your_local_database_password@db:5432/your_database_name
```

Use matching values in `POSTGRES_*` and `DATABASE_URL`. The `.env` file is ignored by Git.

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
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
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

Postgres is the application's persistent memory store. Database code lives in
`backend/memory/`, while live positions and buying power come from Alpaca.

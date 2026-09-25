-- deploy/postgres/init/01-create-databases.sql
-- Runs ONLY on first init of an empty data directory.
-- Docker mounts this into /docker-entrypoint-initdb.d/.

-- Langfuse: свои таблицы создаёт сам Langfuse.
CREATE DATABASE langfuse;

-- LiteLLM Proxy DB: свои таблицы создаёт сам LiteLLM (Prisma migrations).
CREATE DATABASE litellm;

-- Основная БД приложения: POSTGRES_DB=postgres.
-- Все схемы (palatium_ai, edms_assistant, knowledge, memory) — внутри.
\connect postgres
CREATE EXTENSION IF NOT EXISTS vector;

\connect langfuse
CREATE EXTENSION IF NOT EXISTS vector;

\connect litellm
CREATE EXTENSION IF NOT EXISTS vector;
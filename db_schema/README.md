# Database Setup

## Quickstart
1. Install PostgreSQL and create a Postgres account
2. Change to `db_schema/` director
```
cd db_schema
```
2. Start Postgres and log into psql session
```
brew services start postgresql@18
psql -h localhost -U postgres
```
In psql session:

3. Set up DB tables
```
\i ./create_tables.sql
```

## Clear All Tables for Clean Slate
Run
```
\i ./start_new.sql
```
# Database Setup

## Quickstart
1. Install PostgreSQL and create a Postgres account
```
// If you need to have postgresql@18 first in your PATH, run:
echo 'export PATH="/usr/local/opt/postgresql@18/bin:$PATH"' >> ~/.zshrc

// For compilers to find postgresql@18 you may need to set:
export LDFLAGS="-L/usr/local/opt/postgresql@18/lib"
export CPPFLAGS="-I/usr/local/opt/postgresql@18/include"
```
2. Change to `db_schema/` directory
```
cd db_schema
```
3. Start Postgres and log into psql session
```
brew services start postgresql@18
psql -h localhost -U postgres
```
In psql session:

4. Set up DB tables
```
\i ./create_tables.sql
```

The DB is ready to be used. 

## Clear All Tables for Clean Slate
Run
```
\i ./start_new.sql
```
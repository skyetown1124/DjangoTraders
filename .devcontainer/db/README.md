`01_djangotraders.sql` is a full dump of the DjangoTraders database (the course data plus the
edge-case rows from `test_data/edge_case_test_data.sql`). Postgres loads it automatically the first
time the Codespace's database starts. To start over with fresh data, rebuild the Codespace
(Command Palette > "Codespaces: Rebuild Container") after deleting the `postgres-data` volume, or run:

    psql -h localhost -U postgres -c 'DROP DATABASE "DjangoTraders" WITH (FORCE)' -c 'CREATE DATABASE "DjangoTraders"'
    psql -h localhost -U postgres -d DjangoTraders -f .devcontainer/db/01_djangotraders.sql

(password: ISM672Python)

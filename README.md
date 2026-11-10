# DjangoTraders
app for class

ISM 672 Assignment 3 — Dashboards for Three Users (customer, employee and supplier portals).

## Run it in GitHub Codespaces

1. On this repo's page: **Code → Codespaces → Create codespace on main**.
2. Wait for setup to finish (first time takes a few minutes: it starts Postgres, loads the
   DjangoTraders database and installs `requirements.txt`).
3. In the terminal: `python manage.py runserver`
4. Open the forwarded port 8000 when VS Code offers it (or from the **Ports** tab).

Sign-in: customers use their customer ID with password `pass`; employees use their birth year;
suppliers use `pass`.

## Run it locally

Create a virtual environment, `pip install -r requirements.txt`, point `DATABASES` in
`DjangoTraders/settings.py` at your own Postgres, then `python manage.py runserver`.

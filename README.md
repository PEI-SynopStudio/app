# SynopStudio

Arranque local:

```bash
docker compose up --build

# BD
docker compose up -d postgres
```

Apagar:

```bash
docker compose down -v
```


## Virtual Environment

```bash
python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements-dev.txt

python -m pytest -v

```


# SynopStudio

Arranque local:

```bash
docker compose up --build
```

Apagar:

```bash
docker compose down -v
```


## Virtual Environment

```bash
python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt

python -m pytest -v

```


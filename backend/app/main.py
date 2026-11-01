from fastapi import FastAPI

from app.api import ingestion, projects
from app.core.config import APP_TITLE, HEALTH_OK, HEALTH_ROUTE

app = FastAPI(title=APP_TITLE)
app.include_router(projects.router)
app.include_router(ingestion.router)

@app.get(HEALTH_ROUTE)
def health():
    return {"status": HEALTH_OK}

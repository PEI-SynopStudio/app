from fastapi import FastAPI

from app.api import projects
from app.core.config import APP_TITLE, HEALTH_OK, HEALTH_ROUTE

app = FastAPI(title=APP_TITLE)
app.include_router(projects.router)

@app.get(HEALTH_ROUTE)
def health():
    return {"status": HEALTH_OK}
from fastapi import FastAPI

from app.api.routes import projects

app = FastAPI(title="PEI API")
app.include_router(projects.router)


@app.get("/health")
def health():
    return {"status": "ok"}
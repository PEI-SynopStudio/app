from fastapi import FastAPI

app = FastAPI(title="PEI API")

@app.get("/health")
def health():
    return {"status": "ok"}
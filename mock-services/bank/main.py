from fastapi import FastAPI


app = FastAPI(title="ChargeGuard Mock Bank API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "dataset_version": "1"}

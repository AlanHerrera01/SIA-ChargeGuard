from fastapi import FastAPI


app = FastAPI(title="ChargeGuard Mock Merchant API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

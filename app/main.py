from fastapi import FastAPI

app = FastAPI(
    title="SpendWise API",
    description="Expense tracking REST API powered by FastAPI and Keycloak",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "application": "SpendWise API"
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Welcome to SpendWise API",
        "docs": "/docs"
    }

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from app.routes import scrape_api, trigger_scrape, register_user

app = FastAPI()

# ✅ Root endpoint - open (no API key)
@app.get("/", response_class=PlainTextResponse)
def read_root():
    return "Job Alert API is live 🚀"

# ✅ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Register routes
app.include_router(scrape_api.router)
app.include_router(trigger_scrape.router)
app.include_router(register_user.router)

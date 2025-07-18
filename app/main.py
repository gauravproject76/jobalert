from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from app.routes import admin_api, user_api, register_user

app = FastAPI()

# ✅ Root endpoint - open (no API key)
@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return PlainTextResponse("Job Alert API is live 🚀")


# ✅ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Register routes
app.include_router(admin_api.router)
app.include_router(user_api.router)
app.include_router(register_user.router)


for route in app.routes:
    print(f"{route.path} [{','.join(route.methods)}]")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from chat import router as chat_router
from whatsapp import router as whatsapp_router
from meta_whatsapp import router as meta_router
from email_agent import router as email_router
from voice_agent import router as voice_router
from credits import router as credits_router
from admin import router as admin_router
from auth import router as auth_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://agentflow-q6uaftq71-mridul0hubs-projects.vercel.app",
        "https://agentflow-sage.vercel.app",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/chat")
app.include_router(whatsapp_router, prefix="/whatsapp")
app.include_router(meta_router, prefix="/meta")
app.include_router(email_router, prefix="/email")
app.include_router(voice_router, prefix="/voice")
app.include_router(credits_router, prefix="/credits")
app.include_router(admin_router, prefix="/admin")
app.include_router(auth_router, prefix="/auth")

@app.get("/")
async def root():
    return {"status": "AEZIO AI Agents Backend Running!"}
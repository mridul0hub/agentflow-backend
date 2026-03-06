from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from chat import router as chat_router
from whatsapp import router as whatsapp_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://agentflow-git-main-mridul0hubs-projects.vercel.app",
        "https://agentflow-sage.vercel.app",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/chat")
app.include_router(whatsapp_router, prefix="/whatsapp")

@app.get("/")
async def root():
    return {"status": "AgentFlow Backend Running!"}

import os
from dotenv import load_dotenv
from fastapi import APIRouter
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

load_dotenv(dotenv_path="../.env")

router = APIRouter()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# Store conversations
sessions = {}

class ChatRequest(BaseModel):
    session_id: str
    message: str
    knowledge: str

@router.post("/message")
async def chat_message(req: ChatRequest):
    if req.session_id not in sessions:
        sessions[req.session_id] = []

    system_prompt = f"""
You are a helpful customer support agent for a business.
Use ONLY the information below to answer questions.
If you don't know the answer, say "Let me connect you with a human agent."
Never make up information.

BUSINESS INFORMATION:
{req.knowledge}

Always be polite, short and helpful.
Reply in the same language the customer uses.
"""

    messages = [SystemMessage(content=system_prompt)]
    for msg in sessions[req.session_id]:
        messages.append(msg)
    messages.append(HumanMessage(content=req.message))

    response = llm.invoke(messages)
    ai_reply = response.content

    sessions[req.session_id].append(HumanMessage(content=req.message))
    sessions[req.session_id].append(AIMessage(content=ai_reply))

    if len(sessions[req.session_id]) > 20:
        sessions[req.session_id] = sessions[req.session_id][-20:]

    return {"reply": ai_reply}

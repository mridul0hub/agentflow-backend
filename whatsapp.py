import os
from dotenv import load_dotenv
from fastapi import APIRouter, Request, Response
from twilio.rest import Client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

load_dotenv(dotenv_path="D:/AI_Agent_SaaS/.env")

router = APIRouter()

twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

conversations = {}

def get_system_prompt():
    return """
You are a helpful WhatsApp assistant for a business.
Reply short and clearly. Maximum 2-3 sentences per reply.
Be polite and helpful.

BUSINESS INFORMATION:
Business Name: Dr. Sharma Skin Clinic
Doctor: Dr. Rajesh Sharma
Timings: Monday to Saturday 10am to 8pm
Sunday: Closed
Fees: Consultation 500 rupees
Services: Acne, Skin allergy, Hair fall
Location: Near City Mall Kota Rajasthan
Payment: Cash and UPI accepted

If you cannot answer say: Let me check with our team!
Reply in same language customer uses.
"""

def get_ai_response(customer_number: str, message: str) -> str:
    if customer_number not in conversations:
        conversations[customer_number] = []

    messages = [SystemMessage(content=get_system_prompt())]
    for msg in conversations[customer_number]:
        messages.append(msg)
    messages.append(HumanMessage(content=message))

    response = llm.invoke(messages)
    ai_reply = response.content

    conversations[customer_number].append(HumanMessage(content=message))
    conversations[customer_number].append(AIMessage(content=ai_reply))

    if len(conversations[customer_number]) > 10:
        conversations[customer_number] = conversations[customer_number][-10:]

    return ai_reply

@router.post("/message")
async def whatsapp_message(request: Request):
    form_data = await request.form()
    incoming_message = form_data.get("Body", "").strip()
    customer_number = form_data.get("From", "")

    print(f"Message received: {incoming_message}")
    print(f"From: {customer_number}")

    if not incoming_message:
        return Response(content="", media_type="text/plain")

    try:
        ai_reply = get_ai_response(customer_number, incoming_message)
        print(f"AI Reply: {ai_reply}")

        twilio_client.messages.create(
            body=ai_reply,
            from_="whatsapp:+14155238886",
            to=customer_number
        )
        print("Message sent successfully!")

    except Exception as e:
        print(f"Error: {e}")

    return Response(content="", media_type="text/plain")
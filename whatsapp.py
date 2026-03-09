import os
from dotenv import load_dotenv
from fastapi import APIRouter, Request, Response
from twilio.rest import Client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from supabase import create_client

load_dotenv(dotenv_path="D:/AI_Agent_SaaS/.env")

router = APIRouter()

# Twilio
twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

# Gemini AI
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0.3,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# Supabase
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# ─────────────────────────────────────────
# Fetch agent config from Supabase
# ─────────────────────────────────────────
def get_agent_config(whatsapp_number: str):
    try:
        clean_number = whatsapp_number.replace("whatsapp:", "").strip()
        print(f"🔍 Looking up config for: {clean_number}")

        result = supabase.table("whatsapp_agents") \
            .select("*") \
            .eq("whatsapp_number", clean_number) \
            .eq("is_active", True) \
            .single() \
            .execute()

        if result.data:
            print(f"✅ Config found: {result.data['business_name']}")
            return result.data
        else:
            print(f"⚠️ No active agent for: {clean_number}")
            return None

    except Exception as e:
        print(f"❌ Supabase config error: {e}")
        return None

# ─────────────────────────────────────────
# Build system prompt
# ─────────────────────────────────────────
def build_system_prompt(config: dict) -> str:
    if not config:
        return """
You are a helpful WhatsApp business assistant.
Reply short and clearly. Maximum 2-3 sentences.
Be polite and helpful.
If you cannot answer, say: Please contact us directly for more information!
Reply in the same language the customer uses.
"""
    prompt = f"""
You are a helpful WhatsApp assistant for {config.get('business_name', 'this business')}.
Reply short and clearly. Maximum 2-3 sentences per reply.
Be polite, warm and professional.
Always represent the business positively.

BUSINESS INFORMATION:
Business Name: {config.get('business_name', 'N/A')}
"""
    if config.get('timings'):
        prompt += f"Working Hours: {config.get('timings')}\n"
    if config.get('services'):
        prompt += f"Services: {config.get('services')}\n"
    if config.get('fees'):
        prompt += f"Fees/Pricing: {config.get('fees')}\n"
    if config.get('location'):
        prompt += f"Location: {config.get('location')}\n"
    if config.get('extra_info'):
        prompt += f"Additional Info: {config.get('extra_info')}\n"

    prompt += """
INSTRUCTIONS:
- Always greet the customer warmly on first message
- Keep replies short — maximum 2-3 sentences
- If someone asks for appointment, ask for their preferred date and time
- If you cannot answer something, say: "Let me check with our team and get back to you!"
- Reply in the SAME language the customer uses (Hindi or English)
- Never make up information not provided above
- Be helpful, friendly and professional at all times
"""
    return prompt

# ─────────────────────────────────────────
# Save message to Supabase
# ─────────────────────────────────────────
def save_message(business_number: str, customer_number: str, role: str, message: str):
    try:
        clean_business = business_number.replace("whatsapp:", "").strip()
        clean_customer = customer_number.replace("whatsapp:", "").strip()

        supabase.table("chat_history").insert({
            "business_number": clean_business,
            "customer_number": clean_customer,
            "role": role,
            "message": message
        }).execute()

        print(f"💾 Saved [{role}]: {message[:50]}...")

    except Exception as e:
        print(f"❌ Save message error: {e}")

# ─────────────────────────────────────────
# Load chat history from Supabase
# ─────────────────────────────────────────
def load_chat_history(business_number: str, customer_number: str) -> list:
    try:
        clean_business = business_number.replace("whatsapp:", "").strip()
        clean_customer = customer_number.replace("whatsapp:", "").strip()

        result = supabase.table("chat_history") \
            .select("role, message") \
            .eq("business_number", clean_business) \
            .eq("customer_number", clean_customer) \
            .order("created_at", desc=False) \
            .limit(20) \
            .execute()

        messages = []
        if result.data:
            for row in result.data:
                if row["role"] == "user":
                    messages.append(HumanMessage(content=row["message"]))
                elif row["role"] == "assistant":
                    messages.append(AIMessage(content=row["message"]))

        print(f"📖 Loaded {len(messages)} messages from history")
        return messages

    except Exception as e:
        print(f"❌ Load history error: {e}")
        return []

# ─────────────────────────────────────────
# Get AI response
# ─────────────────────────────────────────
def get_ai_response(customer_number: str, business_number: str, message: str) -> str:
    # Fetch config
    config = get_agent_config(business_number)
    system_prompt = build_system_prompt(config)

    # Load history from Supabase
    history = load_chat_history(business_number, customer_number)

    # Build messages
    messages = [SystemMessage(content=system_prompt)]
    messages.extend(history)
    messages.append(HumanMessage(content=message))

    # Get AI reply
    response = llm.invoke(messages)
    ai_reply = response.content

    # Save both messages to Supabase
    save_message(business_number, customer_number, "user", message)
    save_message(business_number, customer_number, "assistant", ai_reply)

    return ai_reply

# ─────────────────────────────────────────
# WhatsApp webhook
# ─────────────────────────────────────────
@router.post("/message")
async def whatsapp_message(request: Request):
    form_data = await request.form()

    incoming_message = form_data.get("Body", "").strip()
    customer_number  = form_data.get("From", "")
    business_number  = form_data.get("To", "")

    print(f"📩 Message : {incoming_message}")
    print(f"👤 From    : {customer_number}")
    print(f"🏥 To      : {business_number}")

    if not incoming_message:
        return Response(content="", media_type="text/plain")

    try:
        ai_reply = get_ai_response(customer_number, business_number, incoming_message)
        print(f"🤖 AI Reply: {ai_reply}")

        twilio_client.messages.create(
            body=ai_reply,
            from_=business_number,
            to=customer_number
        )

        print("✅ Message sent!")

    except Exception as e:
        print(f"❌ Error: {e}")

    return Response(content="", media_type="text/plain")
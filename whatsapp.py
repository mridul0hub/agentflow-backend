import os
import json
import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Request, Response
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from supabase import create_client

load_dotenv(dotenv_path="D:/AI_Agent_SaaS/.env")

router = APIRouter()

# Gemini AI
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# Supabase
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# Meta credentials
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "vasuagents2024")

# ─────────────────────────────────────────
# Webhook Verification (GET)
# Meta calls this once to verify webhook
# ─────────────────────────────────────────
@router.get("/message")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    print(f"🔔 Webhook verify: mode={mode}, token={token}")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("✅ Webhook verified!")
        return Response(content=challenge, media_type="text/plain")
    else:
        print("❌ Webhook verification failed!")
        return Response(content="Forbidden", status_code=403)

# ─────────────────────────────────────────
# Fetch agent config from Supabase
# ─────────────────────────────────────────
def get_agent_config(phone_number_id: str):
    try:
        print(f"🔍 Looking up config for phone_number_id: {phone_number_id}")

        result = supabase.table("whatsapp_agents") \
            .select("*") \
            .eq("phone_number_id", phone_number_id) \
            .eq("is_active", True) \
            .single() \
            .execute()

        if result.data:
            print(f"✅ Config found: {result.data['business_name']}")
            return result.data
        else:
            print(f"⚠️ No active agent for phone_number_id: {phone_number_id}")
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
        supabase.table("chat_history").insert({
            "business_number": business_number,
            "customer_number": customer_number,
            "role": role,
            "message": message
        }).execute()
        print(f"💾 Saved [{role}]: {message[:50]}")
    except Exception as e:
        print(f"❌ Save message error: {e}")

# ─────────────────────────────────────────
# Load chat history from Supabase
# ─────────────────────────────────────────
def load_chat_history(business_number: str, customer_number: str) -> list:
    try:
        result = supabase.table("chat_history") \
            .select("role, message") \
            .eq("business_number", business_number) \
            .eq("customer_number", customer_number) \
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
# Send reply via Meta Cloud API
# ─────────────────────────────────────────
async def send_meta_message(phone_number_id: str, to: str, message: str, access_token: str):
    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        print(f"📤 Meta API response: {response.status_code} - {response.text}")
        return response

# ─────────────────────────────────────────
# Get AI response
# ─────────────────────────────────────────
def get_ai_response(customer_number: str, business_number: str, phone_number_id: str, message: str) -> str:
    config = get_agent_config(phone_number_id)
    system_prompt = build_system_prompt(config)

    history = load_chat_history(business_number, customer_number)

    messages = [SystemMessage(content=system_prompt)]
    messages.extend(history)
    messages.append(HumanMessage(content=message))

    response = llm.invoke(messages)
    return response.content

# ─────────────────────────────────────────
# Webhook Receiver (POST)
# Meta sends messages here
# ─────────────────────────────────────────
@router.post("/message")
async def receive_message(request: Request):
    try:
        body = await request.json()
        print(f"📩 Meta webhook received: {json.dumps(body, indent=2)}")

        # Extract message data
        entry    = body.get("entry", [])[0]
        changes  = entry.get("changes", [])[0]
        value    = changes.get("value", {})

        phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
        business_number = value.get("metadata", {}).get("display_phone_number", "")

        messages = value.get("messages", [])

        if not messages:
            print("ℹ️ No messages in webhook (status update)")
            return {"status": "ok"}

        msg             = messages[0]
        customer_number = msg.get("from", "")
        msg_type        = msg.get("type", "")

        # Only handle text messages
        if msg_type != "text":
            print(f"ℹ️ Ignoring non-text message type: {msg_type}")
            return {"status": "ok"}

        incoming_text = msg.get("text", {}).get("body", "").strip()

        print(f"📩 Message      : {incoming_text}")
        print(f"👤 From         : {customer_number}")
        print(f"🏥 Business     : {business_number}")
        print(f"📱 Phone ID     : {phone_number_id}")

        if not incoming_text:
            return {"status": "ok"}

        # Get access token — use permanent token from config or env
        config = get_agent_config(phone_number_id)
        access_token = META_ACCESS_TOKEN
        if config and config.get("access_token"):
            access_token = config.get("access_token")

        # Save user message
        save_message(business_number, customer_number, "user", incoming_text)

        # Get AI reply
        ai_reply = get_ai_response(customer_number, business_number, phone_number_id, incoming_text)
        print(f"🤖 AI Reply: {ai_reply}")

        # Save AI reply
        save_message(business_number, customer_number, "assistant", ai_reply)

        # Send reply to customer
        await send_meta_message(phone_number_id, customer_number, ai_reply, access_token)

        print("✅ Reply sent!")

    except Exception as e:
        print(f"❌ Error: {e}")

    return {"status": "ok"}
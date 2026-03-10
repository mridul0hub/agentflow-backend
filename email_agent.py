import os
import resend
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from supabase import create_client

load_dotenv(dotenv_path="D:/AI_Agent_SaaS/.env")

router = APIRouter()

# Resend
resend.api_key = os.getenv("RESEND_API_KEY")

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

# ─────────────────────────────────────────
# Fetch agent config from Supabase
# ─────────────────────────────────────────
def get_agent_config(business_email: str):
    try:
        print(f"🔍 Looking up email agent for: {business_email}")

        result = supabase.table("email_agents") \
            .select("*") \
            .eq("business_email", business_email) \
            .eq("is_active", True) \
            .single() \
            .execute()

        if result.data:
            print(f"✅ Config found: {result.data['business_name']}")
            return result.data
        else:
            print(f"⚠️ No active email agent for: {business_email}")
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
You are a helpful business email assistant.
Reply professionally and clearly.
Keep replies concise — maximum 3-4 sentences.
If you cannot answer, say: Please contact us directly for more information.
Reply in the same language the customer uses.
"""
    prompt = f"""
You are a professional email assistant for {config.get('business_name', 'this business')}.
Reply in a professional, warm, and helpful tone.
Keep replies concise — maximum 3-4 sentences.
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
- Always start with a professional greeting
- Keep replies short and to the point — 3-4 sentences max
- If someone asks for appointment, ask for their preferred date and time
- If you cannot answer something, say: "We will get back to you shortly!"
- Reply in the SAME language the customer uses (Hindi or English)
- Never make up information not provided above
- End with a professional sign-off like "Best regards, [Business Name] Team"
- Be helpful, friendly and professional at all times
"""
    return prompt

# ─────────────────────────────────────────
# Save email to Supabase
# ─────────────────────────────────────────
def save_email(business_email: str, customer_email: str, role: str, subject: str, message: str):
    try:
        supabase.table("email_history").insert({
            "business_email": business_email,
            "customer_email": customer_email,
            "role": role,
            "subject": subject,
            "message": message
        }).execute()
        print(f"💾 Saved [{role}]: {message[:50]}")
    except Exception as e:
        print(f"❌ Save email error: {e}")

# ─────────────────────────────────────────
# Load email history from Supabase
# ─────────────────────────────────────────
def load_email_history(business_email: str, customer_email: str) -> list:
    try:
        result = supabase.table("email_history") \
            .select("role, message") \
            .eq("business_email", business_email) \
            .eq("customer_email", customer_email) \
            .order("created_at", desc=False) \
            .limit(10) \
            .execute()

        messages = []
        if result.data:
            for row in result.data:
                if row["role"] == "user":
                    messages.append(HumanMessage(content=row["message"]))
                elif row["role"] == "assistant":
                    messages.append(AIMessage(content=row["message"]))

        print(f"📖 Loaded {len(messages)} emails from history")
        return messages

    except Exception as e:
        print(f"❌ Load history error: {e}")
        return []

# ─────────────────────────────────────────
# Get AI response
# ─────────────────────────────────────────
def get_ai_response(customer_email: str, business_email: str, subject: str, message: str) -> str:
    config = get_agent_config(business_email)
    system_prompt = build_system_prompt(config)

    history = load_email_history(business_email, customer_email)

    full_message = f"Subject: {subject}\n\n{message}"

    messages = [SystemMessage(content=system_prompt)]
    messages.extend(history)
    messages.append(HumanMessage(content=full_message))

    response = llm.invoke(messages)
    return response.content

# ─────────────────────────────────────────
# Send email via Resend
# ─────────────────────────────────────────
def send_email(to: str, subject: str, reply: str, from_name: str):
    try:
        params = {
            "from": f"{from_name} AI Assistant <onboarding@resend.dev>",
            "to": [to],
            "subject": f"Re: {subject}",
            "html": f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <p>{reply.replace(chr(10), '<br>')}</p>
                    <hr style="border: 1px solid #eee; margin: 20px 0;">
                    <p style="color: #999; font-size: 12px;">
                        This is an automated response powered by Vasu Agents AI.
                    </p>
                </div>
            """
        }
        response = resend.Emails.send(params)
        print(f"📤 Email sent! ID: {response}")
        return response
    except Exception as e:
        print(f"❌ Send email error: {e}")
        return None

# ─────────────────────────────────────────
# Receive email webhook (POST)
# Resend calls this when email is received
# ─────────────────────────────────────────
@router.post("/receive")
async def receive_email(request: Request):
    try:
        body = await request.json()
        print(f"📩 Email received: {body}")

        # Handle both list and dict from Zapier
        if isinstance(body, list):
            body = body[0]
        customer_email  = body.get("From", "")
        business_email  = body.get("To", "")
        subject         = body.get("Subject", "No Subject")
        text_body       = body.get("TextBody", "") or body.get("HtmlBody", "")

        print(f"📩 From    : {customer_email}")
        print(f"🏥 To      : {business_email}")
        print(f"📋 Subject : {subject}")

        if not text_body:
            return {"status": "ok"}

        # Get agent config
        config = get_agent_config(business_email)
        business_name = config.get("business_name", "Business") if config else "Business"

        # Save customer email
        save_email(business_email, customer_email, "user", subject, text_body)

        # Small wait to ensure save completes before AI reads history
        import time
        time.sleep(0.5)

        # Get AI reply
        ai_reply = get_ai_response(customer_email, business_email, subject, text_body)
        print(f"🤖 AI Reply: {ai_reply}")

        # Save AI reply
        save_email(business_email, customer_email, "assistant", f"Re: {subject}", ai_reply)

        # Send reply
        send_email(customer_email, subject, ai_reply, business_name)

        print("✅ Email reply sent!")

    except Exception as e:
        print(f"❌ Error: {e}")

    return {"status": "ok"}

# ─────────────────────────────────────────
# Manual trigger — test endpoint
# ─────────────────────────────────────────
@router.post("/test")
async def test_email(request: Request):
    try:
        body = await request.json()
        to      = body.get("to", "")
        subject = body.get("subject", "Test Email")
        message = body.get("message", "Hello!")

        if not to:
            return {"error": "Please provide 'to' email"}

        send_email(to, subject, message, "Vasu Agents")
        return {"status": "ok", "message": f"Test email sent to {to}"}

    except Exception as e:
        return {"error": str(e)}
import os
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from supabase import create_client
from credits import deduct_credit, has_credits, get_user_id_from_email

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

# Gmail SMTP config
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# ─── Get agent config ─────────────────────────────────────────────────────────
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

# ─── Build system prompt ──────────────────────────────────────────────────────
def build_system_prompt(config: dict) -> str:
    if not config:
        return """
You are a helpful business email assistant.
Reply professionally and clearly. Keep replies concise — 3-4 sentences max.
Reply in the same language the customer uses.
"""
    prompt = f"""
You are a professional email assistant for {config.get('business_name', 'this business')}.
Reply in a professional, warm, and helpful tone.
Keep replies concise — 3-4 sentences max.

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
- Keep replies short — 3-4 sentences max
- If someone asks for appointment, ask for preferred date and time
- Reply in the SAME language the customer uses (Hindi or English)
- Never make up information not provided above
- End with: "Best regards, [Business Name] Team"
"""
    return prompt

# ─── Save email ───────────────────────────────────────────────────────────────
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

# ─── Load email history ───────────────────────────────────────────────────────
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

# ─── Get AI response ──────────────────────────────────────────────────────────
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

# ─── Send email via Gmail SMTP ────────────────────────────────────────────────
def send_email(to: str, subject: str, reply: str, from_name: str):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Re: {subject}"
        msg["From"] = f"{from_name} <{GMAIL_USER}>"
        msg["To"] = to

        # Plain text version
        text_part = MIMEText(reply, "plain", "utf-8")

        # HTML version
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
            <p style="font-size: 15px; line-height: 1.7;">{reply.replace(chr(10), '<br>')}</p>
            <hr style="border: 1px solid #eee; margin: 24px 0;">
            <p style="color: #999; font-size: 12px;">
                This is an automated response powered by AEZIO AI Agents.
            </p>
        </div>
        """
        html_part = MIMEText(html_body, "html", "utf-8")

        msg.attach(text_part)
        msg.attach(html_part)

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to, msg.as_string())

        print(f"📤 Email sent to {to} via Gmail SMTP!")
        return True

    except Exception as e:
        print(f"❌ Gmail SMTP error: {e}")
        return False

# ─── Receive email webhook ────────────────────────────────────────────────────
@router.post("/receive")
async def receive_email(request: Request):
    try:
        body = await request.json()
        print(f"📩 Email received: {body}")

        if isinstance(body, list):
            body = body[0]

        customer_email = body.get("From", "")
        business_email = body.get("To", "")
        subject        = body.get("Subject", "No Subject")
        text_body      = body.get("TextBody", "") or body.get("HtmlBody", "")

        print(f"📩 From    : {customer_email}")
        print(f"🏥 To      : {business_email}")
        print(f"📋 Subject : {subject}")

        if not text_body:
            return {"status": "ok"}

        # Skip automated/noreply emails
        skip_senders = ["no-reply", "noreply", "mailer-daemon", "postmaster", "do-not-reply"]
        if any(s in customer_email.lower() for s in skip_senders):
            print(f"⏭️ Skipping automated email from: {customer_email}")
            return {"status": "ok"}

        # Credit check
        user_id = get_user_id_from_email(business_email)
        if user_id and not has_credits(user_id):
            print(f"❌ No credits for user {user_id}")
            return {"status": "ok"}

        config = get_agent_config(business_email)
        business_name = config.get("business_name", "Business") if config else "Business"

        # Save customer email
        save_email(business_email, customer_email, "user", subject, text_body)
        time.sleep(0.5)

        # Get AI reply
        ai_reply = get_ai_response(customer_email, business_email, subject, text_body)
        print(f"🤖 AI Reply: {ai_reply}")

        # Save AI reply
        save_email(business_email, customer_email, "assistant", f"Re: {subject}", ai_reply)

        # Deduct credit
        if user_id:
            deduct_credit(
                user_id=user_id,
                agent_type="email",
                description=f"Email reply to {customer_email}"
            )

        # Send via Gmail SMTP
        send_email(customer_email, subject, ai_reply, business_name)
        print("✅ Email reply sent!")

    except Exception as e:
        print(f"❌ Error: {e}")

    return {"status": "ok"}

# ─── Test endpoint ────────────────────────────────────────────────────────────
@router.post("/test")
async def test_email(request: Request):
    try:
        body = await request.json()
        to      = body.get("to", "")
        subject = body.get("subject", "Test Email")
        message = body.get("message", "Hello!")
        if not to:
            return {"error": "Please provide 'to' email"}
        success = send_email(to, subject, message, "AEZIO AI Agents")
        return {"status": "ok" if success else "error", "message": f"Test email sent to {to}"}
    except Exception as e:
        return {"error": str(e)}
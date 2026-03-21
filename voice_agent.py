from fastapi import APIRouter, Request
from supabase import create_client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
import os
import httpx
from datetime import datetime

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
RETELL_API_KEY = os.getenv("RETELL_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0.3,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# ─── HELPER: Get voice agent config ──────────────────────────────────────────
def get_voice_agent(phone_number: str):
    try:
        result = supabase.table("voice_agents") \
            .select("*") \
            .eq("phone_number", phone_number) \
            .eq("is_active", True) \
            .single() \
            .execute()
        return result.data
    except:
        return None

# ─── HELPER: Build system prompt ─────────────────────────────────────────────
def build_system_prompt(config: dict) -> str:
    if not config:
        return """
You are a professional receptionist for a clinic.
Greet callers warmly. Keep replies short — 1-2 sentences max.
Answer questions about the clinic. Book appointments when asked.
Always be professional and helpful.
"""
    prompt = f"""
You are a professional receptionist for {config.get('business_name', 'this clinic')}.
You are speaking on a phone call — keep all replies SHORT, max 1-2 sentences.
Be warm, professional and helpful. Speak naturally like a human receptionist.

CLINIC INFORMATION:
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
- Greet with: "Hello! Thank you for calling [Business Name]. How may I help you?"
- Keep every reply to 1-2 sentences maximum — this is a phone call
- If caller wants appointment: ask name, date, time one by one
- After collecting details say: "Perfect, your appointment is booked! We will see you then."
- Speak in the same language the caller uses — Hindi or English
- If caller seems suspicious or spam: politely end the call
- Never make up information not provided above
"""
    return prompt

# ─── HELPER: Save appointment ─────────────────────────────────────────────────
def save_appointment(data: dict):
    try:
        supabase.table("appointments").insert(data).execute()
        return True
    except Exception as e:
        print(f"Appointment save error: {e}")
        return False

# ─── HELPER: WhatsApp alert to business owner ────────────────────────────────
async def alert_client_whatsapp(client_number: str, message: str):
    try:
        TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
        TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
                auth=(TWILIO_SID, TWILIO_TOKEN),
                data={
                    "From": "whatsapp:+14155238886",
                    "To": f"whatsapp:{client_number}",
                    "Body": message
                }
            )
        print(f"✅ WhatsApp alert sent to {client_number}")
    except Exception as e:
        print(f"❌ WhatsApp alert error: {e}")


# ════════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1 — CUSTOM LLM WEBHOOK
# Retell sends conversation here — we respond with AI reply
# Set this URL in Retell: Agent → LLM → Custom LLM URL
# ════════════════════════════════════════════════════════════════════════════════
@router.post("/llm")
async def retell_llm(request: Request):
    try:
        body = await request.json()
        print(f"📞 LLM Request: {body}")

        # Retell sends call info + conversation
        call_info = body.get("call", {})
        business_number = call_info.get("to_number", "")
        customer_number = call_info.get("from_number", "")
        conversation = body.get("transcript", [])

        # Get agent config
        agent = get_voice_agent(business_number)
        system_prompt = build_system_prompt(agent)

        # Build message history
        messages = [SystemMessage(content=system_prompt)]
        for msg in conversation:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        # Get AI response
        response = llm.invoke(messages)
        reply = response.content.strip()
        print(f"🤖 AI Reply: {reply}")

        # Retell Custom LLM response format
        return {
            "response_id": body.get("response_id", 0),
            "content": reply,
            "content_complete": True,
            "end_call": False
        }

    except Exception as e:
        print(f"❌ LLM webhook error: {e}")
        return {
            "response_id": 0,
            "content": "I'm sorry, I'm having trouble right now. Please call back shortly.",
            "content_complete": True,
            "end_call": False
        }


# ════════════════════════════════════════════════════════════════════════════════
# ENDPOINT 2 — EVENT WEBHOOK
# Retell sends call events here — call_started, call_ended, function_call
# Set this URL in Retell: Agent → General → Event Webhook URL
# ════════════════════════════════════════════════════════════════════════════════
@router.post("/webhook")
async def retell_events(request: Request):
    try:
        body = await request.json()
        event = body.get("event", "")
        call = body.get("call", {})
        call_id = call.get("call_id", "")
        customer_number = call.get("from_number", "")
        business_number = call.get("to_number", "")

        print(f"📡 Event: {event} | call: {call_id}")

        # ── Call Started ─────────────────────────────────────────────────────
        if event == "call_started":
            try:
                supabase.table("call_logs").insert({
                    "call_id": call_id,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "status": "in-progress",
                    "started_at": datetime.utcnow().isoformat()
                }).execute()
                print(f"✅ Call started logged: {call_id}")
            except Exception as e:
                print(f"❌ Call start log error: {e}")

        # ── Function Call ─────────────────────────────────────────────────────
        elif event == "function_call":
            fn_name = body.get("name", "")
            fn_args = body.get("args", {})
            print(f"🔧 Function: {fn_name} | args: {fn_args}")

            # book_appointment
            if fn_name == "book_appointment":
                agent = get_voice_agent(business_number)
                appointment_data = {
                    "user_id": agent.get("user_id") if agent else None,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "customer_name": fn_args.get("customer_name", "Unknown"),
                    "appointment_date": fn_args.get("appointment_date", ""),
                    "appointment_time": fn_args.get("appointment_time", ""),
                    "notes": fn_args.get("notes", ""),
                    "status": "pending",
                }
                success = save_appointment(appointment_data)

                # Alert business owner on WhatsApp
                if agent and agent.get("client_whatsapp"):
                    msg = (
                        f"📅 *New Appointment Booked via Voice!*\n"
                        f"Patient: {fn_args.get('customer_name', 'Unknown')}\n"
                        f"Phone: {customer_number}\n"
                        f"Date: {fn_args.get('appointment_date', '—')}\n"
                        f"Time: {fn_args.get('appointment_time', '—')}\n"
                        f"Notes: {fn_args.get('notes', '—')}"
                    )
                    await alert_client_whatsapp(agent["client_whatsapp"], msg)

                return {"result": "Appointment booked successfully!" if success else "Booking failed, please try again."}

            # flag_scam_call
            elif fn_name == "flag_scam_call":
                agent = get_voice_agent(business_number)
                reason = fn_args.get("reason", "Suspicious behavior")

                try:
                    supabase.table("call_logs").update({
                        "is_scam": True,
                        "scam_reason": reason
                    }).eq("call_id", call_id).execute()
                except Exception as e:
                    print(f"❌ Scam flag error: {e}")

                if agent and agent.get("client_whatsapp"):
                    msg = (
                        f"⚠️ *Scam Call Detected!*\n"
                        f"From: {customer_number}\n"
                        f"Reason: {reason}"
                    )
                    await alert_client_whatsapp(agent["client_whatsapp"], msg)

                return {"result": "Scam call flagged."}

        # ── Call Ended ────────────────────────────────────────────────────────
        elif event == "call_ended":
            duration = call.get("duration_ms", 0)
            duration_seconds = int(duration / 1000) if duration else 0
            transcript = call.get("transcript", "")
            summary = call.get("call_analysis", {}).get("call_summary", "")
            sentiment = call.get("call_analysis", {}).get("user_sentiment", "")
            ended_reason = call.get("disconnection_reason", "")

            try:
                supabase.table("call_logs").upsert({
                    "call_id": call_id,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "status": "completed",
                    "duration_seconds": duration_seconds,
                    "summary": summary,
                    "transcript": transcript,
                    "ended_reason": ended_reason,
                    "sentiment": sentiment,
                    "ended_at": datetime.utcnow().isoformat()
                }).execute()
                print(f"✅ Call ended: {call_id} | {duration_seconds}s")
            except Exception as e:
                print(f"❌ Call end log error: {e}")

        return {"status": "ok"}

    except Exception as e:
        print(f"❌ Event webhook error: {e}")
        return {"status": "error", "message": str(e)}


# ── Book appointment via HTTP (for Retell tool call) ──────────────────────────
@router.post("/book-appointment")
async def book_appointment_endpoint(request: Request):
    try:
        body = await request.json()
        print(f"📅 Book appointment: {body}")

        call_id = body.get("call_id", "")
        customer_number = body.get("customer_number", "")
        business_number = body.get("business_number", "")
        agent = get_voice_agent(business_number)

        appointment_data = {
            "user_id": agent.get("user_id") if agent else None,
            "business_number": business_number,
            "customer_number": customer_number,
            "customer_name": body.get("customer_name", "Unknown"),
            "appointment_date": body.get("appointment_date", ""),
            "appointment_time": body.get("appointment_time", ""),
            "notes": body.get("notes", ""),
            "status": "pending",
        }
        success = save_appointment(appointment_data)

        if agent and agent.get("client_whatsapp"):
            msg = (
                f"📅 *New Appointment via Voice!*\n"
                f"Patient: {body.get('customer_name', 'Unknown')}\n"
                f"Phone: {customer_number}\n"
                f"Date: {body.get('appointment_date', '—')}\n"
                f"Time: {body.get('appointment_time', '—')}\n"
                f"Notes: {body.get('notes', '—')}"
            )
            await alert_client_whatsapp(agent["client_whatsapp"], msg)

        return {"result": "Appointment booked successfully!" if success else "Booking failed."}

    except Exception as e:
        return {"result": f"Error: {str(e)}"}


# ── Flag scam via HTTP (for Retell tool call) ─────────────────────────────────
@router.post("/flag-scam")
async def flag_scam_endpoint(request: Request):
    try:
        body = await request.json()
        print(f"⚠️ Flag scam: {body}")

        customer_number = body.get("customer_number", "")
        business_number = body.get("business_number", "")
        reason = body.get("reason", "Suspicious behavior")
        call_id = body.get("call_id", "")
        agent = get_voice_agent(business_number)

        if call_id:
            supabase.table("call_logs").update({
                "is_scam": True,
                "scam_reason": reason
            }).eq("call_id", call_id).execute()

        if agent and agent.get("client_whatsapp"):
            msg = (
                f"⚠️ *Scam Call Detected!*\n"
                f"From: {customer_number}\n"
                f"Reason: {reason}"
            )
            await alert_client_whatsapp(agent["client_whatsapp"], msg)

        return {"result": "Scam flagged successfully."}

    except Exception as e:
        return {"result": f"Error: {str(e)}"}


# ── Get call logs ─────────────────────────────────────────────────────────────
@router.get("/calls/{user_id}")
async def get_call_logs(user_id: str):
    try:
        result = supabase.table("call_logs") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("started_at", desc=True) \
            .limit(50) \
            .execute()
        return {"calls": result.data}
    except Exception as e:
        return {"error": str(e)}
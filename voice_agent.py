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

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.4,
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

# ─── HELPER: Build human-like system prompt ───────────────────────────────────
def build_system_prompt(config: dict) -> str:
    if not config:
        return """
You are Priya, a warm and professional receptionist at a clinic.
You speak naturally like a real human — not like a robot.
Keep every reply to 1-2 short sentences. This is a phone call.
Never repeat your greeting after the first message.
Be warm, friendly and professional at all times.
"""

    prompt = f"""
You are Priya, a warm and professional receptionist for {config.get('business_name', 'this clinic')}.
You are on a PHONE CALL — speak exactly like a real human receptionist would.

PERSONALITY:
- Warm, friendly, professional — like a real clinic receptionist
- Natural conversational flow — not robotic or scripted
- Patient and understanding — repeat information if caller doesn't understand
- Confident but polite

STRICT RULES:
- Keep EVERY reply to 1-2 short sentences MAXIMUM — this is a phone call
- NEVER say "Hello! Thank you for calling..." more than once at the start
- After the greeting, just respond naturally to what the caller says
- Do NOT repeat the clinic name in every response
- Speak naturally — use "ji", "bilkul", "zaroor", "achha" naturally in Hindi
- If caller speaks Hindi — reply fully in Hindi
- If caller speaks English — reply in English
- If caller mixes Hindi/English (Hinglish) — match their style

CLINIC INFORMATION:
Business: {config.get('business_name', 'N/A')}
Doctor: Dr. Sharma (Skin Specialist / Dermatologist)
"""
    if config.get('timings'):
        prompt += f"Timings: {config.get('timings')}\n"
    if config.get('services'):
        prompt += f"Services: {config.get('services')}\n"
    if config.get('fees'):
        prompt += f"Fees: {config.get('fees')}\n"
    if config.get('location'):
        prompt += f"Location: {config.get('location')}\n"
    if config.get('extra_info'):
        prompt += f"Other info: {config.get('extra_info')}\n"

    prompt += """
APPOINTMENT BOOKING FLOW:
When caller wants an appointment:
1. Ask for their name — "Aapka naam kya hai ji?" 
2. After name — confirm it: "Rahul ji, sahi hai?"
3. Ask preferred date — "Kaunsi date chahiye aapko?"
4. Ask preferred time — "Aur time?"
5. Confirm everything together — "Toh Rahul ji, 25 March ko 12 baje — bilkul. Main book kar deta/deti hoon."
6. Then call the book_appointment function

NAME HANDLING:
- If you're not sure about the name, ask them to spell it or repeat
- Say "Sorry, thoda clear nahi hua — naam dobara bata sakte hain?"
- Always confirm name before booking

SCAM DETECTION:
- If caller asks irrelevant questions, uses abusive language, or seems suspicious — politely end the call
- Call the flag_scam_call function

EXAMPLES OF NATURAL RESPONSES:
- Instead of "Hello! Thank you for calling Dr. Sharma Skin Clinic. How may I help you?" 
  → Just say "Haan ji, batayein?"
- Instead of "I understand you want an appointment"
  → "Haan ji, zaroor!"
- Instead of "Could you please provide your name?"
  → "Aapka naam?"
"""
    return prompt

# ─── HELPER: Save appointment ─────────────────────────────────────────────────
def save_appointment(data: dict):
    try:
        supabase.table("appointments").insert(data).execute()
        print(f"✅ Appointment saved: {data.get('customer_name')} - {data.get('appointment_date')}")
        return True
    except Exception as e:
        print(f"❌ Appointment save error: {e}")
        return False

# ─── HELPER: WhatsApp alert ───────────────────────────────────────────────────
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
# ENDPOINT 1 — CUSTOM LLM
# Set in Retell: Agent → LLM → Custom LLM URL
# URL: .../voice/llm
# ════════════════════════════════════════════════════════════════════════════════
@router.post("/llm")
async def retell_llm(request: Request):
    try:
        body = await request.json()

        call_info = body.get("call", {})
        business_number = call_info.get("to_number", "")
        conversation = body.get("transcript", [])

        agent = get_voice_agent(business_number)
        system_prompt = build_system_prompt(agent)

        # Build message history
        messages = [SystemMessage(content=system_prompt)]
        for msg in conversation:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content.strip():
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "agent":
                messages.append(AIMessage(content=content))

        response = llm.invoke(messages)
        reply = response.content.strip()
        print(f"🤖 AI Reply: {reply}")

        return {
            "response_id": body.get("response_id", 0),
            "content": reply,
            "content_complete": True,
            "end_call": False
        }

    except Exception as e:
        print(f"❌ LLM error: {e}")
        return {
            "response_id": 0,
            "content": "Ji, thodi problem aa rahi hai. Please thodi der mein call karein.",
            "content_complete": True,
            "end_call": False
        }


# ════════════════════════════════════════════════════════════════════════════════
# ENDPOINT 2 — EVENT WEBHOOK
# Set in Retell: Agent → General → Event Webhook URL
# URL: .../voice/webhook
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
                # Check if already exists first
                existing = supabase.table("call_logs").select("call_id").eq("call_id", call_id).execute()
                if not existing.data:
                    supabase.table("call_logs").insert({
                        "call_id": call_id,
                        "business_number": business_number,
                        "customer_number": customer_number,
                        "status": "in-progress",
                        "started_at": datetime.utcnow().isoformat()
                    }).execute()
                    print(f"✅ Call started: {call_id}")
            except Exception as e:
                print(f"❌ Call start error: {e}")

        # ── Call Ended ────────────────────────────────────────────────────────
        elif event == "call_ended":
            duration = call.get("duration_ms", 0)
            duration_seconds = int(duration / 1000) if duration else 0
            transcript = call.get("transcript", "")
            summary = call.get("call_analysis", {}).get("call_summary", "")
            sentiment = call.get("call_analysis", {}).get("user_sentiment", "")
            ended_reason = call.get("disconnection_reason", "")

            try:
                # Use UPDATE instead of upsert to avoid duplicate key error
                existing = supabase.table("call_logs").select("call_id").eq("call_id", call_id).execute()
                if existing.data:
                    supabase.table("call_logs").update({
                        "status": "completed",
                        "duration_seconds": duration_seconds,
                        "summary": summary,
                        "transcript": transcript,
                        "ended_reason": ended_reason,
                        "sentiment": sentiment,
                        "ended_at": datetime.utcnow().isoformat()
                    }).eq("call_id", call_id).execute()
                else:
                    supabase.table("call_logs").insert({
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
                print(f"❌ Call end error: {e}")

        # ── Call Analyzed ─────────────────────────────────────────────────────
        elif event == "call_analyzed":
            try:
                analysis = call.get("call_analysis", {})
                supabase.table("call_logs").update({
                    "summary": analysis.get("call_summary", ""),
                    "sentiment": analysis.get("user_sentiment", ""),
                    "call_intent": analysis.get("call_intent", "")
                }).eq("call_id", call_id).execute()
                print(f"✅ Call analyzed: {call_id}")
            except Exception as e:
                print(f"❌ Call analyze error: {e}")

        return {"status": "ok"}

    except Exception as e:
        print(f"❌ Event webhook error: {e}")
        return {"status": "error", "message": str(e)}


# ── Book appointment endpoint ─────────────────────────────────────────────────
@router.post("/book-appointment")
async def book_appointment_endpoint(request: Request):
    try:
        body = await request.json()
        print(f"📅 Booking appointment: {body.get('customer_name')} | {body.get('appointment_date')} {body.get('appointment_time')}")

        # Retell sends args inside body directly
        customer_number = body.get("customer_number", "")
        business_number = body.get("business_number", "")

        # Try to get business_number from call info if not in body
        call_info = body.get("call", {})
        if not business_number and call_info:
            business_number = call_info.get("to_number", "")
        if not customer_number and call_info:
            customer_number = call_info.get("from_number", "")

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

        # Alert business owner
        if agent and agent.get("client_whatsapp"):
            msg = (
                f"📅 *New Appointment — Voice Agent!*\n"
                f"👤 Patient: {body.get('customer_name', 'Unknown')}\n"
                f"📞 Phone: {customer_number}\n"
                f"📅 Date: {body.get('appointment_date', '—')}\n"
                f"⏰ Time: {body.get('appointment_time', '—')}\n"
                f"📝 Notes: {body.get('notes', '—')}"
            )
            await alert_client_whatsapp(agent["client_whatsapp"], msg)

        return {
            "result": "Appointment booked! Patient will be confirmed shortly." if success else "Booking failed, please try again."
        }

    except Exception as e:
        print(f"❌ Book appointment error: {e}")
        return {"result": "Error booking appointment."}


# ── Flag scam endpoint ────────────────────────────────────────────────────────
@router.post("/flag-scam")
async def flag_scam_endpoint(request: Request):
    try:
        body = await request.json()
        print(f"⚠️ Scam flagged: {body.get('reason')}")

        customer_number = body.get("customer_number", "")
        business_number = body.get("business_number", "")
        reason = body.get("reason", "Suspicious behavior")
        call_id = body.get("call_id", "")

        call_info = body.get("call", {})
        if not business_number and call_info:
            business_number = call_info.get("to_number", "")
        if not customer_number and call_info:
            customer_number = call_info.get("from_number", "")

        agent = get_voice_agent(business_number)

        if call_id:
            try:
                supabase.table("call_logs").update({
                    "is_scam": True,
                    "scam_reason": reason
                }).eq("call_id", call_id).execute()
            except: pass

        if agent and agent.get("client_whatsapp"):
            msg = (
                f"⚠️ *Scam Call Detected!*\n"
                f"📞 From: {customer_number}\n"
                f"🚨 Reason: {reason}"
            )
            await alert_client_whatsapp(agent["client_whatsapp"], msg)

        return {"result": "Scam call flagged and reported."}

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
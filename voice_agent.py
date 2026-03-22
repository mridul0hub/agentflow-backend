from fastapi import APIRouter, Request
from supabase import create_client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
import os
import httpx
from datetime import datetime

router = APIRouter()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0.4,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# ─── Get voice agent config ───────────────────────────────────────────────────
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

# ─── Build human-like system prompt ──────────────────────────────────────────
def build_system_prompt(config: dict) -> str:
    if not config:
        return """
You are Priya, a warm professional receptionist at a clinic.
Speak naturally like a real human — short replies, 1-2 sentences max.
Never repeat your greeting. Be warm and friendly.
"""
    prompt = f"""
You are Priya, a warm and professional receptionist for {config.get('business_name', 'this business')}.
You are on a PHONE CALL — speak exactly like a real human receptionist.

PERSONALITY:
- Warm, friendly, professional — like a real receptionist
- Natural conversational flow — not robotic
- Patient and understanding
- Use "ji", "bilkul", "zaroor", "achha" naturally in Hindi

STRICT RULES:
- Keep EVERY reply to 1-2 short sentences MAXIMUM
- NEVER repeat greeting after the first message
- Do NOT repeat business name in every reply
- If caller speaks Hindi — reply in Hindi
- If caller speaks English — reply in English
- Match caller's language style (Hinglish is fine)

BUSINESS INFORMATION:
Business: {config.get('business_name', 'N/A')}
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
APPOINTMENT BOOKING:
1. Ask name — confirm it: "Rahul ji, sahi hai?"
2. Ask date
3. Ask time
4. Ask purpose/reason for visit (optional — "Koi specific problem hai?")
5. Confirm all details together
6. Call book_appointment function

NAME HANDLING:
- If name unclear — "Sorry ji, naam dobara bata sakte hain?"
- Always confirm name before booking

SCAM DETECTION:
- Suspicious/abusive caller — call flag_scam_call function

NATURAL RESPONSES:
- "Haan ji, batayein?" (instead of repeating greeting)
- "Bilkul, zaroor!" (instead of "I understand")
- "Aapka naam?" (instead of "Could you please provide your name?")
"""
    return prompt

# ─── Save appointment ─────────────────────────────────────────────────────────
def save_appointment(data: dict):
    try:
        supabase.table("appointments").insert(data).execute()
        print(f"✅ Appointment saved: {data.get('customer_name')} - {data.get('appointment_date')}")
        return True
    except Exception as e:
        print(f"❌ Appointment save error: {e}")
        return False

# ─── WhatsApp alert ───────────────────────────────────────────────────────────
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
# Retell Agent → LLM → Custom LLM URL → .../voice/llm
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
        print(f"🤖 AI: {reply}")

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
# Retell Agent → General → Event Webhook URL → .../voice/webhook
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

        print(f"📡 Event: {event} | {call_id}")

        if event == "call_started":
            try:
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

        elif event == "call_ended":
            duration = call.get("duration_ms", 0)
            duration_seconds = int(duration / 1000) if duration else 0
            transcript = call.get("transcript", "")
            summary = call.get("call_analysis", {}).get("call_summary", "")
            sentiment = call.get("call_analysis", {}).get("user_sentiment", "")
            ended_reason = call.get("disconnection_reason", "")
            try:
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
        print(f"❌ Webhook error: {e}")
        return {"status": "error"}


# ── Book appointment ──────────────────────────────────────────────────────────
@router.post("/book-appointment")
async def book_appointment_endpoint(request: Request):
    try:
        body = await request.json()
        print(f"📅 Booking: {body}")

        call_info = body.get("call", {})
        customer_number = body.get("customer_number") or call_info.get("from_number", "")
        business_number = body.get("business_number") or call_info.get("to_number", "")
        agent = get_voice_agent(business_number)

        # Build extra_info from any additional fields
        extra_info = {}
        known_fields = {"customer_name", "customer_number", "business_number",
                       "appointment_date", "appointment_time", "notes",
                       "purpose", "call", "execution_message"}
        for key, val in body.items():
            if key not in known_fields and val:
                extra_info[key] = val

        appointment_data = {
            "user_id": agent.get("user_id") if agent else None,
            "agent_type": "voice",
            "business_number": business_number,
            "customer_number": customer_number,
            "customer_name": body.get("customer_name", "Unknown"),
            "appointment_date": body.get("appointment_date", ""),
            "appointment_time": body.get("appointment_time", ""),
            "purpose": body.get("purpose", body.get("notes", "")),
            "extra_info": extra_info,
            "notes": body.get("notes", ""),
            "status": "pending",
        }
        success = save_appointment(appointment_data)

        if agent and agent.get("client_whatsapp"):
            extra_str = ""
            if extra_info:
                extra_str = "\n" + "\n".join([f"• {k}: {v}" for k, v in extra_info.items()])
            msg = (
                f"📅 *New Appointment — Voice Agent!*\n"
                f"👤 Name: {body.get('customer_name', 'Unknown')}\n"
                f"📞 Phone: {customer_number}\n"
                f"📅 Date: {body.get('appointment_date', '—')}\n"
                f"⏰ Time: {body.get('appointment_time', '—')}\n"
                f"🎯 Purpose: {body.get('purpose', body.get('notes', '—'))}"
                f"{extra_str}"
            )
            await alert_client_whatsapp(agent["client_whatsapp"], msg)

        return {"result": "Appointment booked successfully!" if success else "Booking failed."}

    except Exception as e:
        print(f"❌ Book appointment error: {e}")
        return {"result": "Error booking appointment."}


# ── Flag scam ─────────────────────────────────────────────────────────────────
@router.post("/flag-scam")
async def flag_scam_endpoint(request: Request):
    try:
        body = await request.json()
        call_info = body.get("call", {})
        customer_number = body.get("customer_number") or call_info.get("from_number", "")
        business_number = body.get("business_number") or call_info.get("to_number", "")
        reason = body.get("reason", "Suspicious behavior")
        call_id = body.get("call_id", "")
        agent = get_voice_agent(business_number)

        if call_id:
            try:
                supabase.table("call_logs").update({
                    "is_scam": True,
                    "scam_reason": reason
                }).eq("call_id", call_id).execute()
            except: pass

        if agent and agent.get("client_whatsapp"):
            await alert_client_whatsapp(agent["client_whatsapp"],
                f"⚠️ *Scam Call!*\n📞 From: {customer_number}\n🚨 Reason: {reason}")

        return {"result": "Scam flagged."}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}


# ── Get call logs ─────────────────────────────────────────────────────────────
@router.get("/calls/{user_id}")
async def get_call_logs(user_id: str):
    try:
        result = supabase.table("call_logs").select("*").eq("user_id", user_id).order("started_at", desc=True).limit(50).execute()
        return {"calls": result.data}
    except Exception as e:
        return {"error": str(e)}
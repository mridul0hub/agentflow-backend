from fastapi import APIRouter, Request
from supabase import create_client
import os
import httpx
from datetime import datetime

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ─── HELPER: Get voice agent config from Supabase ───────────────────────────
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


# ─── HELPER: Save appointment to Supabase ───────────────────────────────────
def save_appointment(data: dict):
    try:
        supabase.table("appointments").insert(data).execute()
        return True
    except Exception as e:
        print(f"Appointment save error: {e}")
        return False


# ─── HELPER: Alert client on WhatsApp ───────────────────────────────────────
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
    except Exception as e:
        print(f"WhatsApp alert error: {e}")


# ─── HELPER: Generate AI response via Gemini ────────────────────────────────
async def get_gemini_response(messages: list, system_prompt: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": system_prompt}]},
                    *[{"role": m["role"], "parts": [{"text": m["content"]}]} for m in messages]
                ],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 150,
                }
            }
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}",
                json=payload
            )
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return "Maafi chahta hoon, abhi kuch technical issue hai. Thodi der baad try karein."


# ─── VAPI WEBHOOK ────────────────────────────────────────────────────────────
@router.post("/webhook")
async def vapi_webhook(request: Request):
    """
    Main Vapi webhook — handles all call events:
    - call-started
    - assistant-request (get system prompt dynamically)
    - function-call (book_appointment, flag_scam)
    - call-ended (save summary)
    """
    try:
        body = await request.json()
        message = body.get("message", {})
        msg_type = message.get("type", "")
        call = message.get("call", {})
        call_id = call.get("id", "")
        customer_number = call.get("customer", {}).get("number", "")
        business_number = call.get("phoneNumber", {}).get("number", "")

        print(f"Vapi event: {msg_type} | call: {call_id} | from: {customer_number}")

        # ── 1. Assistant Request — send dynamic system prompt ──
        if msg_type == "assistant-request":
            agent = get_voice_agent(business_number)
            if not agent:
                return {
                    "assistant": {
                        "assistantId": VAPI_ASSISTANT_ID,
                        "assistantOverrides": {
                            "firstMessage": "Hello! Main AI assistant hoon. Abhi yeh service available nahi hai.",
                        }
                    }
                }

            system_prompt = f"""
You are a professional AI voice assistant for {agent['business_name']}.
Speak in simple Hinglish (Hindi-English mix). Keep responses under 2-3 sentences.

Business Information:
- Business: {agent['business_name']}
- Timings: {agent.get('timings', 'Not specified')}
- Services: {agent.get('services', 'Not specified')}
- Fees: {agent.get('fees', 'Not specified')}
- Location: {agent.get('location', 'Not specified')}
- Extra Info: {agent.get('extra_info', '')}

Your tasks:
1. Greet customer warmly
2. Answer questions about the business
3. Book appointments — ask for: name, preferred date, preferred time
4. If customer is abusive or spam after 2 warnings — use flag_scam_call function

Rules:
- Never make up information
- Keep responses SHORT — this is a phone call
- Be polite and professional always
- If you don't know something say: "Main is baare mein confirm karke batata hoon"
"""
            return {
                "assistant": {
                    "assistantId": VAPI_ASSISTANT_ID,
                    "assistantOverrides": {
                        "model": {
                            "provider": "google",
                            "model": "gemini-2.0-flash",
                            "systemPrompt": system_prompt,
                            "temperature": 0.3,
                            "maxTokens": 150,
                        },
                        "firstMessage": f"Hello! {agent['business_name']} mein aapka swagat hai. Main aapki kaise help kar sakta hoon?",
                    }
                }
            }

        # ── 2. Function Call — book appointment or flag scam ──
        elif msg_type == "function-call":
            fn = message.get("functionCall", {})
            fn_name = fn.get("name", "")
            fn_params = fn.get("parameters", {})

            # Book Appointment
            if fn_name == "book_appointment":
                agent = get_voice_agent(business_number)
                appointment_data = {
                    "user_id": agent.get("user_id") if agent else None,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "customer_name": fn_params.get("customer_name", "Unknown"),
                    "appointment_date": fn_params.get("appointment_date", ""),
                    "appointment_time": fn_params.get("appointment_time", ""),
                    "notes": fn_params.get("notes", ""),
                    "status": "pending",
                    "created_at": datetime.utcnow().isoformat()
                }
                success = save_appointment(appointment_data)

                # Alert client on WhatsApp
                if agent and agent.get("client_whatsapp"):
                    msg = (
                        f"📅 *New Appointment Booked!*\n"
                        f"Customer: {appointment_data['customer_name']}\n"
                        f"Phone: {customer_number}\n"
                        f"Date: {appointment_data['appointment_date']}\n"
                        f"Time: {appointment_data['appointment_time']}\n"
                        f"Via: Voice Agent"
                    )
                    await alert_client_whatsapp(agent["client_whatsapp"], msg)

                return {
                    "result": "Appointment booked successfully" if success else "Booking failed, please try again"
                }

            # Flag Scam
            elif fn_name == "flag_scam_call":
                agent = get_voice_agent(business_number)
                reason = fn_params.get("reason", "Suspicious behavior detected")

                # Save scam flag in Supabase
                try:
                    supabase.table("call_logs").update({
                        "is_scam": True,
                        "scam_reason": reason
                    }).eq("call_id", call_id).execute()
                except:
                    pass

                # Alert client
                if agent and agent.get("client_whatsapp"):
                    msg = (
                        f"⚠️ *Suspicious Call Detected!*\n"
                        f"From: {customer_number}\n"
                        f"Reason: {reason}\n"
                        f"Call has been ended automatically."
                    )
                    await alert_client_whatsapp(agent["client_whatsapp"], msg)

                return {"result": "Scam flagged, call will be ended"}

        # ── 3. Call Started — log it ──
        elif msg_type == "call-started":
            try:
                supabase.table("call_logs").insert({
                    "call_id": call_id,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "status": "in-progress",
                    "started_at": datetime.utcnow().isoformat()
                }).execute()
            except Exception as e:
                print(f"Call log error: {e}")

        # ── 4. Call Ended — save summary ──
        elif msg_type == "end-of-call-report":
            summary = message.get("summary", "")
            transcript = message.get("transcript", "")
            duration = message.get("durationSeconds", 0)
            ended_reason = message.get("endedReason", "")
            analysis = message.get("analysis", {})

            try:
                supabase.table("call_logs").upsert({
                    "call_id": call_id,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "status": "completed",
                    "duration_seconds": duration,
                    "summary": summary,
                    "transcript": transcript,
                    "ended_reason": ended_reason,
                    "call_intent": analysis.get("structuredData", {}).get("call_intent", ""),
                    "sentiment": analysis.get("structuredData", {}).get("sentiment", ""),
                    "ended_at": datetime.utcnow().isoformat()
                }).execute()
            except Exception as e:
                print(f"Call end log error: {e}")

        return {"status": "ok"}

    except Exception as e:
        print(f"Vapi webhook error: {e}")
        return {"status": "error", "message": str(e)}


# ─── CREATE VAPI PHONE NUMBER (called when client activates voice agent) ─────
@router.post("/create-agent")
async def create_voice_agent(request: Request):
    """
    Called by admin when activating a client's voice agent.
    Links Plivo number to Vapi assistant.
    """
    try:
        body = await request.json()
        user_id = body.get("user_id")
        plivo_number = body.get("plivo_number")

        if not user_id or not plivo_number:
            return {"error": "user_id and plivo_number required"}

        # Register number in Vapi
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.vapi.ai/phone-number",
                headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
                json={
                    "provider": "byo-phone-number",
                    "number": plivo_number,
                    "assistantId": VAPI_ASSISTANT_ID,
                    "serverUrl": f"{os.getenv('BACKEND_URL', 'https://agentflow-backend-production-34e2.up.railway.app')}/voice/webhook"
                }
            )
            vapi_data = response.json()
            vapi_phone_id = vapi_data.get("id")

        # Save to Supabase
        supabase.table("voice_agents").update({
            "vapi_phone_id": vapi_phone_id,
            "is_active": True
        }).eq("user_id", user_id).execute()

        return {"status": "ok", "vapi_phone_id": vapi_phone_id}

    except Exception as e:
        print(f"Create agent error: {e}")
        return {"error": str(e)}


# ─── GET CALL LOGS ────────────────────────────────────────────────────────────
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
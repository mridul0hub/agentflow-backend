from fastapi import APIRouter, Request
from supabase import create_client
import os
import httpx
from datetime import datetime

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
RETELL_API_KEY = os.getenv("RETELL_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ─── HELPER: Get voice agent config from Supabase ────────────────────────────
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


# ─── HELPER: Save appointment to Supabase ────────────────────────────────────
def save_appointment(data: dict):
    try:
        supabase.table("appointments").insert(data).execute()
        return True
    except Exception as e:
        print(f"Appointment save error: {e}")
        return False


# ─── HELPER: Alert client on WhatsApp ────────────────────────────────────────
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


# ─── RETELL WEBHOOK ───────────────────────────────────────────────────────────
@router.post("/webhook")
async def retell_webhook(request: Request):
    try:
        body = await request.json()

        event = body.get("event", "")
        call = body.get("call", {})
        call_id = call.get("call_id", "")
        customer_number = call.get("from_number", "")
        business_number = call.get("to_number", "")

        print(f"Retell event: {event} | call: {call_id} | from: {customer_number}")

        # ── 1. Call Started ──────────────────────────────────────────────────
        if event == "call_started":
            try:
                supabase.table("call_logs").insert({
                    "call_id": call_id,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "status": "in-progress",
                    "started_at": datetime.utcnow().isoformat()
                }).execute()
            except Exception as e:
                print(f"Call start log error: {e}")
            return {"status": "ok"}

        # ── 2. Function Call ─────────────────────────────────────────────────
        elif event == "function_call":
            fn_name = body.get("name", "")
            fn_args = body.get("args", {})

            print(f"Function called: {fn_name} | args: {fn_args}")

            # ── book_appointment ──
            if fn_name == "book_appointment":
                agent = get_voice_agent(business_number)
                appointment_data = {
                    "user_id": agent.get("user_id") if agent else None,
                    "business_number": business_number,
                    "customer_number": customer_number,
                    "customer_name": fn_args.get("customer_name", "Unknown"),
                    "student_name": fn_args.get("student_name", ""),
                    "student_class": fn_args.get("student_class", ""),
                    "subject": fn_args.get("subject", ""),
                    "appointment_date": fn_args.get("appointment_date", ""),
                    "appointment_time": fn_args.get("appointment_time", ""),
                    "notes": fn_args.get("notes", ""),
                    "status": "pending",
                    "created_at": datetime.utcnow().isoformat()
                }
                success = save_appointment(appointment_data)

                if agent and agent.get("client_whatsapp"):
                    msg = (
                        f"📅 *New Appointment Booked!*\n"
                        f"Parent: {appointment_data['customer_name']}\n"
                        f"Student: {appointment_data['student_name']} ({appointment_data['student_class']})\n"
                        f"Subject: {appointment_data['subject']}\n"
                        f"Phone: {customer_number}\n"
                        f"Date: {appointment_data['appointment_date']}\n"
                        f"Time: {appointment_data['appointment_time']}\n"
                        f"Via: Voice Agent 📞"
                    )
                    await alert_client_whatsapp(agent["client_whatsapp"], msg)

                return {
                    "result": "Appointment booked successfully! Demo class confirmed." if success else "Booking failed, please try again."
                }

            # ── flag_scam_call ──
            elif fn_name == "flag_scam_call":
                agent = get_voice_agent(business_number)
                reason = fn_args.get("reason", "Suspicious behavior detected")

                try:
                    supabase.table("call_logs").update({
                        "is_scam": True,
                        "scam_reason": reason
                    }).eq("call_id", call_id).execute()
                except Exception as e:
                    print(f"Scam flag error: {e}")

                if agent and agent.get("client_whatsapp"):
                    msg = (
                        f"⚠️ *Suspicious Call Detected!*\n"
                        f"From: {customer_number}\n"
                        f"Reason: {reason}\n"
                        f"Call ended automatically."
                    )
                    await alert_client_whatsapp(agent["client_whatsapp"], msg)

                return {"result": "Scam flagged successfully."}

            return {"result": "Function not found"}

        # ── 3. Call Ended ────────────────────────────────────────────────────
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
                print(f"Call ended: {call_id} | {duration_seconds}s")
            except Exception as e:
                print(f"Call end log error: {e}")

            return {"status": "ok"}

        return {"status": "ok"}

    except Exception as e:
        print(f"Retell webhook error: {e}")
        return {"status": "error", "message": str(e)}


# ─── CREATE RETELL AGENT ──────────────────────────────────────────────────────
@router.post("/create-agent")
async def create_voice_agent(request: Request):
    try:
        body = await request.json()
        user_id = body.get("user_id")
        phone_number = body.get("phone_number")
        agent_id = body.get("agent_id")

        if not user_id or not phone_number:
            return {"error": "user_id and phone_number required"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.retellai.com/create-phone-number",
                headers={
                    "Authorization": f"Bearer {RETELL_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "phone_number": phone_number,
                    "inbound_agent_id": agent_id,
                }
            )
            retell_data = response.json()

        supabase.table("voice_agents").update({
            "retell_agent_id": agent_id,
            "is_active": True
        }).eq("user_id", user_id).execute()

        return {"status": "ok", "retell_data": retell_data}

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


# ─── GET APPOINTMENTS ─────────────────────────────────────────────────────────
@router.get("/appointments/{user_id}")
async def get_appointments(user_id: str):
    try:
        result = supabase.table("appointments") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(50) \
            .execute()
        return {"appointments": result.data}
    except Exception as e:
        return {"error": str(e)}
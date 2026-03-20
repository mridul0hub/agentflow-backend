import os
import resend
from fastapi import APIRouter, Request
from supabase import create_client
from datetime import datetime

router = APIRouter()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

resend.api_key = os.getenv("RESEND_API_KEY")

LOW_CREDITS_THRESHOLD = 5

# ─── GET or CREATE credits for user ──────────────────────────────────────────
def get_credits(user_id: str) -> dict:
    try:
        result = supabase.table("credits").select("*").eq("user_id", user_id).single().execute()
        return result.data
    except:
        # Create credits row with 20 free credits
        result = supabase.table("credits").insert({
            "user_id": user_id,
            "balance": 20,
            "total_used": 0
        }).execute()
        return result.data[0] if result.data else {"balance": 20, "total_used": 0}

# ─── DEDUCT credit + log transaction ─────────────────────────────────────────
def deduct_credit(user_id: str, agent_type: str, description: str) -> bool:
    try:
        credits = get_credits(user_id)
        balance = credits.get("balance", 0)

        if balance <= 0:
            print(f"❌ No credits for user {user_id}")
            return False

        # Deduct 1 credit
        new_balance = balance - 1
        supabase.table("credits").update({
            "balance": new_balance,
            "total_used": credits.get("total_used", 0) + 1,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("user_id", user_id).execute()

        # Log transaction
        supabase.table("credit_transactions").insert({
            "user_id": user_id,
            "amount": -1,
            "type": "usage",
            "description": description,
            "agent_type": agent_type
        }).execute()

        print(f"✅ Credit deducted for {user_id}. Balance: {new_balance}")

        # Send low credits alert
        if new_balance == LOW_CREDITS_THRESHOLD:
            send_low_credits_alert(user_id, new_balance)

        return True

    except Exception as e:
        print(f"❌ Deduct credit error: {e}")
        return False

# ─── ADD credits (manual or payment) ─────────────────────────────────────────
def add_credits(user_id: str, amount: int, description: str = "Credits added") -> bool:
    try:
        credits = get_credits(user_id)
        new_balance = credits.get("balance", 0) + amount

        supabase.table("credits").update({
            "balance": new_balance,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("user_id", user_id).execute()

        supabase.table("credit_transactions").insert({
            "user_id": user_id,
            "amount": amount,
            "type": "topup",
            "description": description,
            "agent_type": "manual"
        }).execute()

        print(f"✅ Added {amount} credits for {user_id}. New balance: {new_balance}")
        return True

    except Exception as e:
        print(f"❌ Add credit error: {e}")
        return False

# ─── CHECK if user has credits ────────────────────────────────────────────────
def has_credits(user_id: str) -> bool:
    try:
        credits = get_credits(user_id)
        return credits.get("balance", 0) > 0
    except:
        return False

# ─── GET user_id from agent config ───────────────────────────────────────────
def get_user_id_from_whatsapp(whatsapp_number: str) -> str | None:
    try:
        result = supabase.table("whatsapp_agents").select("user_id").eq("whatsapp_number", whatsapp_number).single().execute()
        return result.data.get("user_id") if result.data else None
    except:
        return None

def get_user_id_from_email(business_email: str) -> str | None:
    try:
        result = supabase.table("email_agents").select("user_id").eq("business_email", business_email).single().execute()
        return result.data.get("user_id") if result.data else None
    except:
        return None

# ─── LOW CREDITS EMAIL ALERT ──────────────────────────────────────────────────
def send_low_credits_alert(user_id: str, balance: int):
    try:
        user = supabase.auth.admin.get_user_by_id(user_id)
        email = user.user.email if user.user else None
        if not email:
            return

        resend.Emails.send({
            "from": "AEZIO AI Agents <onboarding@resend.dev>",
            "to": [email],
            "subject": "⚠️ Low Credits Alert — AEZIO AI Agents",
            "html": f"""
            <div style="font-family: Montserrat, sans-serif; max-width: 560px; margin: 0 auto; background: #0d0d14; color: #e8e8f0; border-radius: 16px; overflow: hidden;">
              <div style="background: linear-gradient(135deg, #11111c, #16162a); padding: 32px; border-bottom: 1px solid rgba(124,58,237,0.2);">
                <h1 style="font-size: 24px; font-weight: 800; color: #e8e8f0; margin: 0 0 8px;">⚠️ Low Credits Warning</h1>
                <p style="color: #9898c0; margin: 0; font-size: 14px;">Your AEZIO AI agent credits are running low</p>
              </div>
              <div style="padding: 32px;">
                <p style="color: #c8c8e0; font-size: 15px; line-height: 1.7; margin: 0 0 24px;">
                  You only have <strong style="color: #a78bfa;">{balance} credits</strong> remaining. 
                  Your AI agents will stop responding when credits reach zero.
                </p>
                <a href="https://aezioaiagents.vercel.app/pricing" 
                   style="display: inline-block; padding: 14px 32px; background: #7c3aed; color: white; border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 14px;">
                  Buy More Credits →
                </a>
                <p style="color: #606080; font-size: 12px; margin-top: 24px; line-height: 1.6;">
                  AEZIO AI Agents · Building the future of business automation
                </p>
              </div>
            </div>
            """
        })
        print(f"📧 Low credits alert sent to {email}")
    except Exception as e:
        print(f"❌ Low credits email error: {e}")

# ─── API ROUTES ───────────────────────────────────────────────────────────────

@router.get("/balance/{user_id}")
async def get_balance(user_id: str):
    try:
        credits = get_credits(user_id)
        return {
            "balance": credits.get("balance", 0),
            "total_used": credits.get("total_used", 0)
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/transactions/{user_id}")
async def get_transactions(user_id: str):
    try:
        result = supabase.table("credit_transactions") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(50) \
            .execute()
        return {"transactions": result.data}
    except Exception as e:
        return {"error": str(e)}

@router.post("/add")
async def add_credits_route(request: Request):
    try:
        body = await request.json()
        user_id = body.get("user_id")
        amount = body.get("amount", 0)
        description = body.get("description", "Credits added by admin")
        if not user_id or amount <= 0:
            return {"error": "user_id and amount required"}
        success = add_credits(user_id, amount, description)
        return {"status": "ok" if success else "error"}
    except Exception as e:
        return {"error": str(e)}
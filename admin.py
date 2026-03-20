import os
from fastapi import APIRouter, Request, HTTPException
from supabase import create_client
from auth import send_agent_activated_email

router = APIRouter()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

ADMIN_EMAILS = ["vasusoni1068@gmail.com"]

def verify_admin(email: str):
    if email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access only")

# ── GET all users ─────────────────────────────────────────────────────────────
@router.get("/users")
async def get_all_users(admin_email: str):
    verify_admin(admin_email)
    try:
        result = supabase.table("admin_users_view").select("*").execute()
        return {"users": result.data}
    except Exception as e:
        return {"error": str(e)}

# ── GET single user detail ────────────────────────────────────────────────────
@router.get("/user/{user_id}")
async def get_user_detail(user_id: str, admin_email: str):
    verify_admin(admin_email)
    try:
        credits = supabase.table("credits").select("*").eq("user_id", user_id).single().execute()
        wa = supabase.table("whatsapp_agents").select("*").eq("user_id", user_id).execute()
        em = supabase.table("email_agents").select("*").eq("user_id", user_id).execute()
        vo = supabase.table("voice_agents").select("*").eq("user_id", user_id).execute()
        tx = supabase.table("credit_transactions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
        return {
            "credits": credits.data,
            "whatsapp_agent": wa.data[0] if wa.data else None,
            "email_agent": em.data[0] if em.data else None,
            "voice_agent": vo.data[0] if vo.data else None,
            "transactions": tx.data
        }
    except Exception as e:
        return {"error": str(e)}

# ── ACTIVATE / DEACTIVATE agent ───────────────────────────────────────────────
@router.post("/toggle-agent")
async def toggle_agent(request: Request):
    try:
        body        = await request.json()
        admin_email = body.get("admin_email")
        user_id     = body.get("user_id")
        agent_type  = body.get("agent_type")
        is_active   = body.get("is_active")

        verify_admin(admin_email)

        table_map = {
            "whatsapp": "whatsapp_agents",
            "email": "email_agents",
            "voice": "voice_agents"
        }
        table = table_map.get(agent_type)
        if not table:
            return {"error": "Invalid agent_type"}

        supabase.table(table).update({"is_active": is_active}).eq("user_id", user_id).execute()
        print(f"✅ {agent_type} agent {'activated' if is_active else 'deactivated'} for {user_id}")

        # Send activation email to user
        if is_active:
            try:
                user = supabase.auth.admin.get_user_by_id(user_id)
                if user.user:
                    email = user.user.email
                    name = user.user.user_metadata.get("full_name", "") if user.user.user_metadata else ""
                    agent_data = supabase.table(table).select("business_name").eq("user_id", user_id).single().execute()
                    business_name = agent_data.data.get("business_name", "Your Business") if agent_data.data else "Your Business"
                    send_agent_activated_email(email, name, agent_type, business_name)
            except Exception as email_err:
                print(f"⚠️ Could not send activation email: {email_err}")

        return {"status": "ok", "is_active": is_active}

    except HTTPException as e:
        raise e
    except Exception as e:
        return {"error": str(e)}

# ── ADD / REMOVE credits ──────────────────────────────────────────────────────
@router.post("/credits")
async def manage_credits(request: Request):
    try:
        body        = await request.json()
        admin_email = body.get("admin_email")
        user_id     = body.get("user_id")
        amount      = body.get("amount", 0)
        note        = body.get("note", "Admin adjustment")

        verify_admin(admin_email)

        result = supabase.table("credits").select("*").eq("user_id", user_id).single().execute()
        if not result.data:
            supabase.table("credits").insert({"user_id": user_id, "balance": max(0, amount), "total_used": 0}).execute()
        else:
            current = result.data.get("balance", 0)
            new_balance = max(0, current + amount)
            supabase.table("credits").update({"balance": new_balance}).eq("user_id", user_id).execute()

        supabase.table("credit_transactions").insert({
            "user_id": user_id,
            "amount": amount,
            "type": "admin",
            "description": note,
            "agent_type": "admin"
        }).execute()

        print(f"✅ Admin adjusted {amount} credits for {user_id}")
        return {"status": "ok"}

    except HTTPException as e:
        raise e
    except Exception as e:
        return {"error": str(e)}

# ── STATS overview ────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_stats(admin_email: str):
    verify_admin(admin_email)
    try:
        users     = supabase.table("admin_users_view").select("*").execute()
        total_tx  = supabase.table("credit_transactions").select("*", count="exact", head=True).eq("type", "usage").execute()
        wa_active = supabase.table("whatsapp_agents").select("*", count="exact", head=True).eq("is_active", True).execute()
        em_active = supabase.table("email_agents").select("*", count="exact", head=True).eq("is_active", True).execute()
        vo_active = supabase.table("voice_agents").select("*", count="exact", head=True).eq("is_active", True).execute()
        return {
            "total_users": len(users.data),
            "total_replies": total_tx.count or 0,
            "whatsapp_agents_active": wa_active.count or 0,
            "email_agents_active": em_active.count or 0,
            "voice_agents_active": vo_active.count or 0,
        }
    except Exception as e:
        return {"error": str(e)}
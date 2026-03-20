import os
import resend
from fastapi import APIRouter, Request
from supabase import create_client

router = APIRouter()

resend.api_key = os.getenv("RESEND_API_KEY")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

WEBHOOK_SECRET = os.getenv("SUPABASE_WEBHOOK_SECRET", "aezio_webhook_secret_2024")

# ─── WELCOME EMAIL ────────────────────────────────────────────────────────────
def send_welcome_email(email: str, name: str):
    try:
        first_name = name.split(" ")[0] if name else email.split("@")[0]
        resend.Emails.send({
            "from": "AEZIO AI Agents <onboarding@resend.dev>",
            "to": [email],
            "subject": "Welcome to AEZIO AI Agents 🚀",
            "html": f"""
            <div style="font-family: Montserrat, Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0d0d14; border-radius: 20px; overflow: hidden; border: 1px solid rgba(124,58,237,0.2);">

              <!-- HEADER -->
              <div style="background: linear-gradient(135deg, #11111c 0%, #16162a 100%); padding: 40px 40px 32px; text-align: center; border-bottom: 1px solid rgba(124,58,237,0.15);">
                <div style="font-size: 13px; font-weight: 700; color: #a78bfa; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 16px;">AEZIO AI AGENTS</div>
                <h1 style="font-size: 28px; font-weight: 800; color: #e8e8f0; margin: 0 0 10px; letter-spacing: -0.5px;">Welcome, {first_name}! 👋</h1>
                <p style="color: #9898c0; font-size: 15px; margin: 0; line-height: 1.6;">Your AI agents are ready to work for your business.</p>
              </div>

              <!-- BODY -->
              <div style="padding: 36px 40px;">
                <p style="color: #c8c8e0; font-size: 15px; line-height: 1.8; margin: 0 0 28px;">
                  You now have <strong style="color: #a78bfa;">20 free credits</strong> to get started. 
                  Each AI reply uses 1 credit — so you have 20 free customer interactions waiting!
                </p>

                <!-- STEPS -->
                <div style="margin-bottom: 28px;">
                  <div style="font-size: 11px; font-weight: 700; color: #606080; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 16px;">Get Started in 3 Steps</div>

                  {_step("1", "Set up your agent", "Fill in your business details — timings, services, pricing.", "#7c3aed")}
                  {_step("2", "We activate it", "Our team activates your agent within 24 hours.", "#8b5cf6")}
                  {_step("3", "AI starts working", "Your agent replies to customers automatically — 24/7.", "#a78bfa")}
                </div>

                <!-- CTA -->
                <div style="text-align: center; margin-bottom: 28px;">
                  <a href="https://aezioaiagents.vercel.app/dashboard"
                     style="display: inline-block; padding: 14px 36px; background: #7c3aed; color: white; border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 15px; letter-spacing: 0.2px;">
                    Go to Dashboard →
                  </a>
                </div>

                <!-- AGENTS -->
                <div style="background: #16162a; border-radius: 14px; padding: 20px; border: 1px solid rgba(124,58,237,0.15); margin-bottom: 24px;">
                  <div style="font-size: 12px; font-weight: 700; color: #606080; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 14px;">Available Agents</div>
                  <div style="display: flex; gap: 12px; flex-wrap: wrap;">
                    {_agent_pill("💬 WhatsApp Agent")}
                    {_agent_pill("📧 Email Agent")}
                    {_agent_pill("📞 Voice Agent")}
                    {_agent_pill("📅 Appointment Agent")}
                  </div>
                </div>

                <p style="color: #606080; font-size: 12px; line-height: 1.7; margin: 0;">
                  Questions? Reply to this email or contact us at 
                  <a href="mailto:vasusoni1068@gmail.com" style="color: #a78bfa;">vasusoni1068@gmail.com</a>
                </p>
              </div>

              <!-- FOOTER -->
              <div style="padding: 20px 40px; border-top: 1px solid rgba(124,58,237,0.1); text-align: center;">
                <p style="color: #606080; font-size: 11px; margin: 0;">© 2025 AEZIO AI Agents · Building the future of business automation</p>
              </div>

            </div>
            """
        })
        print(f"✅ Welcome email sent to {email}")
    except Exception as e:
        print(f"❌ Welcome email error: {e}")

def _step(num, title, desc, color):
    return f"""
    <div style="display: flex; gap: 14px; margin-bottom: 14px; align-items: flex-start;">
      <div style="width: 28px; height: 28px; border-radius: 50%; background: {color}20; border: 1px solid {color}40; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 12px; font-weight: 700; color: {color};">{num}</div>
      <div>
        <div style="font-size: 14px; font-weight: 700; color: #e8e8f0; margin-bottom: 2px;">{title}</div>
        <div style="font-size: 12px; color: #9898c0; line-height: 1.5;">{desc}</div>
      </div>
    </div>
    """

def _agent_pill(label):
    return f'<span style="padding: 5px 12px; border-radius: 50px; background: rgba(124,58,237,0.1); color: #a78bfa; font-size: 12px; font-weight: 600; border: 1px solid rgba(124,58,237,0.2);">{label}</span>'

# ─── AGENT ACTIVATED EMAIL ────────────────────────────────────────────────────
def send_agent_activated_email(email: str, name: str, agent_type: str, business_name: str):
    try:
        first_name = name.split(" ")[0] if name else email.split("@")[0]
        agent_names = {
            "whatsapp": "WhatsApp Agent",
            "email": "Email Agent",
            "voice": "Voice Agent"
        }
        agent_name = agent_names.get(agent_type, "AI Agent")
        agent_icons = {"whatsapp": "💬", "email": "📧", "voice": "📞"}
        icon = agent_icons.get(agent_type, "🤖")

        resend.Emails.send({
            "from": "AEZIO AI Agents <onboarding@resend.dev>",
            "to": [email],
            "subject": f"🎉 Your {agent_name} is now LIVE!",
            "html": f"""
            <div style="font-family: Montserrat, Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #0d0d14; border-radius: 20px; overflow: hidden; border: 1px solid rgba(124,58,237,0.2);">

              <div style="background: linear-gradient(135deg, #11111c 0%, #16162a 100%); padding: 40px; text-align: center; border-bottom: 1px solid rgba(124,58,237,0.15);">
                <div style="font-size: 48px; margin-bottom: 16px;">{icon}</div>
                <h1 style="font-size: 26px; font-weight: 800; color: #e8e8f0; margin: 0 0 10px;">Your {agent_name} is Live!</h1>
                <p style="color: #9898c0; font-size: 14px; margin: 0;">For <strong style="color: #a78bfa;">{business_name}</strong></p>
              </div>

              <div style="padding: 36px 40px;">
                <p style="color: #c8c8e0; font-size: 15px; line-height: 1.8; margin: 0 0 24px;">
                  Great news, {first_name}! Your <strong style="color: #a78bfa;">{agent_name}</strong> for 
                  <strong style="color: #e8e8f0;"> {business_name}</strong> has been activated and is now 
                  replying to your customers automatically.
                </p>

                <div style="background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.2); border-radius: 12px; padding: 16px 20px; margin-bottom: 24px;">
                  <div style="color: #4ade80; font-size: 14px; font-weight: 700;">✅ Agent Status: ACTIVE</div>
                  <div style="color: #9898c0; font-size: 13px; margin-top: 4px;">Your customers are now getting instant AI replies 24/7</div>
                </div>

                <div style="text-align: center; margin-bottom: 24px;">
                  <a href="https://aezioaiagents.vercel.app/dashboard"
                     style="display: inline-block; padding: 14px 36px; background: #7c3aed; color: white; border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 15px;">
                    View Dashboard →
                  </a>
                </div>

                <p style="color: #606080; font-size: 12px; line-height: 1.7; margin: 0;">
                  Need help? Contact us at <a href="mailto:vasusoni1068@gmail.com" style="color: #a78bfa;">vasusoni1068@gmail.com</a>
                </p>
              </div>

              <div style="padding: 20px 40px; border-top: 1px solid rgba(124,58,237,0.1); text-align: center;">
                <p style="color: #606080; font-size: 11px; margin: 0;">© 2025 AEZIO AI Agents · Building the future of business automation</p>
              </div>
            </div>
            """
        })
        print(f"✅ Agent activated email sent to {email}")
    except Exception as e:
        print(f"❌ Agent activated email error: {e}")

# ─── WEBHOOK ENDPOINT ─────────────────────────────────────────────────────────
@router.post("/webhook")
async def auth_webhook(request: Request):
    try:
        body = await request.json()
        print(f"📩 Auth webhook: {body.get('type')}")

        event_type = body.get("type")

        if event_type == "INSERT" and body.get("table") == "users":
            record = body.get("record", {})
            email = record.get("email", "")
            name = record.get("raw_user_meta_data", {}).get("full_name", "")
            if email:
                send_welcome_email(email, name)

        return {"status": "ok"}

    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return {"status": "error", "detail": str(e)}

# ─── MANUAL TRIGGER (for testing) ────────────────────────────────────────────
@router.post("/send-welcome")
async def manual_welcome(request: Request):
    try:
        body = await request.json()
        email = body.get("email")
        name = body.get("name", "")
        if not email:
            return {"error": "email required"}
        send_welcome_email(email, name)
        return {"status": "ok", "message": f"Welcome email sent to {email}"}
    except Exception as e:
        return {"error": str(e)}

@router.post("/send-activated")
async def manual_activated(request: Request):
    try:
        body = await request.json()
        email       = body.get("email")
        name        = body.get("name", "")
        agent_type  = body.get("agent_type", "whatsapp")
        business    = body.get("business_name", "Your Business")
        if not email:
            return {"error": "email required"}
        send_agent_activated_email(email, name, agent_type, business)
        return {"status": "ok", "message": f"Activation email sent to {email}"}
    except Exception as e:
        return {"error": str(e)}
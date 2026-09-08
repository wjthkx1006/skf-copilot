"""
Teams Bot Service for HelpDesk
Handles Microsoft Teams messages and integrates with the HelpDesk backend
"""
import os
import json
import logging
import aiohttp
from datetime import datetime
from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot Configuration
APP_ID = os.environ.get("MICROSOFT_APP_ID", "fa2848d0-d507-492d-8f30-2f6e7c0a1210")
APP_PASSWORD = os.environ.get("MICROSOFT_APP_PASSWORD", "")
APP_TENANT_ID = os.environ.get("MICROSOFT_APP_TENANT_ID", "0e7486f4-86f7-4695-9c58-5a1f261871c9")

# Backend Configuration
GUARDRAIL_URL = os.environ.get("GUARDRAIL_URL", "http://localhost:8003")
DEVOPS_AGENT_URL = os.environ.get("DEVOPS_AGENT_URL", "http://localhost:8001")
DIFY_API_URL = os.environ.get("DIFY_API_URL", "https://api.dify.ai/v1/chat-messages")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "app-aiKkdUntwqNNX7OZIzeTlbQY")

# Bot Framework Adapter Settings for Single Tenant
SETTINGS = BotFrameworkAdapterSettings(
    app_id=APP_ID,
    app_password=APP_PASSWORD,
    channel_auth_tenant=APP_TENANT_ID,  # Required for Single Tenant
)
ADAPTER = BotFrameworkAdapter(SETTINGS)


async def on_error(context: TurnContext, error: Exception):
    """Error handler for the bot"""
    logger.error(f"Bot error: {error}")
    await context.send_activity("Sorry, something went wrong. Please try again.")


ADAPTER.on_turn_error = on_error


async def check_guardrail(text: str) -> dict:
    """Check input through guardrail service"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GUARDRAIL_URL}/api/guardrail/check",
                json={"text": text},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    return await response.json()
    except Exception as e:
        logger.warning(f"Guardrail check failed: {e}")
    return {"safe": True, "blocked": False}


async def check_output_guardrail(text: str) -> dict:
    """Check output through guardrail service"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GUARDRAIL_URL}/api/guardrail/check-output",
                json={"text": text},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    return await response.json()
    except Exception as e:
        logger.warning(f"Output guardrail check failed: {e}")
    return {"safe": True, "blocked": False}


async def call_devops_agent(message: str, caller: str = None) -> dict:
    """Call Azure DevOps agent for ticket operations"""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"X-API-Key": "sk-1c6b6cae56fa4937ab5718e0c5f3fd34"}
            payload = {"message": message}
            if caller:
                payload["caller"] = caller
            
            async with session.post(
                f"{DEVOPS_AGENT_URL}/api/chat",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    return await response.json()
    except Exception as e:
        logger.error(f"DevOps agent call failed: {e}")
    return None


async def call_dify(message: str, user_id: str) -> str:
    """Call Dify API for general conversation (streaming mode for Agent Chat)"""
    if not DIFY_API_URL or not DIFY_API_KEY:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {DIFY_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": {},
                "query": message,
                "user": user_id,
                "response_mode": "streaming"
            }
            
            async with session.post(
                DIFY_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status == 200:
                    # Parse streaming SSE response
                    full_answer = ""
                    async for line in response.content:
                        line_str = line.decode('utf-8').strip()
                        if line_str.startswith('data: '):
                            try:
                                data = json.loads(line_str[6:])
                                event = data.get('event', '')
                                if event == 'agent_message' or event == 'message':
                                    full_answer += data.get('answer', '')
                                elif event == 'message_end':
                                    # Final message, use metadata answer if available
                                    if data.get('metadata', {}).get('answer'):
                                        full_answer = data['metadata']['answer']
                            except json.JSONDecodeError:
                                continue
                    if full_answer:
                        logger.info(f"Dify response received: {len(full_answer)} chars")
                        return full_answer
                else:
                    error_text = await response.text()
                    logger.error(f"Dify API error {response.status}: {error_text[:200]}")
    except Exception as e:
        logger.error(f"Dify call failed: {e}")
    return None


def is_ticket_related(message: str) -> bool:
    """Check if message is ticket-related"""
    keywords = [
        # Create ticket
        "create ticket", "open ticket", "new ticket", "report issue",
        "创建工单", "开单", "报修", "提交问题",
        # Query ticket
        "ticket status", "check ticket", "ticket #", "工单状态", "查询工单",
        # Update ticket
        "close ticket", "update ticket", "关闭工单", "更新工单",
        # List tickets
        "list tickets", "my tickets", "show tickets", "工单列表", "我的工单",
        # Common IT issues that should create tickets
        "not working", "broken", "error", "cannot connect", "failed",
        "无法", "不工作", "坏了", "报错", "连不上"
    ]
    message_lower = message.lower()
    return any(kw in message_lower for kw in keywords)


async def process_message(turn_context: TurnContext):
    """Process incoming message from Teams"""
    user_message = turn_context.activity.text
    user_name = turn_context.activity.from_property.name or "Teams User"
    user_id = turn_context.activity.from_property.id or "unknown"
    
    logger.info(f"Message from {user_name}: {user_message}")
    
    # 1. Check input through guardrail
    guardrail_result = await check_guardrail(user_message)
    if guardrail_result.get("blocked"):
        blocked_message = guardrail_result.get("message", "Your message was blocked by content policy.")
        await turn_context.send_activity(blocked_message)
        logger.warning(f"Input blocked: {user_message[:50]}")
        return
    
    # 2. Determine if this is ticket-related or general conversation
    response_text = None
    
    if is_ticket_related(user_message):
        # Call Azure DevOps Agent
        agent_response = await call_devops_agent(user_message, user_name)
        if agent_response:
            response_text = agent_response.get("ai_response", "Ticket operation completed.")
        else:
            response_text = "Sorry, I couldn't process your ticket request. Please try again."
    else:
        # Try Dify for general conversation
        dify_response = await call_dify(user_message, user_id)
        if dify_response:
            response_text = dify_response
        else:
            # Fallback: treat as potential ticket
            agent_response = await call_devops_agent(user_message, user_name)
            if agent_response:
                response_text = agent_response.get("ai_response", "How can I help you?")
            else:
                response_text = (
                    "👋 Hi! I'm the IT HelpDesk Bot.\n\n"
                    "I can help you with:\n"
                    "• **Report issues** - \"My laptop won't connect to WiFi\"\n"
                    "• **Check ticket status** - \"What's the status of ticket #123?\"\n"
                    "• **List your tickets** - \"Show my open tickets\"\n\n"
                    "How can I assist you today?"
                )
    
    # 3. Check output through guardrail
    output_check = await check_output_guardrail(response_text)
    if output_check.get("blocked"):
        response_text = "I apologize, but I cannot provide that information. Please ask a work-related question."
        logger.warning(f"Output blocked")
    
    # 4. Send response
    await turn_context.send_activity(response_text)
    logger.info(f"Response sent to {user_name}")


async def on_turn(turn_context: TurnContext):
    """Handle incoming activity"""
    if turn_context.activity.type == ActivityTypes.message:
        await process_message(turn_context)
    elif turn_context.activity.type == ActivityTypes.conversation_update:
        # Welcome new members
        if turn_context.activity.members_added:
            for member in turn_context.activity.members_added:
                if member.id != turn_context.activity.recipient.id:
                    welcome_text = (
                        "👋 Welcome to IT HelpDesk!\n\n"
                        "I can help you:\n"
                        "• Report IT issues and create tickets\n"
                        "• Check ticket status\n"
                        "• Answer IT-related questions\n\n"
                        "Just type your question or describe your issue!"
                    )
                    await turn_context.send_activity(welcome_text)


async def messages(req: web.Request) -> web.Response:
    """Handle incoming messages from Bot Framework"""
    if "application/json" in req.headers.get("Content-Type", ""):
        body = await req.json()
    else:
        return web.Response(status=415)
    
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")
    
    try:
        response = await ADAPTER.process_activity(activity, auth_header, on_turn)
        if response:
            return web.json_response(data=response.body, status=response.status)
        return web.Response(status=201)
    except Exception as e:
        logger.error(f"Error processing activity: {e}")
        return web.Response(status=500)


async def health(req: web.Request) -> web.Response:
    """Health check endpoint"""
    return web.json_response({
        "status": "ok",
        "service": "teams-bot",
        "timestamp": datetime.utcnow().isoformat()
    })


def create_app():
    """Create the web application"""
    app = web.Application()
    app.router.add_post("/api/teams/messages", messages)
    app.router.add_get("/api/teams/health", health)
    app.router.add_get("/health", health)
    return app


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║         HelpDesk Teams Bot Service                           ║
╠══════════════════════════════════════════════════════════════╣
║  App ID:      {:<45} ║
║  Server:      http://0.0.0.0:8004                            ║
╚══════════════════════════════════════════════════════════════╝
    """.format(APP_ID[:20] + "..."))
    
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8004)

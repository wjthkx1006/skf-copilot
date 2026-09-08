"""
SKF Distributor Copilot server
RAG (Chroma + DashScope) + tool calling (qwen-plus) + SQLite exact queries
"""
import os
import json
import sqlite3
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import Chroma

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("skf-copilot")

BASE = Path(__file__).parent
DB_PATH = Path(os.environ.get("SKF_DB_PATH", BASE / "skf.db"))
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8001")
QWEN_API_KEY = os.environ["QWEN_API_KEY"]
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")

client = OpenAI(api_key=QWEN_API_KEY,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

emb = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=QWEN_API_KEY)
vectorstore = Chroma(
    persist_directory=str(BASE / "chroma_index"),
    embedding_function=emb,
    collection_name="skf_copilot",
)
logger.info("Chroma collection loaded: %d vectors", vectorstore._collection.count())

app = FastAPI(title="SKF Distributor Copilot", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# In-memory conversation history: {session_id: [messages]}
sessions = {}
MAX_HISTORY = 20


def init_orders_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        sku TEXT, quantity INTEGER, distributor_class TEXT,
        unit_price REAL, subtotal_excl_vat REAL, vat REAL, total_incl_vat REAL,
        status TEXT, created_at TEXT)""")
    for col in ("customer_name", "customer_phone", "customer_address"):
        try:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()


init_orders_table()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def find_sku(conn, sku: str):
    """Fuzzy SKU match: exact first, then LIKE."""
    row = conn.execute("SELECT sku FROM products WHERE sku = ? COLLATE NOCASE", (sku,)).fetchone()
    if row:
        return row["sku"]
    row = conn.execute("SELECT sku FROM products WHERE sku LIKE ? COLLATE NOCASE ORDER BY LENGTH(sku) LIMIT 1",
                       (f"%{sku.strip()}%",)).fetchone()
    return row["sku"] if row else None


# ---------------- Tools ----------------

def tool_search_knowledge(query: str) -> str:
    docs = vectorstore.similarity_search(query, k=5)
    return "\n---\n".join(d.page_content for d in docs) or "No relevant knowledge found."


CATEGORY_IMAGES = {
    "Deep Groove": "/product-images/deep-groove.png",
    "Spherical Roller": "/product-images/spherical-roller.png",
    "Tapered Roller": "/product-images/tapered-roller.png",
    "Lubrication": "/product-images/lubrication.png",
    "Seal": "/product-images/seal.png",
    "Mounted Unit": "/product-images/mounted-unit.png",
    "Tool": "/product-images/tool.png",
    "Monitoring": "/product-images/monitoring.png",
}


def tool_get_product(sku: str) -> str:
    conn = db()
    real = find_sku(conn, sku)
    if not real:
        conn.close()
        return json.dumps({"error": f"SKU '{sku}' not found in catalog"}, ensure_ascii=False)
    p = dict(conn.execute("SELECT * FROM products WHERE sku=?", (real,)).fetchone())
    conn.close()
    img = CATEGORY_IMAGES.get(p.get("category", ""))
    if img:
        p["image_url"] = img
    return json.dumps(p, ensure_ascii=False)


def tool_check_inventory(sku: str) -> str:
    conn = db()
    real = find_sku(conn, sku)
    if not real:
        conn.close()
        return json.dumps({"error": f"SKU '{sku}' not found"}, ensure_ascii=False)
    row = conn.execute("SELECT * FROM inventory WHERE sku=?", (real,)).fetchone()
    conn.close()
    d = dict(row) if row else {"error": "no inventory record"}
    d["shipping_note"] = ("Order before 16:00 ships next day. Delivery: East China 1-2d, "
                          "South 2-3d, North/West 3-4d.")
    return json.dumps(d, ensure_ascii=False)


def tool_get_quote(sku: str, quantity: int, distributor_class: str = "A") -> str:
    conn = db()
    real = find_sku(conn, sku)
    if not real:
        conn.close()
        return json.dumps({"error": f"SKU '{sku}' not found"}, ensure_ascii=False)
    pr = conn.execute("SELECT * FROM pricing WHERE sku=?", (real,)).fetchone()
    conn.close()
    cls = distributor_class.upper().strip()
    if cls not in ("A", "B", "C"):
        cls = "A"
    unit = pr[f"class_{cls.lower()}_price"]
    moq = pr[f"moq_{cls.lower()}"]
    disc = pr[f"class_{cls.lower()}_disc"]
    quantity = int(quantity)
    subtotal = round(unit * quantity, 2)
    vat = round(subtotal * 0.13, 2)
    result = {
        "sku": real, "distributor_class": cls, "quantity": quantity,
        "list_price": pr["list_price"], "unit_price": unit,
        "discount_pct": disc, "moq": moq,
        "moq_ok": quantity >= (moq or 0),
        "subtotal_excl_vat": subtotal, "vat_13pct": vat,
        "total_incl_vat": round(subtotal + vat, 2), "currency": "RMB",
    }
    if moq and quantity >= moq * 3:
        result["volume_discount_note"] = "Order exceeds 3x MOQ - eligible for extra volume discount, contact sales."
    if subtotal >= 500000:
        result["special_pricing_note"] = "Order value >¥500K - eligible for special project pricing."
    return json.dumps(result, ensure_ascii=False)


def tool_get_cross_sell(product: str) -> str:
    conn = db()
    real = find_sku(conn, product) or product
    rows = conn.execute(
        "SELECT * FROM cross_sell WHERE primary_product LIKE ? OR ? LIKE '%' || primary_product || '%'",
        (f"%{real}%", real)).fetchall()
    if not rows:
        # category / application level rules
        p = conn.execute("SELECT category, bore_mm FROM products WHERE sku=?", (real,)).fetchone()
        if p:
            pats = []
            if p["category"] == "Spherical Roller":
                pats.append("%Spherical Roller%")
            if p["bore_mm"] and p["bore_mm"] >= 100:
                pats.append("%>100mm%")
            pats.append("%Any Bearing Purchase%")
            q = " OR ".join("primary_product LIKE ?" for _ in pats)
            rows = conn.execute(f"SELECT * FROM cross_sell WHERE {q}", pats).fetchall()
    conn.close()
    return json.dumps([dict(r) for r in rows], ensure_ascii=False) or "[]"


def tool_list_products(category: str = "") -> str:
    conn = db()
    if category:
        rows = conn.execute("SELECT sku, description, category FROM products WHERE category LIKE ?",
                            (f"%{category}%",)).fetchall()
    else:
        rows = conn.execute("SELECT sku, description, category FROM products").fetchall()
    conn.close()
    return json.dumps([dict(r) for r in rows], ensure_ascii=False)


def tool_create_engineer_ticket(order_id: str, site_address: str = "",
                                preferred_date: str = "", contact_name: str = "",
                                notes: str = "") -> str:
    """Create a field-service work item in Azure DevOps for on-site installation."""
    import requests as _rq
    conn = db()
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id.strip().upper(),)).fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"Order '{order_id}' not found - cannot dispatch engineer"}, ensure_ascii=False)
    o = dict(row)
    contact_name = contact_name or o.get("customer_name") or ""
    site_address = site_address or o.get("customer_address") or ""
    contact_phone = o.get("customer_phone") or ""
    title = f"[FSE] 现场安装支持 - {o['sku']} x{o['quantity']} ({o['order_id']})"
    desc_lines = [
        "<b>SKF 现场服务派工单（Field Service Engineer Dispatch）</b>",
        f"关联订单: {o['order_id']}（状态: {o['status']}，下单时间: {o['created_at']}）",
        f"产品: {o['sku']} × {o['quantity']} 套",
        f"订单金额（含税）: ¥{o['total_incl_vat']}",
        f"服务类型: 轴承安装指导 / 现场技术支持",
        f"客户联系人: {contact_name or '待补充'}",
        f"联系电话: {contact_phone or '待补充'}",
        f"服务地址: {site_address or '待与客户确认'}",
        f"期望上门时间: {preferred_date or '1个工作日内联系客户预约'}",
        f"备注: {notes or '无'}",
    ]
    try:
        r = _rq.post(f"{AGENT_BASE_URL}/api/work-items/create", json={
            "title": title,
            "description": "<br>".join(desc_lines),
            "work_item_type": "Task",
            "priority": "high",
            "tags": ["field-service", "skf-copilot", "installation", o["order_id"]],
        }, timeout=30)
        res = r.json()
    except Exception as e:
        return json.dumps({"error": f"Ticket system unavailable: {e}"}, ensure_ascii=False)
    if not res.get("success"):
        return json.dumps({"error": res.get("error", "ticket creation failed")}, ensure_ascii=False)
    return json.dumps({
        "success": True, "ticket_id": res["work_item_id"], "title": res["title"],
        "state": res["state"], "url": res["url"],
        "order_id": o["order_id"], "sku": o["sku"], "quantity": o["quantity"],
        "contact_name": contact_name or "待补充",
        "contact_phone_masked": (contact_phone[:3] + "****" + contact_phone[-4:]) if len(contact_phone) >= 7 else (contact_phone or "待补充"),
        "site_address": site_address or "待与客户确认",
        "preferred_date": preferred_date or "1个工作日内联系客户预约",
        "sla": "工程师将在1个工作日内与客户联系确认上门时间",
    }, ensure_ascii=False)


def tool_get_order(order_id: str) -> str:
    conn = db()
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id.strip().upper(),)).fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"Order '{order_id}' not found"}, ensure_ascii=False)
    d = dict(row)
    ph = d.get("customer_phone") or ""
    if len(ph) >= 7:
        d["customer_phone"] = ph[:3] + "****" + ph[-4:]
    return json.dumps(d, ensure_ascii=False)


TOOLS_IMPL = {
    "create_engineer_ticket": tool_create_engineer_ticket,
    "get_order": tool_get_order,
    "search_knowledge": tool_search_knowledge,
    "get_product": tool_get_product,
    "check_inventory": tool_check_inventory,
    "get_quote": tool_get_quote,
    "get_cross_sell": tool_get_cross_sell,
    "list_products": tool_list_products,
}

TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "create_engineer_ticket",
        "description": "Dispatch a field service engineer: creates an Azure DevOps work order for on-site bearing installation support, linked to a paid order. Use ONLY after the customer confirms they want an engineer.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "the paid order ID, e.g. ORD-20260808-1234"},
            "site_address": {"type": "string", "description": "installation site address if the customer provided it"},
            "preferred_date": {"type": "string", "description": "preferred visit date/time if provided"},
            "contact_name": {"type": "string", "description": "customer contact name if provided"},
            "notes": {"type": "string", "description": "extra requirements, e.g. equipment type, urgency"}},
            "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "get_order",
        "description": "Look up a placed order by order ID (e.g. ORD-20260808-1234): SKU, quantity, price, payment status. Use when the user says they placed/paid an order.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "Semantic search over SKF knowledge base: product specs, application guides, business context, FAQ, cross-sell rules. Use for technical selection, application questions, general questions.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "search query, can be Chinese or English"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_product",
        "description": "Get exact technical specifications of one SKU (bore, OD, width, load ratings, speed limit).",
        "parameters": {"type": "object", "properties": {
            "sku": {"type": "string"}}, "required": ["sku"]}}},
    {"type": "function", "function": {
        "name": "check_inventory",
        "description": "Check real-time stock of a SKU across Shanghai/Dalian/Jinan warehouses, with reorder point and shipping lead times.",
        "parameters": {"type": "object", "properties": {
            "sku": {"type": "string"}}, "required": ["sku"]}}},
    {"type": "function", "function": {
        "name": "get_quote",
        "description": "Calculate a quotation: unit price by distributor class (A/B/C), MOQ check, subtotal, 13% VAT, total. Always use this for pricing questions, never guess prices.",
        "parameters": {"type": "object", "properties": {
            "sku": {"type": "string"},
            "quantity": {"type": "integer"},
            "distributor_class": {"type": "string", "enum": ["A", "B", "C"]}},
            "required": ["sku", "quantity"]}}},
    {"type": "function", "function": {
        "name": "get_cross_sell",
        "description": "Get cross-sell / accessory recommendations for a product (seals, grease, tools, sensors) based on association rules.",
        "parameters": {"type": "object", "properties": {
            "product": {"type": "string", "description": "SKU or product/application name"}},
            "required": ["product"]}}},
    {"type": "function", "function": {
        "name": "list_products",
        "description": "List catalog SKUs, optionally filtered by category (Deep Groove, Spherical Roller, Tapered Roller, Mounted Unit, Lubrication, Seal, Tool, Monitoring).",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string"}}, "required": []}}},
]

SYSTEM_PROMPT = """You are the SKF Distributor Copilot (SKF 经销商智能助手), combining the roles of technical engineer, inventory coordinator, pricing analyst, and cross-sell advisor for SKF China distributors.

LANGUAGE: Always reply in the same language as the user (Chinese question -> Chinese answer).

DATA DISCIPLINE (critical):
- All prices, stock numbers, and specs MUST come from tool results. NEVER invent numbers.
- For pricing always call get_quote. For stock always call check_inventory. For specs call get_product.
- NEVER mention a SKU that is not in the catalog (the 25 SKUs from list_products). Accessory recommendations MUST come from get_cross_sell results and be actual catalog SKUs (e.g. seals are CR 80x100x10 / CR 100x120x12, grease LGMT 2 / LGEP 2 / LGHP 2, tools TKTL 10 / TMBA 10, sensor CMSS 200-VL). Do not invent seal or accessory model numbers.
- If a SKU is not found, say so clearly and suggest close alternatives from list_products or search_knowledge. Never fabricate.
- The catalog data is the SINGLE SOURCE OF TRUTH. Do NOT use your pre-trained knowledge to add, correct, or question product specifications (dimensions, materials, grease composition, designation suffixes like W33/CC). Do not compare tool results against what you "remember" about SKF/FAG products. Do not mention SKU variants that are not in the catalog. If the user's stated specs differ from catalog data, simply present the catalog data as authoritative.
- IMAGES: the ONLY valid image URLs are the exact image_url values returned by get_product (paths like /product-images/xxx.png). NEVER invent, guess or modify an image URL, never use external URLs (skf.com etc.), and never claim a picture is an "official product photo" or "matches the official catalogue" - these are representative category illustrations. If get_product returned no image_url, say no picture is available.
- Do NOT invent product attributes that are not in tool results: no seal materials (NBR/FKM), IP ratings, temperature ranges, sensor output specs (4-20mA), grease fill states, or industry-standard claims ("C3 is standard for motors >55kW"). Describe accessories ONLY with the description and reason fields returned by tools.
- For vibration / shock load applications (vibrating screens, etc.), prefer C3 clearance variants (e.g. 22320 E/C3 over 22320 E) and explain why; mention the standard-clearance option as a cheaper alternative.

WORKFLOW for a full inquiry (technical selection with quote):
1. For application-type questions (motor, pump, fan, conveyor, gearbox, agricultural, food industry), FIRST call get_cross_sell with the application name (e.g. "Motor Application") - the catalog has authoritative application-to-product rules. Base your primary recommendation on that rule:
   - Motor -> 6205-2RS/C3 + LGMT 2 | Pump -> 6205-2RS + LGHP 2 | Fan (high temp) -> 22320 E/C3 + LGHP 2 | Conveyor -> 22216 E + LGEP 2 + Seal | Gearbox -> 32210/32212 + LGEP 2
2. search_knowledge for supporting technical context
3. get_product to confirm specs - this step is MANDATORY for every recommended main product, even if you already know the specs from other tools, because get_product is the ONLY source of the product image (image_url) which must be shown in the answer
4. check_inventory for stock
5. get_quote for pricing (ask distributor class if unknown; default Class A with a note)
6. get_cross_sell for accessories and include the high-priority ones with reasons

CONVERSATION HYGIENE: Each new question must be evaluated on its own. Do not let a previous product discussion (e.g. vibrating screen bearings) bias the recommendation for a new application (e.g. motor). Re-run the application rule lookup for every new use case.

TOOLS ARE MANDATORY EVERY TURN: You MUST actually call the tools in the current turn for any specs, stock, price, image or rule you present - even if the same SKU was discussed earlier in this conversation. NEVER copy numbers from earlier assistant messages in the history; they may be stale or wrong - re-query. NEVER write tool names or call syntax in your answer text (no "get_product(...)", "search_knowledge(...)", "来自 get_product" etc.) - customers must never see internal tool names. If you did not call a tool this turn, you have no data to show.

CUSTOMER ADDRESSING: Orders carry customer_name (e.g. "王伟"). Once you know the customer's name from get_order, address them warmly by surname: "王先生/王女士" (if gender unknown, use "王先生/女士" or just "王工"). Use this in order confirmations and engineer dispatch replies. Never read out the full phone number - it is already masked in tool results; show it as-is.

ORDER CONFIRMATION: When the user says they have placed/paid an order and provides an order ID (e.g. "我已经下单了，订单号 ORD-20260808-1234"), call get_order with that ID. If found, confirm warmly with the order details (SKU, quantity, amount incl. VAT, status), then proactively ask: "需要我们派工程师协助安装吗？" If they want an engineer, confirm a follow-up will be scheduled within 1 working day. If the order is not found, apologize and ask them to double-check the order ID.

ENGINEER DISPATCH: When the customer confirms they want an engineer for installation (e.g. "需要", "帮我安排工程师"), IMMEDIATELY call create_engineer_ticket with the order ID from the conversation (plus address/date/contact if the customer mentioned them). Output NO text before or while calling the tool (the UI already shows a "正在开单" status). Only after the tool returns, give ONE final answer starting with "好的，已为您开单安排工程师：" - never write that sentence twice. After the tool returns success, present the work order info as a compact table: 工单号, 工单标题, 关联订单, 产品与数量, 服务地址, 预约时间, SLA承诺, and the ticket link as [查看工单](url). If the customer hasn't given an address, note that the engineer will confirm the address when contacting them - do NOT block ticket creation waiting for the address. If the tool returns an error, apologize and give the hotline 400-810-8878 as fallback.

ORDER STATUS QUERY: When the user asks about an order status ("查一下订单 ORD-xxx", "我的订单到哪了"), call get_order with the order ID. Report SKU, quantity, amount, payment status and order time in a compact list. Status PAID means 已支付，仓库备货中，下单次日发货（华东1-2天/华南2-3天/华北西部3-4天）. If no order ID was given, ask for it.

QUOTE REPORTING: If get_quote returns moq_ok=false, you MUST prominently state that the quantity is below MOQ and what the minimum is. Never silently quote a below-MOQ quantity.

BUSINESS RULES:
- Prices exclude 13% VAT; always show both excl. and incl. VAT totals for quotes.
- Check MOQ; if quantity below MOQ, tell the user the minimum.
- Quantity >= 3x MOQ: mention extra volume discount eligibility.
- Order value > ¥500K: mention special project pricing.
- Open bearings: always recommend seal + grease. Bearings with bore >= 100mm: recommend TKTL 10 heater.
- Low stock (status Low Stock): warn the user and suggest checking other warehouses or reserving.

STYLE (critical):
- While you are still calling tools, output NO text at all. Only produce text once, as the single final answer after all tool calls are done. Never narrate your workflow ("我将按标准流程...", "现在开始执行...") and never repeat or re-summarize the recommendation multiple times.
- Structure of the final answer:
  1. A warm, personalized opening that acknowledges the customer's situation, e.g. "根据您描述的水泵应用工况（80°C、连续运行），我们为您推荐以下方案：" Then state the recommendation with a 1-2 sentence reason.
  2. Product image: if get_product returned an image_url, show it right after the recommendation with markdown: <img src="IMAGE_URL" alt="SKU" width="180" />. Show at most 2 images per answer (main product + optionally the grease/accessory). Then key specs of the recommended product(s): a short markdown table or bullet list with the important parameters from get_product (dimensions, load rating, speed limit, etc.).
  3. Inventory: a proper markdown table with one row per warehouse (Shanghai / Dalian / Jinan) plus a total row and status. Never cram warehouses into one line with slashes.
  4. Quote: a proper markdown table (SKU, qty, unit price, excl. VAT subtotal, VAT, incl. VAT total). State the MOQ warning clearly if applicable. Right after the quote table, ALWAYS add an order link so the customer can place the order online: [🛒 立即下单](/order.html?sku=URLENCODED_SKU&qty=QTY&cls=CLASS) — use the quoted SKU, quantity and distributor class as URL parameters (URL-encode the SKU, e.g. spaces as %20, slashes as %2F).
  5. Accessories from get_cross_sell with a one-line reason each.
  6. A friendly closing with concrete next steps (确认订单 / 调整数量 / 生成正式报价单).
- Formatting: use clean markdown tables or bullet lists, NEVER slash-separated ("上海3890 / 大连1560") or pipe-separated inline text.
- Target length: a well-organized answer of roughly 15-30 lines. Complete but not repetitive; every section appears exactly once.
- Keep the tone professional, warm and helpful, like an experienced SKF sales engineer."""


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    distributor_class: str = ""


@app.get("/api/skf/health")
async def health():
    conn = db()
    n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    return {"status": "ok", "service": "skf-copilot", "products": n,
            "vectors": vectorstore.index.ntotal, "model": QWEN_MODEL}


@app.get("/api/skf/quote-calc")
async def quote_calc(sku: str, qty: int = 1, cls: str = "A"):
    """Live price calculation for the order page."""
    q = json.loads(tool_get_quote(sku, qty, cls))
    if "error" not in q:
        conn = db()
        p = conn.execute("SELECT description, category FROM products WHERE sku=?", (q["sku"],)).fetchone()
        conn.close()
        if p:
            q["description"] = p["description"]
            q["image_url"] = CATEGORY_IMAGES.get(p["category"], "")
    return q


class OrderRequest(BaseModel):
    sku: str
    quantity: int
    distributor_class: str = "A"
    customer_name: str = ""
    customer_phone: str = ""
    customer_address: str = ""


@app.post("/api/skf/order")
async def place_order(req: OrderRequest):
    from datetime import datetime
    import random
    q = json.loads(tool_get_quote(req.sku, req.quantity, req.distributor_class))
    if "error" in q:
        return {"success": False, "error": q["error"]}
    order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    conn = db()
    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (order_id, q["sku"], q["quantity"], q["distributor_class"],
                  q["unit_price"], q["subtotal_excl_vat"], q["vat_13pct"],
                  q["total_incl_vat"], "PAID", datetime.now().isoformat(timespec="seconds"),
                  req.customer_name.strip(), req.customer_phone.strip(),
                  req.customer_address.strip()))
    conn.commit()
    conn.close()
    logger.info("Order placed: %s %s x%d", order_id, q["sku"], q["quantity"])
    return {"success": True, "order_id": order_id, **q}


@app.get("/api/skf/order/{order_id}")
async def get_order(order_id: str):
    conn = db()
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id.upper(),)).fetchone()
    conn.close()
    return dict(row) if row else {"error": "not found"}


@app.post("/api/skf/reset")
async def reset(req: ChatRequest):
    sessions.pop(req.session_id, None)
    return {"ok": True}


@app.post("/api/skf/chat")
async def chat(req: ChatRequest):
    history = sessions.setdefault(req.session_id, [])
    user_msg = req.message
    if req.distributor_class:
        user_msg += f"\n[system note: distributor class = {req.distributor_class}]"
    history.append({"role": "user", "content": user_msg})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-MAX_HISTORY:]
    tool_trace = []

    for _ in range(15):
        resp = client.chat.completions.create(
            model=QWEN_MODEL, messages=messages, tools=TOOLS_SPEC,
            parallel_tool_calls=True, temperature=0.3, max_tokens=2000)
        msg = resp.choices[0].message

        if not msg.tool_calls:
            answer = msg.content or ""
            history.append({"role": "assistant", "content": answer})
            sessions[req.session_id] = history[-MAX_HISTORY:]
            return {"success": True, "answer": answer, "tools_used": tool_trace,
                    "session_id": req.session_id}

        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            fname = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            logger.info("tool call: %s(%s)", fname, args)
            tool_trace.append({"tool": fname, "args": args})
            try:
                result = TOOLS_IMPL[fname](**args)
            except Exception as e:
                result = json.dumps({"error": str(e)}, ensure_ascii=False)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # Tool budget exhausted: force a final answer from collected data
    messages.append({"role": "user", "content":
                     "Please give your final answer now based on the tool results collected so far. Do not call any more tools."})
    resp = client.chat.completions.create(model=QWEN_MODEL, messages=messages,
                                          temperature=0.3, max_tokens=2000)
    answer = resp.choices[0].message.content or ""
    history.append({"role": "assistant", "content": answer})
    sessions[req.session_id] = history[-MAX_HISTORY:]
    return {"success": True, "answer": answer, "tools_used": tool_trace,
            "session_id": req.session_id}


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


TOOL_STATUS = {
    "create_engineer_ticket": "正在为您开单安排工程师...",
    "get_order": "正在核实订单信息...",
    "search_knowledge": "正在检索知识库...",
    "get_product": "正在查询产品规格...",
    "check_inventory": "正在查询库存...",
    "get_quote": "正在计算报价...",
    "get_cross_sell": "正在匹配配件推荐...",
    "list_products": "正在查询产品目录...",
}


@app.post("/api/skf/chat-stream")
async def chat_stream(req: ChatRequest):
    """SSE streaming version of chat: tool status events + token stream."""
    history = sessions.setdefault(req.session_id, [])
    user_msg = req.message
    if req.distributor_class:
        user_msg += f"\n[system note: distributor class = {req.distributor_class}]"
    history.append({"role": "user", "content": user_msg})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-MAX_HISTORY:]

    def gen():
        full_answer = []
        try:
            for _ in range(15):
                stream = client.chat.completions.create(
                    model=QWEN_MODEL, messages=messages, tools=TOOLS_SPEC,
                    parallel_tool_calls=True, temperature=0.3, max_tokens=2000, stream=True)

                tool_calls = {}   # index -> {id, name, arguments}
                content_started = False

                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            slot = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                            if tc.id:
                                slot["id"] = tc.id
                            if tc.function and tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                slot["arguments"] += tc.function.arguments
                    if delta.content:
                        content_started = True
                        full_answer.append(delta.content)
                        yield sse({"event": "message", "answer": delta.content})

                if not tool_calls:
                    # Final answer finished streaming
                    answer = "".join(full_answer)
                    history.append({"role": "assistant", "content": answer})
                    sessions[req.session_id] = history[-MAX_HISTORY:]
                    yield sse({"event": "message_end"})
                    return

                # Execute tools, announce status
                assistant_msg = {"role": "assistant", "content": "",
                                 "tool_calls": [{"id": s["id"], "type": "function",
                                                 "function": {"name": s["name"], "arguments": s["arguments"]}}
                                                for s in tool_calls.values()]}
                messages.append(assistant_msg)
                for s in tool_calls.values():
                    fname = s["name"]
                    yield sse({"event": "tool", "tool": fname,
                               "status": TOOL_STATUS.get(fname, f"正在调用 {fname}...")})
                    try:
                        args = json.loads(s["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    logger.info("tool call: %s(%s)", fname, args)
                    try:
                        result = TOOLS_IMPL[fname](**args)
                    except Exception as e:
                        result = json.dumps({"error": str(e)}, ensure_ascii=False)
                    messages.append({"role": "tool", "tool_call_id": s["id"], "content": result})

            # Tool budget exhausted: force a streamed final answer without tools
            messages.append({"role": "user", "content":
                             "Please give your final answer now based on the tool results collected so far. Do not call any more tools."})
            final_stream = client.chat.completions.create(
                model=QWEN_MODEL, messages=messages,
                temperature=0.3, max_tokens=2000, stream=True)
            for chunk in final_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    full_answer.append(chunk.choices[0].delta.content)
                    yield sse({"event": "message", "answer": chunk.choices[0].delta.content})
            answer = "".join(full_answer)
            history.append({"role": "assistant", "content": answer})
            sessions[req.session_id] = history[-MAX_HISTORY:]
            yield sse({"event": "message_end"})
        except Exception as e:
            logger.error("stream error: %s", e)
            yield sse({"event": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)

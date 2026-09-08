"""
SKF Copilot data ingestion:
- Parse markdown tables from source_data/ into SQLite (exact queries)
- Build Chroma vector index with DashScope embeddings (semantic retrieval)
"""
import os
import re
import sqlite3
from pathlib import Path

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

BASE = Path(__file__).parent
SRC = Path(os.environ.get("SOURCE_DATA_DIR", "/root/helpdesk/source_data"))
DB_PATH = BASE / "skf.db"
INDEX_DIR = BASE / "chroma_index"


def parse_md_tables(md_text: str):
    """Return list of tables; each table is list of row dicts keyed by header."""
    tables = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            headers = [h.strip().strip("*") for h in line.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip().strip("*") for c in lines[i].strip().strip("|").split("|")]
                if len(cells) == len(headers):
                    rows.append(dict(zip(headers, cells)))
                i += 1
            tables.append(rows)
        else:
            i += 1
    return tables


def num(s):
    """Parse a number from strings like '2,450', '¥850.50', '37%', 'N/A'."""
    if s is None:
        return None
    s = str(s).replace(",", "").replace("¥", "").replace("%", "").strip()
    if s in ("", "N/A", "-"):
        return None
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else None


def build_sqlite():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS products;
    DROP TABLE IF EXISTS inventory;
    DROP TABLE IF EXISTS pricing;
    DROP TABLE IF EXISTS cross_sell;
    CREATE TABLE products (sku TEXT PRIMARY KEY, description TEXT, category TEXT,
        bore_mm REAL, od_mm REAL, width_mm REAL, weight_kg REAL,
        c_kn REAL, c0_kn REAL, speed_limit_rpm REAL);
    CREATE TABLE inventory (sku TEXT PRIMARY KEY, shanghai INTEGER, dalian INTEGER,
        jinan INTEGER, total INTEGER, status TEXT, reorder_point INTEGER);
    CREATE TABLE pricing (sku TEXT PRIMARY KEY, list_price REAL,
        class_a_price REAL, class_a_disc REAL, class_b_price REAL, class_b_disc REAL,
        class_c_price REAL, class_c_disc REAL, moq_a INTEGER, moq_b INTEGER, moq_c INTEGER);
    CREATE TABLE cross_sell (primary_product TEXT, add_on TEXT, confidence REAL,
        reason TEXT, priority TEXT);
    """)

    prod = parse_md_tables((SRC / "product_catalog.md").read_text())[0]
    for r in prod:
        c.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", (
            r["SKU"], r["Description"], r["Category"],
            num(r["Bore (mm)"]), num(r["OD (mm)"]), num(r["Width (mm)"]),
            num(r["Weight (kg)"]), num(r["C (kN)"]), num(r["C0 (kN)"]),
            num(r["Speed Limit (RPM)"])))

    inv = parse_md_tables((SRC / "inventory.md").read_text())[0]
    for r in inv:
        c.execute("INSERT INTO inventory VALUES (?,?,?,?,?,?,?)", (
            r["SKU"], num(r["Shanghai DC"]), num(r["Dalian DC"]), num(r["Jinan DC"]),
            num(r["Total Stock"]), r["Status"], num(r["Reorder Point"])))

    price = parse_md_tables((SRC / "pricing.md").read_text())[0]
    for r in price:
        c.execute("INSERT INTO pricing VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            r["SKU"], num(r["List Price"]),
            num(r["Class A Price"]), num(r["Class A Disc"]),
            num(r["Class B Price"]), num(r["Class B Disc"]),
            num(r["Class C Price"]), num(r["Class C Disc"]),
            num(r["MOQ A"]), num(r["MOQ B"]), num(r["MOQ C"])))

    xs = parse_md_tables((SRC / "cross_sell_rules.md").read_text())[0]
    for r in xs:
        c.execute("INSERT INTO cross_sell VALUES (?,?,?,?,?)", (
            r["Primary Product"], r["Recommended Add-On"], num(r["Confidence"]),
            r["Reason"], r["Priority"]))

    conn.commit()
    n = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("products", "inventory", "pricing", "cross_sell")}
    conn.close()
    print(f"SQLite done: {n}")
    return n


def build_vectors():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    docs = []

    # Row-level natural language descriptions for each SKU (spec + stock + price)
    for p in conn.execute("SELECT * FROM products"):
        inv = conn.execute("SELECT * FROM inventory WHERE sku=?", (p["sku"],)).fetchone()
        pr = conn.execute("SELECT * FROM pricing WHERE sku=?", (p["sku"],)).fetchone()
        parts = [f"SKF {p['sku']}: {p['description']}, category {p['category']}."]
        if p["bore_mm"]:
            parts.append(f"Bore {p['bore_mm']}mm, OD {p['od_mm']}mm, width {p['width_mm']}mm.")
        if p["c_kn"]:
            parts.append(f"Dynamic load rating C={p['c_kn']}kN, static C0={p['c0_kn']}kN, speed limit {p['speed_limit_rpm']} RPM.")
        if inv:
            parts.append(f"Stock: Shanghai {inv['shanghai']}, Dalian {inv['dalian']}, Jinan {inv['jinan']}, total {inv['total']} ({inv['status']}).")
        if pr:
            parts.append(f"List price ¥{pr['list_price']}, Class A ¥{pr['class_a_price']}, Class B ¥{pr['class_b_price']}, Class C ¥{pr['class_c_price']} (RMB, excl. 13% VAT).")
        docs.append(Document(page_content=" ".join(parts),
                             metadata={"type": "product", "sku": p["sku"]}))

    for r in conn.execute("SELECT * FROM cross_sell"):
        docs.append(Document(
            page_content=(f"Cross-sell rule: when buying {r['primary_product']}, "
                          f"recommend {r['add_on']} (confidence {r['confidence']}%, "
                          f"priority {r['priority']}). Reason: {r['reason']}."),
            metadata={"type": "cross_sell", "primary": r["primary_product"]}))
    conn.close()

    # Knowledge docs: chunk by markdown section headings
    for fname in ("business_context.md", "response_templates.md", "top50_queries.md"):
        text = (SRC / fname).read_text()
        chunks = re.split(r"\n(?=#{1,3} )", text)
        for ch in chunks:
            ch = ch.strip()
            if len(ch) > 40:
                docs.append(Document(page_content=ch[:3000], metadata={"type": "knowledge", "source": fname}))

    print(f"Embedding {len(docs)} documents...")
    emb = DashScopeEmbeddings(model="text-embedding-v3",
                              dashscope_api_key=os.environ["QWEN_API_KEY"])
    # Chroma: 若目录已存在则先删除，避免重复追加
    import shutil
    if INDEX_DIR.exists():
        shutil.rmtree(INDEX_DIR)
    vs = Chroma.from_documents(
        docs, emb,
        persist_directory=str(INDEX_DIR),
        collection_name="skf_copilot",
    )
    print(f"Chroma index saved to {INDEX_DIR} ({vs._collection.count()} vectors)")


if __name__ == "__main__":
    build_sqlite()
    build_vectors()

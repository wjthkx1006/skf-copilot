# SKF Distributor Copilot + IT HelpDesk — 一体化智能助手平台

集 **SKF 经销商 Copilot**（前台）与 **企业 IT Helpdesk**（后台）于一体的 AI 对话平台，支持产品查询、报价下单、工程师派工、IT 工单、内容安全护栏等完整业务流程，一键 Docker 部署。

---

## 目录

- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [核心模块：SKF Distributor Copilot（前台）](#核心模块skf-distributor-copilot前台)
- [核心模块：IT HelpDesk（后台）](#核心模块it-helpdesk后台)
- [支撑组件](#支撑组件)
- [快速部署（Docker）](#快速部署docker)
- [本地开发](#本地开发)
- [环境变量说明](#环境变量说明)
- [数据管理](#数据管理)
- [常用运维命令](#常用运维命令)

---

## 系统架构

```
浏览器 :4000
   │
   ▼
frontend（nginx — React 单页应用 + API 反向代理）
   ├── /api/skf/*       → skf-copilot :8005   SKF 经销商 Copilot（RAG + 下单 + 派工）
   ├── /api/guardrail*  → guardrail   :8003   内容安全护栏
   ├── /api/logs        → guardrail   :8003
   ├── /api/auth/*      → auth-server :8002   Azure AD SAML SSO 认证
   └── /api/*           → agent       :8001   Azure DevOps 工单代理
```

| 服务 | 端口 | 技术栈 |
|------|------|--------|
| frontend | 4000 (对外) | React + Vite + nginx |
| skf-copilot | 8005 (内部) | FastAPI + Chroma + DashScope + SQLite |
| agent | 8001 (内部) | FastAPI + Azure DevOps REST API |
| guardrail | 8003 (内部) | FastAPI + Qwen + 阿里云绿网 |
| auth-server | 8002 (内部) | FastAPI + SAML + JWT |

---

## 核心模块：SKF Distributor Copilot（前台）

> **定位**：面向 SKF 中国经销商的 AI 销售助手，集技术选型、库存查询、报价计算、下单和现场工程师派工于一体。

### 功能

| 功能 | 说明 |
|------|------|
| **产品技术选型** | 根据应用工况（电机/泵/风机/输送机/齿轮箱等）推荐轴承型号，给出规格参数与选型理由 |
| **库存查询** | 实时查询上海/大连/济南三仓库库存及备货状态 |
| **智能报价** | 按经销商等级（A/B/C类）计算含税/不含税单价、MOQ 校验、批量折扣提示 |
| **配件交叉销售** | 基于关联规则推荐密封圈、润滑脂、安装工具、传感器等配件 |
| **在线下单** | 前端订单页直接提交，生成订单号并写入 SQLite |
| **工程师派工** | 订单确认后一键在 Azure DevOps 创建现场服务工单，附地址/联系人/SLA |
| **多轮对话** | 会话历史保持，支持追问与上下文记忆（最多 20 条） |
| **流式输出** | SSE 实时推流，工具调用过程显示中间状态（正在检索/计算/开单…） |

### 技术实现

- **RAG**：DashScope `text-embedding-v3` 向量化产品目录、业务知识、FAQ，Chroma 本地向量检索（`chroma_index/`）
- **精确查询**：SQLite 存储产品规格、库存、价格、订单，Tool Calling 驱动精确数字查询，拒绝 LLM 幻觉报价
- **大模型**：`qwen-plus`（通义千问），兼容 OpenAI SDK，支持 `parallel_tool_calls`，最多 15 轮工具调用
- **数据摄取**：`ingest.py` 从 `source_data/` 解析 Markdown 表格到 SQLite，同步构建 Chroma 向量索引

### 数据文件（`source_data/`）

| 文件 | 内容 |
|------|------|
| `product_catalog.md` | 25 个 SKU：规格、载荷、转速等 |
| `inventory.md` | 三仓库实时库存 |
| `pricing.md` | A/B/C 类价格、折扣、MOQ |
| `cross_sell_rules.md` | 产品关联推荐规则 |
| `business_context.md` | 业务背景与政策 |
| `response_templates.md` | 标准话术模板 |
| `top50_queries.md` | 高频问题 FAQ |

### API 端点（`/api/skf/`）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/skf/chat` | POST | 对话（非流式） |
| `/api/skf/chat-stream` | POST | 对话（SSE 流式） |
| `/api/skf/order` | POST | 提交订单 |
| `/api/skf/order/{id}` | GET | 查询订单 |
| `/api/skf/quote-calc` | GET | 实时报价计算 |
| `/api/skf/reset` | POST | 清除会话历史 |
| `/api/skf/health` | GET | 健康检查 |

---

## 核心模块：IT HelpDesk（后台）

> **定位**：企业内部 IT 服务台，基于 Dify 云端 Agent，对话式创建和查询 Azure DevOps 工单，集成 SSO 认证与内容安全护栏。

### 功能

| 功能 | 说明 |
|------|------|
| **自然语言开单** | 用中/英文描述 IT 问题，自动在 Azure DevOps 创建工单 |
| **工单查询/更新** | 按 ID 查询工单状态、更新优先级和备注 |
| **历史对话** | 通过 Dify API 持久化对话记录，支持按时间分组浏览与搜索 |
| **SSO 登录** | Azure AD SAML 2.0 单点登录，JWT 会话，24 小时有效 |
| **内容安全** | 多层护栏（规则 + Qwen AI + 阿里云绿网）防护提示词注入、PII 泄露、辱骂、政治内容等 |

### Azure DevOps Agent（`dify-azure-devops-agent/`）

- 提供 REST API 供 Dify 工具调用，OpenAPI 规范见 `openapi_spec.json`
- 工单管理：创建、查询、更新、列表
- Dify 工具集：`ChatWithAgent` / `CreateTicket` / `GetTicket` / `ListTickets` / `UpdateTicket`

### 认证服务（`dify-chatbot/auth-server/`）

- SAML SP 实现，对接 Azure AD（Tenant ID 配置于代码）
- 认证流：浏览器 → `/api/auth/saml/login` → Azure AD → ACS 回调 → 签发 JWT → 前端
- 端点：`/api/auth/me`、`/api/auth/verify`、`/api/auth/saml/logout`

### 内容安全护栏（`dify-chatbot/guardrail-server/`）

十层检测，按顺序短路执行：

| 优先级 | 规则 | 类型 |
|--------|------|------|
| 1 | 提示词注入检测 | 正则规则 |
| 2 | PII（身份证/手机/银行卡）检测 | 正则规则 |
| 3 | 财务敏感词检测 | 关键词规则 |
| 4 | 有害内容检测 | 正则规则 |
| 5 | 辱骂语言检测（中英双语） | 正则规则 |
| 6 | 负面情绪标记（仅记录） | 正则规则 |
| 7 | 阿里云绿网 AI 审核 | 云服务 API |
| 8 | AI 政治内容意图检测 | Qwen |
| 9 | AI 语义综合检测 | Qwen |

- 规则开关可通过 `/api/guardrail/rules` 端点实时切换
- 所有检测事件写入日志文件，可通过 `/api/logs` 端点查看

---

## 支撑组件

### 前端（`dify-chatbot/src/`）

- React + Vite 单页应用
- **双模式切换**：侧边栏按钮在「IT Helpdesk」和「SKF Copilot」模式间切换，共享同一 UI
- Markdown 渲染（含 GFM 表格、HTML 图片标签）、深色/浅色主题、对话历史

### 前台页面（`dify-chatbot/public/`）

| 页面 | 功能 |
|------|------|
| `order.html` | 产品下单页（接收 SKU/qty/class 参数，实时报价后提交） |
| `guardrail.html` | 内容安全管理后台（规则开关、实时日志） |
| `logs.html` | 护栏审计日志查看 |

---

## 快速部署（Docker）

### 前置条件

- Docker Desktop（Windows 使用 WSL2 后端）或 Docker Engine（Linux）
- 能访问 `dashscope.aliyuncs.com`（千问）、`dev.azure.com`（工单）、`api.dify.ai`（HelpDesk）

### 步骤

```powershell
# 1. 配置环境变量
Copy-Item .env.docker.example .env.docker
# 编辑 .env.docker，填入真实密钥（见下方环境变量说明）

# 2. 构建并启动（首次约 3-5 分钟）
docker compose up -d

# 3. 查看状态（4 个容器应全部 Up）
docker compose ps

# 4. 访问
# 浏览器打开 http://localhost:4000
```

> **离线部署**：如有预先构建好的镜像包 `helpdesk-images.tar.gz`，可直接 `docker load -i helpdesk-images.tar.gz` 后跳至第 2 步。

---

## 本地开发

### SKF Copilot 后端

```bash
cd skf-copilot
pip install fastapi uvicorn openai langchain-community faiss-cpu dashscope

# 首次：构建 SQLite + FAISS 索引
export QWEN_API_KEY=sk-xxxx
python ingest.py

# 启动开发服务器
uvicorn server:app --reload --port 8005
```

### 前端

```bash
cd dify-chatbot
npm install
npm run dev   # 默认 :5173，代理到后端
```

### 护栏服务

```bash
cd dify-chatbot/guardrail-server
pip install -r requirements.txt
uvicorn main:app --reload --port 8003
```

---

## 环境变量说明

复制 `.env.docker.example` 为 `.env.docker` 并填写：

| 变量 | 必填 | 说明 |
|------|------|------|
| `QWEN_API_KEY` | ✅ | 通义千问 / DashScope API Key（`sk-xxxx`） |
| `DASHSCOPE_API_KEY` | ✅ | 同上（向量化服务用） |
| `QWEN_MODEL` | — | 默认 `qwen-plus` |
| `AZURE_DEVOPS_ORG` | ✅ | Azure DevOps 组织名 |
| `AZURE_DEVOPS_PROJECT` | ✅ | 项目名 |
| `AZURE_DEVOPS_PAT` | ✅ | Personal Access Token（需要工单读写权限） |
| `AGENT_API_KEY` | ✅ | Agent 服务自定义鉴权 Key |
| `ALIYUN_ACCESS_KEY_ID` | 可选 | 阿里云内容安全（绿网）AK |
| `ALIYUN_ACCESS_KEY_SECRET` | 可选 | 阿里云内容安全 SK |
| `ALIYUN_REGION` | 可选 | 默认 `cn-shanghai` |
| `GUARDRAILS_ENABLED` | 可选 | 默认 `true`，设为 `false` 可全局关闭护栏 |

---

## 数据管理

| 数据 | 存储位置 | 说明 |
|------|---------|------|
| 产品目录 + 订单 | Docker volume `skf-data`（`/data/skf.db`） | 首次启动自动从镜像内种子库初始化 |
| 护栏日志 + 规则开关 | Docker volume `guardrail-data` | 持久化，重启不丢失 |

**备份订单数据库：**

```powershell
docker run --rm -v helpdesk_skf-data:/data -v ${PWD}:/backup alpine cp /data/skf.db /backup/skf.db.bak
```

**重建向量索引**（更新产品数据后）：

```bash
docker compose exec skf-copilot python ingest.py
```

> 重建时会自动清空旧的 `chroma_index/` 目录再重新写入，无需手动删除。

---

## 常用运维命令

```powershell
# 查看实时日志
docker compose logs -f skf-copilot

# 重启单个服务
docker compose restart guardrail

# 停止全部（数据保留）
docker compose down

# 修改端口（默认 4000 被占用时）
$env:FRONTEND_PORT=8080; docker compose up -d
```

---

## 技术栈

### 全局一览

| 层次 | 技术 | 版本 / 说明 |
|------|------|------------|
| **容器编排** | Docker Compose | 四服务编排，内部网络隔离，仅 4000 端口对外 |
| **反向代理** | nginx | 静态文件服务 + API 路由转发 |
| **前端框架** | React 18 | Hooks + 函数组件 |
| **前端构建** | Vite | 开发热更新，生产静态打包 |
| **后端框架** | FastAPI (Python 3.10+) | 全异步，Pydantic 数据校验，OpenAPI 文档自动生成 |
| **ASGI 服务器** | Uvicorn | 生产环境运行所有 Python 服务 |
| **大语言模型** | 通义千问 `qwen-plus` | 兼容 OpenAI SDK，支持 parallel tool calls |
| **向量嵌入** | DashScope `text-embedding-v3` | 1536 维，中英文双语 |
| **向量检索** | Chroma 1.5 | 本地持久化向量库，`similarity_search` Top-K 检索，支持元数据过滤 |
| **结构化存储** | SQLite 3 | 产品/库存/价格/订单，零额外依赖 |
| **认证协议** | SAML 2.0 + JWT | Azure AD IdP，HS256 签名，24 小时有效期 |
| **AI 内容安全** | 阿里云绿网 SDK + Qwen | 文本审核 + 语义意图检测双重防护 |
| **外部集成** | Azure DevOps REST API | 工单（Work Items）CRUD |
| **AI 平台** | Dify Cloud | IT HelpDesk Agent 托管，对话历史持久化 |

---

### 前端技术栈

```
React 18
├── react-markdown          # Markdown 渲染
│   ├── remark-gfm          # GitHub 风格：表格、删除线、任务列表
│   └── rehype-raw          # 允许内联 HTML（产品图片 <img> 标签）
└── Vite                    # 构建工具
    └── vite.config.js      # 开发代理 → 后端各端口
```

关键设计决策：
- **双模式 UI**：同一个 React 应用通过 `botMode` 状态切换 IT Helpdesk（Dify SSE）和 SKF Copilot（本地 SSE），避免维护两套前端
- **SSE 流式消费**：手动解析 `ReadableStream`，逐行处理 `data:` 事件，实时追加 Markdown 内容到消息气泡
- **乐观更新**：对话历史删除、重命名操作先更新本地状态再请求 API，保证 UI 即时响应
- **Token 管理**：JWT 存 `localStorage`，每次请求前通过 `/api/auth/verify` 校验；SAML 回调后 token 从 URL query param 提取并清除，防止 Referer 泄露

---

### SKF Copilot 后端技术栈

```
FastAPI
├── 对话层
│   ├── OpenAI Python SDK     # 兼容 DashScope /compatible-mode/v1
│   ├── parallel_tool_calls   # 同一轮多工具并发调用
│   ├── SSE StreamingResponse # 流式推送 tool/message/message_end 事件
│   └── 会话管理              # 内存字典 {session_id: [messages]}，最多 20 条
├── RAG 层
│   ├── LangChain Community   # Chroma + DashScope 封装
│   ├── Chroma                # 本地持久化向量库（chroma_index/），similarity_search(k=5)
│   └── DashScopeEmbeddings   # text-embedding-v3，摄取 + 检索共用
└── 数据层
    ├── SQLite                # 产品规格 / 库存 / 价格 / 订单
    └── sqlite3 Row Factory   # 查询结果直接转 dict，无 ORM 开销
```

**Tool Calling 设计**：8 个工具，职责严格分离，LLM 只负责意图理解和语言生成，所有数字必须来自工具返回值：

| 工具 | 数据来源 | 用途 |
|------|---------|------|
| `search_knowledge` | FAISS | 语义检索产品知识、业务规则、FAQ |
| `get_product` | SQLite `products` | 精确规格 + 产品图片 URL |
| `check_inventory` | SQLite `inventory` | 三仓库实时库存 |
| `get_quote` | SQLite `pricing` | 含税/不含税报价、MOQ 校验 |
| `get_cross_sell` | SQLite `cross_sell` | 配件关联推荐 |
| `list_products` | SQLite `products` | 按类别浏览目录 |
| `get_order` | SQLite `orders` | 订单详情（手机号脱敏） |
| `create_engineer_ticket` | Azure DevOps API | 现场服务工单创建 |

**数据摄取流水线（`ingest.py`）**：
1. 解析 `source_data/` 中的 Markdown 表格 → SQLite（精确查询）
2. 将每行记录转为自然语言描述文本 → Chroma（语义检索）
3. 将业务知识文档按 `## / ###` 标题切块 → Chroma

---

### IT HelpDesk 后端技术栈

```
FastAPI（三个独立服务，共享同一 Docker 镜像）
├── azure_devops_agent（:8001）
│   ├── Azure DevOps REST API   # Basic Auth (PAT)，Work Items CRUD
│   ├── Qwen LLM                # 自然语言 → 工单字段提取
│   └── X-API-Key 鉴权          # 简单 Header 验证
├── auth-server（:8002）
│   ├── python-saml / 手写 XML  # SAML AuthnRequest 构造 + Response 解析
│   ├── PyJWT                   # HS256 签发，无状态会话
│   └── zlib + base64           # SAML Redirect Binding 编解码
└── guardrail-server（:8003）
    ├── 规则引擎                 # re 正则，纯 CPU，<1ms
    ├── alibabacloud-green SDK  # 文本内容审核（可选）
    ├── Qwen AI 语义检测         # 政治意图 + 综合安全，超时 5-10s
    └── deque(maxlen=1000)      # 内存日志环形缓冲，REST 接口实时查看
```

**护栏分层策略**：规则检测（<1ms）→ 云 API 审核（~200ms）→ LLM 语义检测（~2s），命中即短路，未命中才进入下一层，在延迟和准确率间取得平衡。

---

### 基础设施技术栈

```
Docker
├── Dockerfile.backend    # python:3.11-slim，安装依赖后 COPY 全部代码
├── Dockerfile.frontend   # node:20-alpine 构建 → nginx:alpine 服务
└── nginx.conf            # 静态文件 + /api/* 反向代理规则

Docker Compose
├── 4 个服务（agent / guardrail / skf-copilot / frontend）
├── 2 个命名卷（skf-data / guardrail-data）——数据持久化
└── 内部网络——后端端口不对外暴露
```

---

## 项目结构

```
.
├── skf-copilot/                # SKF 经销商 Copilot 后端
│   ├── server.py               # FastAPI 主服务（RAG + 工具调用 + 下单 + 派工）
│   ├── ingest.py               # 数据摄取（SQLite + FAISS 向量索引构建）
│   ├── skf.db                  # 种子数据库（产品/库存/价格）
│   └── chroma_index/           # 预构建向量索引（Chroma 格式）
├── dify-chatbot/               # IT HelpDesk 前台 + 前端
│   ├── src/                    # React 前端（双模式：HelpDesk + SKF Copilot）
│   ├── public/                 # 订单页、护栏管理页、日志页
│   ├── auth-server/            # SAML SSO 认证服务
│   └── guardrail-server/       # 内容安全护栏服务
├── dify-azure-devops-agent/    # Azure DevOps 工单代理
│   ├── azure_devops_agent.py   # FastAPI 工单 API
│   └── openapi_spec.json       # Dify 工具 OpenAPI 规范
├── source_data/                # SKF 原始数据（Markdown 格式）
├── deploy/                     # Dockerfile + nginx 配置
├── docker-compose.yml          # 一键编排
└── .env.docker.example         # 环境变量模板
```

---

## License

MIT

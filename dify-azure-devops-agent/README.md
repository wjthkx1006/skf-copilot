# Azure DevOps ITSM Agent

AI-powered IT Service Management Agent for creating, querying, updating, and listing tickets in Azure DevOps. Designed to integrate with Dify AI platform.

## ✨ Features

- 🎫 **Ticket Management** - Create, query, update, and list work items
- 🤖 **AI-Powered Chat** - Natural language interface using Qwen LLM
- 🛡️ **Content Security** - Aliyun Guardrails for prompt injection & PII protection
- 🔌 **Dify Integration** - OpenAPI spec ready for Dify AI Agent tools
- ⚡ **FastAPI Backend** - High-performance async API

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Azure DevOps account with PAT (Personal Access Token)
- (Optional) Aliyun account for Qwen API & Guardrails

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/dify-azure-devops-agent.git
cd dify-azure-devops-agent
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate  # Windows
```

### 3. Install Dependencies

```bash
pip install fastapi uvicorn requests pydantic
# Optional: For Aliyun Guardrails
pip install alibabacloud-green20220302 alibabacloud-tea-openapi
```

### 4. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `AZURE_DEVOPS_ORG` | Azure DevOps organization name | ✅ |
| `AZURE_DEVOPS_PROJECT` | Azure DevOps project name | ✅ |
| `AZURE_DEVOPS_PAT` | Personal Access Token | ✅ |
| `AGENT_API_KEY` | API key for authentication | ✅ |
| `QWEN_API_KEY` | Qwen/Tongyi API key | Optional |
| `QWEN_MODEL` | Qwen model name (default: qwen-plus) | Optional |
| `ALIYUN_ACCESS_KEY_ID` | Aliyun AK for Guardrails | Optional |
| `ALIYUN_ACCESS_KEY_SECRET` | Aliyun SK for Guardrails | Optional |
| `GUARDRAILS_ENABLED` | Enable content security (true/false) | Optional |

### 5. Run the Server

```bash
# Development
python azure_devops_agent.py

# Or with uvicorn directly
uvicorn azure_devops_agent:app --host 0.0.0.0 --port 8001 --reload
```

Server will start at `http://localhost:8001`

---

## 📡 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | AI chat interface for natural language ticket management |
| `/api/tickets` | POST | Create a new ticket |
| `/api/tickets` | GET | List tickets with filters |
| `/api/tickets/{id}` | GET | Get ticket details |
| `/api/tickets/{id}` | PUT | Update a ticket |
| `/api/categories` | GET | Get available categories |
| `/health` | GET | Health check |
| `/api/guardrails/events` | GET | View guardrail events (admin) |

### Example: Create Ticket via Chat

```bash
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"message": "My VPN is not working", "caller": "John Doe"}'
```

### Example: List Tickets

```bash
curl http://localhost:8001/api/tickets \
  -H "X-API-Key: your-api-key"
```

---

## 🔗 Dify Integration

### Import OpenAPI Spec

1. In Dify Studio, go to **Tools** → **Custom Tools**
2. Click **Create Custom Tool**
3. Import `openapi_spec.json` or paste the content
4. Configure the API key in tool settings

### Available Tools for Dify Agent

| Tool | Description |
|------|-------------|
| `ChatWithAgent` | Natural language ticket management |
| `CreateTicket` | Create a new support ticket |
| `GetTicket` | Get ticket details by ID |
| `ListTickets` | List tickets with filters |
| `UpdateTicket` | Update ticket status/details |
| `GetCategories` | Get available ticket categories |

---

## 🛡️ Security Features

### Content Guardrails

- **Prompt Injection Detection** - Blocks attempts to manipulate AI behavior
- **PII Protection** - Detects and flags sensitive personal information
- **Aliyun Integration** - Enterprise-grade content moderation

### Authentication

- API key authentication via `X-API-Key` header
- Configurable per-environment

---

## 📁 Project Structure

```
dify-azure-devops-agent/
├── azure_devops_agent.py   # Main FastAPI application
├── openapi_spec.json       # OpenAPI specification for Dify
├── prompt.txt              # Dify Agent system prompt
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
└── README.md               # This file
```

---

## 🖥️ Production Deployment

### Using systemd (Linux)

Create service file `/etc/systemd/system/azure-devops-agent.service`:

```ini
[Unit]
Description=Azure DevOps ITSM Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/dify
Environment="PATH=/path/to/dify/venv/bin"
EnvironmentFile=/path/to/dify/.env
ExecStart=/path/to/dify/venv/bin/uvicorn azure_devops_agent:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable azure-devops-agent
systemctl start azure-devops-agent
```

### Service Management

```bash
# View status
systemctl status azure-devops-agent

# View logs
journalctl -u azure-devops-agent -f

# Restart
systemctl restart azure-devops-agent
```

---

## 🔧 Troubleshooting

### Check if service is running

```bash
curl http://localhost:8001/health
```

### Check port usage

```bash
netstat -tlnp | grep 8001
```

### View application logs

```bash
journalctl -u azure-devops-agent -n 100
```

### Test Azure DevOps connection

```bash
curl http://localhost:8001/api/categories -H "X-API-Key: your-key"
```

---

## 📄 License

MIT License

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

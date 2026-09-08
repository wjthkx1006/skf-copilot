# HelpDesk / SKF Copilot — Windows Docker 部署指南

## 一、前置条件（Windows 机器）

1. Windows 10/11（专业版或家庭版均可），已开启虚拟化（BIOS 里 VT-x/AMD-V）。
2. 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，安装时选择 **WSL2 后端**（默认）。
3. 安装完成后启动 Docker Desktop，任务栏图标变绿即就绪。

## 二、需要拷贝到 Windows 的文件

从服务器拷贝以下文件到 Windows 任意目录（如 `D:\helpdesk\`）：

| 文件 | 说明 |
|------|------|
| `deploy/helpdesk-images.tar.gz` | 两个 Docker 镜像（后端 + 前端），约 167MB |
| `docker-compose.yml` | 编排文件（项目根目录） |
| `.env.docker` | 密钥配置（Qwen / 阿里云 / Azure DevOps），**注意保密** |

> 镜像已包含全部代码、依赖、产品数据库和向量索引，Windows 上**不需要** Python/Node 环境，也不需要拉取任何外网依赖。

## 三、部署步骤（PowerShell）

```powershell
cd D:\helpdesk

# 1. 导入镜像（一次性，约1分钟）
docker load -i helpdesk-images.tar.gz

# 2. 启动全部服务
docker compose up -d

# 3. 查看状态（4个容器应全部 Up）
docker compose ps
```

浏览器访问 `http://localhost:4000` 即可。局域网其他电脑访问 `http://<这台Windows的IP>:4000`（需在 Windows 防火墙放行 4000 端口）。

## 四、架构说明

```
浏览器 :4000
   │
   ▼
frontend (nginx, 静态页面 + API 反向代理)
   ├── /api/skf/*        → skf-copilot :8005  (SKF 经销商Copilot, RAG+下单+派工)
   ├── /api/guardrail*   → guardrail   :8003  (内容安全护栏)
   ├── /api/logs         → guardrail   :8003
   └── /api/*            → agent       :8001  (Azure DevOps 开单代理)
```

- 后端三个服务共用同一个镜像 `helpdesk-backend`，仅启动命令不同。
- 容器间通过内部网络通信，后端端口不对外暴露，只开放 4000。

## 五、数据持久化

| 数据 | 位置 | 说明 |
|------|------|------|
| 订单数据库（含产品目录） | volume `skf-data` | 首次启动时自动从镜像内种子库初始化 |
| Guardrail 日志与规则开关 | volume `guardrail-data` | |

容器重启/升级镜像都不会丢数据。备份：`docker run --rm -v helpdesk_skf-data:/data -v ${PWD}:/backup alpine cp /data/skf.db /backup/`

## 六、常用运维命令

```powershell
docker compose logs -f skf-copilot   # 看某个服务的日志
docker compose restart guardrail     # 重启单个服务
docker compose down                  # 停止全部（数据保留）
docker compose up -d                 # 再次启动
```

## 七、注意事项

1. **出站网络**：Windows 机器需能访问 `dashscope.aliyuncs.com`（千问/向量化）、`green-cip.cn-shanghai.aliyuncs.com`（阿里云内容安全）、`dev.azure.com`（开单）。公司代理环境需在 Docker Desktop → Settings → Resources → Proxies 里配置。
2. **端口冲突**：如 4000 被占用，启动时改用 `$env:FRONTEND_PORT=8080; docker compose up -d`。
3. **更新版本**：服务器上重新构建镜像并导出 tar.gz，Windows 上 `docker load` 后 `docker compose up -d` 即自动换新（数据不受影响）。

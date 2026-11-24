# 部署与使用手册

## 1. 环境

- macOS / Linux / Windows WSL2
- Python 3.11+
- uv
- Node.js 20.19+
- npm
- Google Chrome（仅浏览器端到端测试需要）

## 2. 安装

```bash
cd backend
uv sync --group dev

cd ../frontend
npm ci
```

## 3. 启动

项目根目录执行：

```bash
./scripts/dev.sh
```

访问：

- `http://127.0.0.1:5173`
- `http://127.0.0.1:8000/docs`

自定义端口：

```bash
LEARNFLOW_API_PORT=8100 LEARNFLOW_WEB_PORT=5200 ./scripts/dev.sh
```

## 4. 演示路径

1. 注册并登录独立账号。
2. 创建自己的知识文件夹。
3. 上传资料、课堂照片或写入快速笔记。
4. 在知识库搜索内容并打开来源。
5. 建立学习画像后进入资源工作室，选择个人文件夹生成六类资源。
6. 查看资源中的个人知识来源。
7. 完成路径、辅导和评估闭环。

## 5. 运行测试

```bash
./scripts/test-all.sh
```

## 6. 生成提交包

```bash
./scripts/package-submission.sh
```

输出：

- `submission/LearnFlow-A3/`
- `submission/LearnFlow-A3.zip`

脚本排除 Git、虚拟环境、依赖目录、缓存、运行数据和 `.env`。

## 7. 常见问题

### 页面显示“后端尚未连接”

确认 API 健康检查：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/health/ready
```

### 浏览器测试找不到 Chrome

安装 Google Chrome，或将 `frontend/playwright.config.ts` 的 `channel` 改为已安装的 Chromium。

### 需要重置演示数据

先创建备份并停止服务，再删除：

```bash
sudo /usr/local/sbin/learnflow-backup
sudo systemctl stop learnflow
rm -f backend/data/runtime/learnflow.sqlite3
sudo systemctl start learnflow
```

该操作会删除账号、工作空间、资料和学习记录，仅应在本地演示环境执行。

## 8. 生产安全

- 正式账号服务必须启用 HTTPS，使会话 Cookie 获得 `Secure` 标记。
- 学习通连接器通过 `LEARNFLOW_CHAOXING_ENABLED=true` 开启，并使用独立 `LEARNFLOW_CONNECTOR_KEY` 加密会话。
- 连接器密钥使用 `openssl rand -base64 32` 生成，不能写入源码、前端或 Git。
- ZIP 预览接口单独允许 260 MB 请求；普通资料仍限制 25 MB，学习通文档单文件限制 100 MB。
- 每日备份位于 `/var/backups/learnflow/`，默认保留 14 天。
- `/healthz` 和 `/api/health/ready` 检查数据库、上传目录和磁盘空间。
- 完整基线见 [安全与生产基线](security.md)。

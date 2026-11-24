# 公网部署

目标服务器：`124.223.49.44`

## 架构

- Nginx：监听公网 80 端口，提供 `frontend/dist`。
- Nginx：将 `/api/` 反向代理到 `127.0.0.1:8000`，支持 SSE。
- systemd：托管 FastAPI，单进程运行。
- 持久数据：`/var/lib/learnflow/learnflow.sqlite3`。
- 每日备份：`/var/backups/learnflow/`，默认保留 14 天。
- 发布目录：`/opt/learnflow/releases/<timestamp>`。
- 当前版本：`/opt/learnflow/current` 符号链接。
- 学习通连接器：FastAPI 单进程内的持久化任务执行器，默认关闭。

## 前置条件

服务器需允许 SSH 登录，并满足以下任一条件：

- 直接使用 `root` 登录。
- 使用具备免密 `sudo` 权限的云服务器账号。

服务器安全组需开放 TCP 80。若使用域名，后续再把 Nginx `server_name` 更新为域名。

## 本机部署

```bash
DEPLOY_HOST=124.223.49.44 \
DEPLOY_USER=root \
DEPLOY_SSH_KEY="$HOME/.ssh/id_ed25519" \
./scripts/deploy-remote.sh
```

首次部署建议保留完整测试：

```bash
DEPLOY_USER=root ./scripts/deploy-remote.sh
```

测试已单独完成时可跳过：

```bash
DEPLOY_SKIP_TESTS=1 DEPLOY_USER=root ./scripts/deploy-remote.sh
```

## 验证

```bash
curl http://124.223.49.44/healthz
curl http://124.223.49.44/api/health
curl http://124.223.49.44/api/health/ready
```

浏览器访问：

```text
http://124.223.49.44/
```

## 更新与持久化

- 每次部署创建新 release，并切换 `current` 符号链接。
- SQLite 数据不随 release 更新。
- systemd 环境文件：`/etc/learnflow/learnflow.env`。
- 模型密钥只写入服务器环境文件，不进入发布包。
- 启用学习通连接器：

```bash
sudo sh -c 'printf "LEARNFLOW_CHAOXING_ENABLED=true\nLEARNFLOW_CONNECTOR_KEY=%s\n" "$(openssl rand -base64 32)" >> /etc/learnflow/learnflow.env'
sudo systemctl restart learnflow
```

- 连接器密钥必须保留在服务器密钥管理或备份中；修改密钥会使旧的学习通会话失效，但已导入资料不受影响。
- Nginx 仅对 ZIP 预览接口放宽到 260 MB；普通资料上传仍受 30 MB 请求上限和 25 MB 业务上限约束。
- `learnflow-backup.timer` 每日执行 SQLite 在线备份并检查完整性。
- HTTPS 启用前，会话 Cookie 不会带 `Secure`；正式账号服务必须配置域名和 TLS。

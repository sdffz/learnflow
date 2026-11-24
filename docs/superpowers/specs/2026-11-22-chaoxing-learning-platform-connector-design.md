# 知序 LearnFlow 学习通扫码导入设计规格

日期：2026-11-22  
状态：已确认，进入实施  
范围：个人学习通账号扫码连接、课程与文档资料预览、选择性导入、同步任务和安全边界

## 1. 目标

知序允许用户通过本人学习通账号，把课程、文件夹和文档资料按课程导入个人知识空间。连接过程使用学习通官方二维码登录，不要求用户向知序提供学习通密码。

本阶段必须完成：

1. 手机和电脑均可完成扫码连接。
2. 用户导入前可预览课程、文件和预计容量。
3. 只导入 PDF、PPT、Word、图片和文本；视频不下载。
4. 导入资料进入现有个人知识库，支持正文提取、知识片段、搜索和来源追溯。
5. 会话、任务和个人资料严格限制在当前知序用户与工作空间。
6. 学习通登录或页面结构异常时安全暂停，不绕过验证码或风险控制。
7. 提供 ZIP 资料包手动导入作为稳定备用入口。

## 2. 非目标

- 不实现学习通账号密码登录或长期保存密码。
- 不下载课程视频，不破解课程权限或绕过验证码。
- 不导入用户没有权限访问的课程或资料。
- 不在不同用户之间共享学习通会话、课程目录和资料。
- 本阶段不建设独立分布式任务集群；任务在现有单节点服务内持久化和执行。

## 3. 产品流程

### 3.1 连接学习通

1. 用户在知识文件夹页点击“连接学习通”。
2. 知序创建一次性连接会话并展示学习通官方二维码。
3. 用户使用学习通 App 扫码，并在 App 内确认登录。
4. 知序显示脱敏昵称和连接状态。
5. 会话默认保留 24 小时；过期后重新扫码。
6. 用户可随时断开连接，知序立即删除加密会话。

二维码有效期为 5 分钟。刷新、取消、过期、扫码待确认、扫码成功和会话失效均展示明确状态。

### 3.2 预览和选择

1. 知序读取本人课程目录与资料清单。
2. 课程默认不勾选，显示课程名称、教师/班级信息、文档数、视频链接数、预计容量和文件类型。
3. 用户可展开课程查看文件。
4. 不支持或超过限制的文件显示排除原因。
5. 用户选择课程后进入文件夹映射。

### 3.3 文件夹映射

- 每门课程默认新建同名知识文件夹。
- 已有同名文件夹时，用户选择“合并”或“新建副本”。
- 映射结果在最终确认页中可修改。
- 用户确认课程、文件、容量和映射后启动同步。

### 3.4 后台同步

任务状态包括：等待、读取目录、下载、解析、完成、部分失败、已取消、会话过期。

用户可以离开页面，重新进入后继续查看进度。单个文件失败不停止其他文件；完成后可只重试失败项。视频资料以每门课程一份“视频资料链接”笔记保存，不占用文件容量。

### 3.5 ZIP 备用导入

用户可上传包含课程文件夹和文档资料的 ZIP。服务器在安全限制内展开目录、生成预览，再复用同一映射和同步任务流程。禁止路径穿越、符号链接、嵌套压缩包和超大解压体积。

## 4. 架构

### 4.1 模块边界

- `learning_connector.py`：学习通连接领域模型、二维码会话和上游适配器协议。
- `learning_connector_store.py`：连接、会话密文、预览、任务和明细的 SQLite 持久化。
- `learning_connector_api.py`：连接、二维码、预览、导入、进度、取消、重试和断开 API。
- `learning_sync.py`：后台同步、文件下载、校验、去重、导入和失败隔离。
- `LearningConnectorDialog.tsx`：扫码、预览、映射、确认、进度与结果向导。
- `SettingsPage.tsx` 或现有账户区域：连接状态、最近同步、断开和 ZIP 导入入口。

连接器只通过现有 `KnowledgeStore` 写入课程和资料，不建立第二套知识库。

### 4.2 上游适配

服务端使用独立 `httpx.Client`：

1. 打开学习通官方登录页。
2. 解析二维码 `uuid`、`enc` 和当前会话 Cookie。
3. 代理二维码图片并在当前连接上下文中轮询授权状态。
4. 授权成功后保存该客户端 Cookie，读取课程和资料页面。
5. 下载文档时校验域名、重定向、大小、MIME 和文件签名。

上游适配器实现固定接口。页面或接口变化只影响适配器，不修改知识库和前端流程。

## 5. 数据模型

### 5.1 LearningConnection

```ts
interface LearningConnection {
  id: string;
  provider: "chaoxing";
  remoteNickname: string | null;
  status: "pending" | "connected" | "expired" | "error" | "revoked";
  expiresAt: string | null;
  lastSyncedAt: string | null;
  createdAt: string;
  updatedAt: string;
}
```

底层表包含 `workspace_id`、`user_id`、AES-GCM 加密会话密文、随机 nonce、密钥版本和上游账号指纹。每个用户最多一个活动连接。

### 5.2 ImportPreview

```ts
interface ImportPreview {
  id: string;
  courses: PreviewCourse[];
  totalDocuments: number;
  totalVideoLinks: number;
  totalBytes: number;
  generatedAt: string;
  expiresAt: string;
}
```

预览明细只保存导入所需的课程和文件元数据，不保存文档正文。

### 5.3 ImportJob

```ts
interface ImportJob {
  id: string;
  status: ImportJobStatus;
  progress: number;
  totalItems: number;
  completedItems: number;
  failedItems: number;
  skippedItems: number;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  errorCode: string | null;
  errorMessage: string | null;
}
```

任务明细记录上游课程/文件 ID、映射后的知序课程、状态、重试次数、错误码、文件校验值及最终资料 ID。预览和任务均绑定 `workspace_id` 与 `user_id`。

## 6. 课程与资料导入

- 导入扩展名：`.pdf`、`.docx`、`.pptx`、`.md`、`.txt`、`.png`、`.jpg`、`.jpeg`、`.webp`。
- 单文件上限：100 MB。
- ZIP 解压总量上限：1 GB；单次最多 1,000 个文件。
- 工作空间仍受现有 500 MB、500 份资料配额限制。
- 学习通文件使用外部课程 ID 和文件 ID 去重。
- 同一外部文件内容未变化时跳过；内容变化时替换现有知序资料和知识片段，保留资料 ID。
- 下载文件先进入用户隔离的临时目录，完成签名校验和文本提取后才转为正式资料。
- 任务结束、失败或取消后清理临时文件。
- 视频 URL 写入课程笔记；笔记标明“仅链接、未下载”。

## 7. API

```text
GET    /api/learning/chaoxing/status
POST   /api/learning/chaoxing/login
GET    /api/learning/chaoxing/login/{login_id}
GET    /api/learning/chaoxing/login/{login_id}/qr
POST   /api/learning/chaoxing/login/{login_id}/refresh
DELETE /api/learning/chaoxing/login/{login_id}
DELETE /api/learning/chaoxing/connection
POST   /api/learning/chaoxing/previews
GET    /api/learning/imports/{job_id}
GET    /api/learning/imports/{job_id}/items
POST   /api/learning/imports
POST   /api/learning/imports/{job_id}/cancel
POST   /api/learning/imports/{job_id}/retry
POST   /api/learning/imports/zip/previews
```

所有写操作执行同源校验、CSRF 会话保护、限流和审计。跨工作空间对象返回 404。

## 8. 安全与隐私

- 二维码登录会话 5 分钟失效，一次性使用，绑定知序用户。
- 学习通 Cookie 使用 AES-256-GCM 加密，主密钥来自部署环境，不进入数据库、日志或前端。
- 默认会话有效期 24 小时；过期、断开和账号异常时立即销毁。
- API 响应只返回脱敏昵称、状态和时间，不返回 Cookie、二维码底层凭证或带签名的下载 URL。
- 域名白名单只包含学习通官方登录、课程和资料 CDN 域名。
- 重定向逐跳校验；禁止 `file:`、`localhost`、内网 IP 和非 HTTPS 上游地址。
- 请求设置连接/读取超时、最大响应体积、并发上限和重试退避。
- 连接、扫码成功、预览、导入、取消、重试和断开写入审计日志，不记录敏感内容。
- 遇到验证码、二次验证或风控页面时任务暂停并提示重新扫码；系统不自动绕过。
- 用户只能导入本人账号可见资料；界面明确展示数据范围和 24 小时会话规则。

## 9. 前端体验

- 知识文件夹页提供“连接学习通”主入口，连接后提供“从学习通导入”。
- 向导在桌面使用居中模态卡片，在手机使用全屏底部面板。
- 每一步均显示可理解的加载、成功、失败和恢复动作。
- 二维码有倒计时、刷新按钮和 App 扫码说明。
- 课程选择支持全选文档、取消全选、展开文件和查看排除原因。
- 容量超限时在启动前阻止，并显示现有占用与可释放空间。
- 同步进度轮询频率受控，页面隐藏时降低频率。
- 完成页显示成功、跳过、失败数量及查看导入资料入口。
- 设置区域提供连接状态、断开和 ZIP 导入。

## 10. 错误处理

稳定错误码至少包括：

- `connector_disabled`
- `login_not_found`
- `login_expired`
- `login_cancelled`
- `session_expired`
- `upstream_unavailable`
- `upstream_changed`
- `verification_required`
- `source_permission_denied`
- `quota_exceeded`
- `file_too_large`
- `invalid_file_content`
- `partial_import_failed`

错误信息面向用户提供下一步操作，不展示底层 Cookie、HTML 或堆栈。后端日志记录 request ID、任务 ID和错误码。

## 11. 测试

自动化测试使用本地伪学习通服务，覆盖：

- 二维码创建、图片代理、轮询、确认、取消、刷新和过期。
- 连接会话加密、解密、过期、断开和跨用户隔离。
- 域名白名单、私网地址、恶意重定向和异常响应大小。
- 课程与文件解析、文档过滤、视频链接笔记和异常页面。
- 同名文件夹合并/新建映射、容量计算和配额阻止。
- 后台任务进度、取消、部分失败、重试、重启恢复和临时文件清理。
- ZIP 路径穿越、符号链接、嵌套压缩包和解压炸弹限制。
- 加密会话不会出现在 API 响应、日志或审计记录。
- Playwright 覆盖桌面与手机扫码向导、预览、选择、任务进度和失败恢复。

真实学习通账号只用于部署后的本人扫码验收，不进入 CI。

## 12. 上线和回退

- 新增功能开关 `LEARNFLOW_CHAOXING_ENABLED`，默认关闭。
- 新增主密钥 `LEARNFLOW_CONNECTOR_KEY`；缺失时连接功能 fail closed，现有知识库不受影响。
- 数据库迁移只新增表和列，不重写现有课程、资料和知识点。
- 后台任务由持久化任务表恢复，不因普通服务重启丢失。
- 上线后依次验证 readiness、扫码、预览、单课程导入、搜索、断开和重启恢复。
- 出现上游异常或安全事件时关闭功能开关；已导入资料保持可用。

## 13. 验收标准

1. 用户可在手机和电脑打开同一公网页面并扫码连接学习通。
2. 二维码不会跨用户复用，过期或断开后立即失效。
3. 用户可预览所选课程和文档，排除项显示原因。
4. 导入后资料出现在正确文件夹并生成可搜索知识片段。
5. 重复同步不会产生重复资料；文件变化能安全更新。
6. 部分文件失败不影响其他文件，失败项可单独重试。
7. API、日志、前端和审计记录中没有学习通 Cookie 或密码。
8. 跨工作空间无法读取连接、预览、任务或导入资料。
9. 学习通不可用时可使用 ZIP 备用导入，现有知识库继续工作。
10. 断开连接后知序删除学习通会话，但保留用户已确认导入的资料。

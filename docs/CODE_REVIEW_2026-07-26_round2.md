# 代码审查报告 · 第二轮（2026-07-26）

## 本轮范围

补上第一轮（`CODE_REVIEW_2026-07-26.md`）因中断未覆盖的部分，并复查工作区新改动：

- `src/memoria/api/` 全部路由（user / dialogue / multi_dialogue / character_admin / event_admin / knowledge / speech / relationship / developer / story / streaming）
- 安全专项：CSRF 完整评估、`avatar_fetcher.py` SSRF 绕过手法、限流绕过
- 工作区新改动：`csrf.py` query 参数回退、`web/src/api/memoria.js`、`ChatRoom.jsx`、`vector_memory.py`、`vite.config.js`
- 测试执行：`.venv/bin/python -m pytest tests/ -q` → **778 passed, 1 failed**

---

## 🔴 严重

### 1. 角色卡导入接口存在路径穿越，可读取服务器上任意 `.json` 文件
- **位置**：[character_admin.py:383-394](src/memoria/api/character_admin.py#L383)，模型定义 [character_admin.py:65-67](src/memoria/api/character_admin.py#L65)
- **问题**：`file_path = characters_dir / f"{req.character_id}.json"`，`ImportFromFileRequest.character_id` 是无任何校验的自由字符串。`pathlib` 对 `..` 不做规范化，对绝对路径直接覆盖基准目录。
- **验证**（已在本机实测）：
  - `Path(".../characters") / "../../../../../.claude.json"` → `/home/nanzi/.claude.json`，`.exists()` 为 `True`
  - `Path(".../characters") / "/etc/hosts.json"` → `/etc/hosts.json`
- **失败场景**：任意已登录用户 `POST /api/v1/admin/characters/import`，body `{"character_id": "../../../../../.claude"}`：
  1. 文件存在与否直接区分为 404 / 400，构成**任意 `.json` 文件存在性探测**；
  2. 文件被 `json.loads` + `CharacterCard.model_validate` 后，pydantic v2 的 `ValidationError` 字符串**包含 `input_value` 片段**，而 handler 在 [character_admin.py:425-427](src/memoria/api/character_admin.py#L425) 用 `detail=f"导入角色卡失败: {str(e)}"` 原样返回给客户端 → **文件内容部分泄露**。实测对 `~/.claude.json` 返回 1877 字符的错误串，含 `input_value={'numStartups': 31, 'inst...tUsedNumStartups': 31}}}`。
  3. 若目标恰好是合法角色卡 JSON（例如其他部署路径下的角色卡），则**完整内容**被写入当前用户的数据库，随后可通过 `GET /admin/characters/{id}` 完整读出。
- **修复建议**：`character_id` 加白名单校验（如 `^[A-Za-z0-9_-]{1,64}$`），并在拼接后用 `file_path.resolve().is_relative_to(characters_dir.resolve())` 二次确认；同时**停止把 `str(e)` 回传客户端**（见 🟢 #12）。

### 2. 工作区测试用例失败：`_embedding_lock` 修复未同步测试
- **位置**：[vector_memory.py:49,99](src/memoria/core/vector_memory.py#L49)，[tests/test_vector_memory.py:47](tests/test_vector_memory.py#L47)
- **问题**：本轮改动为修第一轮 #40（CUDA 降级路径无锁）新增了 `self._embedding_lock = threading.Lock()`（在 `__init__` 中赋值），但 `test_encode_text_recovers_cuda_failure_to_cpu` 用 `VectorMemoryStore.__new__(...)` 绕过 `__init__` 构造对象，因此 `_recover_embedding_model_to_cpu` 里 `with self._embedding_lock:` 抛 `AttributeError`。
- **当前状态**：`1 failed, 778 passed`，工作区测试为红。
- **修复建议**：测试内补 `store._embedding_lock = threading.Lock()`；或把锁改为类级惰性初始化（`getattr(self, "_embedding_lock", None) or ...`）以免同类构造方式再次踩坑。
- **附带**：`_encode_text` 在锁外读取 `self.embedding_model` 后才调用 `.encode()`，降级窗口内仍可能拿到旧的 CUDA 模型引用；后果仅是多失败一次并再次触发降级，可接受，但值得注释说明。

---

## 🟡 中等

### 3. CSRF token 的 query 参数回退作用于**全部**写接口，令牌泄露面显著扩大
- **位置**：[csrf.py:91-93](src/memoria/core/csrf.py#L91)（本轮新增），前端 [memoria.js:30-36](web/src/api/memoria.js#L30)
- **问题**：为修第一轮 #12（`sendBeacon` 无法带自定义头）而加的回退没有做路径限定，任何 `/api/` 写请求都可以用 `?csrf_token=` 代替 `X-CSRF-Token`。CSRF token 因此可能出现在：反向代理/网关的 access log、浏览器历史、`Referer`、APM/日志采集链路。而该 token 的生命周期是 30 天（`CSRF_COOKIE_MAX_AGE`），一次日志泄露即长期有效。
- **修复建议**：把 query 回退限制在真正需要它的两条路径上（`/api/v1/dialogue/session/end`、`/api/v1/multi-dialogue/session/end`），例如用一个 `_BEACON_PATHS` 白名单；更彻底的做法是给 unload 场景签发独立的短时效一次性 token。

### 4. `POST /multi-dialogue/interaction/trigger` 的 `prompt` 无长度上限，直通 LLM
- **位置**：[multi_dialogue.py:114](src/memoria/api/multi_dialogue.py#L114) → [multi_character_orchestrator.py:1542](src/memoria/core/multi_character_orchestrator.py#L1542)
- **问题**：同文件的 `player_message` 明确限制 `max_length=8000`，但 `TriggerInteractionRequest.prompt` 没有任何约束，且原样作为 `trigger_text` 进入群聊 pulse 的 prompt 构建。
- **失败场景**：单个已登录用户提交 1 MB 的 `prompt`，直接转化为一次超长上下文的 LLM 调用（token 账单放大 100 倍以上）；若超出模型上下文，还会命中第一轮 #32——`BadRequestError` 被误判为"不支持 response_format"，导致**整个进程永久丢失 JSON 模式**。两个缺陷可以串成一次真实的持久性降级攻击。
- **修复建议**：`prompt: Optional[str] = Field(None, max_length=2000)`。

### 5. 群聊参与角色数无上限
- **位置**：[multi_dialogue.py:42](src/memoria/api/multi_dialogue.py#L42)（`min_length=2` 但无 `max_length`），校验逻辑 [multi_dialogue.py:406-419](src/memoria/api/multi_dialogue.py#L406)
- **问题**：`/admin/characters` 创建角色卡本身也无配额，用户可先建 N 个角色再开一个 N 人群聊。结合第一轮 #11（每回合对**每个参与者**重复执行约 6 条事件上下文查询），单次 `/multi-dialogue/turn` 的 DB 查询数与 LLM 调用数随 N 线性放大。
- **修复建议**：`character_ids: list[str] = Field(..., min_length=2, max_length=8)`（或与产品定义的群聊上限一致），并给角色卡数量加每用户配额。

### 6. 大量分页接口的 `limit` / `offset` 没有边界，SQLite 下 `LIMIT -1` 等于不限量
- **位置**：[dialogue.py:577-578](src/memoria/api/dialogue.py#L577)、[dialogue.py:633](src/memoria/api/dialogue.py#L633)、[developer.py:36](src/memoria/api/developer.py#L36)、[event_admin.py:923](src/memoria/api/event_admin.py#L923)、`event_admin.py:942,1115,1203,1300,1330`
- **问题**：这些都是裸 `limit: int = N`，未用 `Query(ge=..., le=...)`。对比 [user.py:686](src/memoria/api/user.py#L686) 的 `Query(default=50, ge=1, le=100)` 可见规范本身是存在的，只是没有贯彻。
- **失败场景**：
  - `GET /dialogue/history?limit=-1` → SQLite 中 `LIMIT -1` 语义为**不限行数**，一次拉全部历史消息，绕过分页；
  - `GET /admin/events/history/all?limit=100000000` → 单次响应体可达数百 MB；
  - `POST /admin/events/schedules/run-due?limit=1000000`（[event_admin.py:1300](src/memoria/api/event_admin.py#L1300)）最严重：这是同步执行到期事件的接口，`limit` 直接决定单请求内执行多少次事件（含 LLM 主动对白），可把一个 worker 卡住极长时间。
- **修复建议**：统一改为 `Query(default=N, ge=1, le=<上限>)`。

### 7. 登录接口存在用户名枚举时序侧信道，且无针对性节流
- **位置**：[user.py:441-443](src/memoria/api/user.py#L441)
- **问题**：`if not user or not _verify_password(...)`——用户不存在时**完全不做 PBKDF2**，用户存在时做 210,000 轮 SHA256（约 100 ms）。响应时间差异稳定且巨大，可可靠枚举有效用户名。
- **附带**：全局限流是每窗口 60 次写请求（[main.py:302](src/memoria/main.py#L302)），未登录时按 `request.client.host` 计数，没有按账号的失败计数或锁定。60 次/分钟的在线口令猜测对弱口令是实际可行的，分布式 IP 下无上限。
- **修复建议**：用户不存在时也走一次等价开销的 dummy hash；对 `/user/login` 单独加"同一用户名连续失败"计数与指数退避。

### 8. `POST /relationships/batch` 请求体列表无上限
- **位置**：[relationship.py:412-415](src/memoria/api/relationship.py#L412)
- **问题**：`relationships: list[RelationshipCreateRequest]` 无 `max_length`，循环内每项执行 `_require_relationship_characters` + `get_character_relationship` + `save_character_relationship`（3+ 条 SQL）。提交 10 万项即 30 万条 SQL 的同步请求，且整个 body 先在内存中解析成 pydantic 对象。
- **修复建议**：`Field(..., max_length=200)`，或改成有明确批次上限的分页写入。

### 9. 全局缺少请求体大小上限
- **位置**：[knowledge.py:315-329](src/memoria/api/knowledge.py#L315)（`PastedDocumentCreate.text` 只有 `min_length=1`）、[knowledge.py:285](src/memoria/api/knowledge.py#L285)、`user.py` / `character_admin.py` / `speech.py` 的各 `UploadFile` 端点
- **问题**：`validate_document_size` / `read_upload_limited` 都是**读完之后**才校验。JSON body 由 FastAPI 先整体读入内存再解析；multipart 由 Starlette 先落盘缓冲（超过 1 MB 转 `SpooledTemporaryFile` 到磁盘）。应用层没有任何前置的 `Content-Length` 拦截。
- **失败场景**：单个已登录用户 POST 一个 10 GB 的 multipart 上传，在 handler 拿到控制权之前磁盘已被写满；或 POST 一个 2 GB 的 JSON 粘贴文档触发 OOM。
- **修复建议**：加一个前置中间件按 `Content-Length` 直接 413；文档中明确要求网关层配置 `client_max_body_size`。

### 10. 开发代理端口改成 8002，但全部文档仍写 8001
- **位置**：[vite.config.js:20](web/vite.config.js#L20)（本轮改动 8001 → 8002）
- **不一致的文档**：[README.md:314](README.md#L314)、[docs/CONTRIBUTING.md:28](docs/CONTRIBUTING.md#L28)、[docs/FAQ.md:20,40,313,322](docs/FAQ.md#L20)、[docs/API.md:5](docs/API.md#L5) 全部指示 `--port 8001`。
- **后果**：按文档启动后端的开发者，前端 `/api` 代理 100% 502。若这个改动只是本地调试残留，应在提交前还原。

---

## 🟢 低

| # | 问题 | 位置 |
|---|---|---|
| 11 | `/admin/log-level` 不在 `/api/` 前缀下，`validate_csrf` 第 79 行直接放行，限流中间件同样跳过。目前靠 `SameSite=Lax` + 管理员依赖兜底，但"按路径前缀决定是否防护"这个模式很脆弱：任何将来挂在 `/api/` 之外的写路由都会静默失去 CSRF 与限流 | [main.py:272-279](src/memoria/main.py#L272)，[csrf.py:79-80](src/memoria/core/csrf.py#L79) |
| 12 | 内部异常信息回传客户端：`raise HTTPException(500, detail=f"...{str(e)}")` 泄露 SQL 错误、路径、pydantic 输入值 | `character_admin.py:95,138,204,279,328,364,427,512,556,598`，`relationship.py:406,456`，`event_admin.py:1307` |
| 13 | 用 `print(f"[ERROR] ...")` 而非 logger，容器化部署下丢失结构化日志与级别 | [dialogue.py:392](src/memoria/api/dialogue.py#L392) |
| 14 | GET 请求带写副作用：`/dialogue/sessions/player`、`/dialogue/session/latest` 会调 `_close_idle_sessions` → 结束会话并触发 LLM 摘要。GET 被限流中间件豁免，也不受 CSRF 保护 | [dialogue.py:539,556](src/memoria/api/dialogue.py#L539)、[main.py:302](src/memoria/main.py#L302) |
| 15 | 限流 key 回退到 `request.client.host`，未读取 `X-Forwarded-For`。反向代理后所有匿名请求共用同一个计数桶，60 次/分钟会变成全站共享额度；需确保 uvicorn 以 `--proxy-headers` 启动并配置 `--forwarded-allow-ips`。另外 `_get_rate_limit_key` 每个写请求都做一次 token 的 DB 查询，与第一轮 #20（无效 token 触发全表清理 DELETE）叠加后可被放大成写压力 | [main.py:111-123](src/memoria/main.py#L111) |
| 16 | `SetAvatarUrlRequest.url`、`StartMultiSessionRequest.player_name` / `group_name` 均无 `max_length`，与同文件其它字段的约束风格不一致 | [user.py:208-209](src/memoria/api/user.py#L208)，[multi_dialogue.py:39-41](src/memoria/api/multi_dialogue.py#L39) |
| 17 | `_validate_username` 的 `^[\w一-鿿-]+$` 中 `\w` 在 Python 3 默认匹配全部 Unicode 字母，实际允许西里尔/希腊字母等，与提示文案"字母、数字、中文"不符，且存在同形字冒名风险 | [user.py:115](src/memoria/api/user.py#L115) |
| 18 | `avatar_fetcher` 未限制目标端口，公网 IP 上的任意端口都可探测（返回体/错误差异构成端口扫描信道）；建议限制到 80/443 | [avatar_fetcher.py:99](src/memoria/api/avatar_fetcher.py#L99) |
| 19 | 尺寸/体积达标的头像会**原样存储**（`normalize_avatar_image` 直接返回原 bytes），PNG+HTML polyglot 会被完整保留在 data URL 中。当前只作 `<img src>` 使用，不可执行；若将来出现下载/新窗口打开路径需重新评估 | [avatar_image.py:94-99](src/memoria/api/avatar_image.py#L94) |
| 20 | `create_transcription` / `voice_status` 等在 `except SpeechServiceError` 分支调用 `_raise_service_error(exc)`，依赖该函数内部必然 `raise`。类型上函数返回 `None`，静态检查读不出来，改动时容易退化成静默返回 `None` | [speech.py:31-35](src/memoria/api/speech.py#L31) |

---

## ✅ 正面确认

- **`avatar_fetcher.py` 的 SSRF 防护是本次审查里质量最高的部分**，逐项确认无绕过：
  - IP 字面量、十进制/八进制等 legacy 数值形式（`socket.inet_aton` 探测后拒绝）、IDNA、尾点、`user:pass@`、控制字符与反斜杠全部拦截；
  - 解析结果**全部**地址都要通过 `is_global` 检查（不是只查第一个），并在本机 Python 3.10.12 上验证 `::ffff:127.0.0.1` / `::ffff:169.254.169.254` / `100.64.0.1` / `0.0.0.0` 均判定为非全局；
  - 连接固定到已校验的 IP（`request_url` 用 IP，`Host` 头用主机名，HTTPS 走 `_PinnedHTTPSAdapter` 设 `server_hostname` + `assert_hostname`），**并在响应后用 `getpeername()` 复验实际对端**——DNS rebinding 的两个窗口都堵上了；
  - 每一跳重定向都重新走完整 `_validate_url`，重定向上限 3；
  - 代理环境的 fake-IP（198.18/15）会切换到 DoH 解析，且 DoH 端点本身也是 IP 字面量 + 证书 pinning；
  - `trust_env = False` 阻断 `HTTP_PROXY` 环境变量劫持；deadline + `threading.Timer` 双保险防慢速读取；`BoundedSemaphore(8)` 限制并发；`Content-Length` 与实际流式字节数双重限制 8 MB。
- **`avatar_image.py` 正确忽略客户端声明的 MIME**，格式一律由 PIL 解码结果决定（`_avatar_data_url` 里显式 `del mime_type`），并有 `MAX_AVATAR_PIXELS` + `DecompressionBombError` 的解压炸弹防护。
- **API 层鉴权覆盖完整**：逐条核对全部 90+ 路由，无一遗漏认证依赖；`_require_player_access` / `_get_owned_session` / `_get_owned_multi_session` / `_require_base` / `_require_document` / `_require_owned_character` 的所有权校验一致，未发现 IDOR。`preview_knowledge` 对 `character_id` / `group_thread_id` 做了绑定目标白名单复核。
- **密码存储正确**：PBKDF2-SHA256 / 210k 轮 / 每用户随机 salt，`hmac.compare_digest` 比对，登录时自动重哈希旧的裸 SHA256，`admin_bootstrap_token` 也走定长安全比较。`users.username` 有 `UNIQUE` 约束（`_common.py:321`），注册的 check-then-act 有 DB 层兜底。
- **`streaming.py` 的 SSE 桥接质量高**：自管道 + `add_reader` 的跨线程唤醒、10 秒心跳、`BoundedSemaphore` 限并发、断连后 `StreamDisconnected` 传播、`finally` 中 fd 与信号量的释放顺序均正确；`DialogueTurnConflictError` 保留了 409 语义，其它异常统一脱敏为通用文案。
- **本轮已落地的第一轮修复经复查有效**：#12（CSRF 导致结束会话 403，机制上已修，但作用域过宽见 🟡 #3）、#31（`ChatRoom.jsx` 空 `catch {}` 已改为设置错误态）。

---

---

## 修复状态（2026-07-26 同日完成）

测试：`.venv/bin/python -m pytest tests/ -q` → **803 passed**（修复前为 778 passed / 1 failed，本轮新增 24 条回归测试）。

| # | 状态 | 改动 |
|---|---|---|
| 1 | ✅ 已修 | `ImportFromFileRequest.character_id` 加 `pattern=^[A-Za-z0-9_-]+$` + 长度限制；拼接后再用 `resolve()` + `is_relative_to()` 复核目录；导入分支的 `JSONDecodeError` / 通用异常改为脱敏文案并 `logger.exception` 记录 |
| 2 | ✅ 已修 | `VectorMemoryStore` 增加类级兜底 `_embedding_lock`，绕过 `__init__` 构造的实例也能安全走降级路径 |
| 3 | ✅ 已修 | 新增 `_QUERY_TOKEN_PATHS` 白名单，query 回退仅对两条 `session/end` 生效；已核对前端 `withCsrfQuery` 的调用点与之完全对应 |
| 4 | ✅ 已修 | `TriggerInteractionRequest.prompt` 加 `max_length=2000`，`trigger_character_id` 加 `max_length=64` |
| 5 | ✅ 已修 | `MAX_GROUP_CHARACTERS = 8`，`character_ids` 加 `max_length`；`player_id` / `player_name` / `group_name` 补长度上限 |
| 6 | ✅ 已修 | 9 处裸 `limit`/`offset` 改为 `Query(ge=..., le=...)`；`run-due` 因在请求内同步执行 LLM，单独收紧到 `le=50` |
| 7 | ✅ 已修 | 用户不存在时走 `_burn_password_hash_time` 恒定开销路径；新增按用户名的失败节流（15 分钟窗口 / 10 次 → 429），成功登录清零 |
| 8 | ✅ 已修 | `MAX_BATCH_RELATIONSHIPS = 200`，超限返回 400 |
| 9 | ✅ 已修 | 新增 `body_size_limit_middleware` 按 `Content-Length` 前置 413；配置项 `max_request_body_bytes` 默认 32 MB（高于最大的 STT 25 MB 限制）。chunked 传输仍需网关兜底，已在配置注释中标注 |
| 10 | ✅ 已修 | `vite.config.js` 回退到 8001，与全部文档一致 |
| 11 | ✅ 已修 | CSRF 与限流的路径判断抽为 `csrf.is_protected_path()`，覆盖 `/api/` 与 `/admin/` 两个前缀；`/health` `/ready` 保持开放 |
| 12 | ✅ 已修 | `character_admin` / `relationship` / `event_admin` 的 500 类响应全部脱敏 + `logger.exception`；角色卡创建/更新单独捕获 `ValidationError` 以保留对**请求方自己提交数据**的校验反馈 |
| 13 | ✅ 已修 | `dialogue.py` 的 `print` 改为模块 logger |
| 16 | ✅ 已修 | 两处 `AvatarUrlRequest.url` 加 `max_length=2048` |
| 20 | ✅ 已修 | `_raise_service_error` 返回类型标注为 `NoReturn` |
| 14 | ⏸ 未改 | GET 带写副作用（`_close_idle_sessions`）是既有架构选择，改成显式清理需要动前端调用时序，建议单独排期 |
| 15 | ⏸ 未改 | 需要部署侧配合（uvicorn `--proxy-headers` / `--forwarded-allow-ips`），非代码改动 |
| 17 | ⏸ 未改 | 收紧用户名字符集会影响存量账号，需要迁移方案 |
| 18 | ⏸ 未改 | **有意不做**：端口白名单会拒绝非标端口上的合法图片地址，且会让现有安全测试 `test_avatar_downloader_rejects_...:8001` 在到达 IP 校验前就短路，改变其断言意图。当前 IP 层防护已足够 |
| 19 | ⏸ 未改 | 仅在头像被用于 `<img src>` 之外的场景才需重新评估，现状无风险 |

### 新增回归测试

- `tests/test_security_fixes.py`：路径穿越 ID 拒绝（6 种变体）、导入异常不回显文件内容、未知用户名的恒定开销路径、登录节流与按账号隔离、成功登录清零计数、群聊人数上限、`prompt` 长度上限、批量关系上限、分页边界声明
- `tests/test_csrf.py`：两条 beacon 路径接受 query token、其它写接口拒绝 query token、beacon 路径的 token 不匹配仍拒绝、`/admin/` 前缀受保护、健康检查不受保护
- `tests/test_developer_experience.py`：超大 `Content-Length` 返回 413（已通过临时禁用中间件验证该测试确实会失败，不是空转）

---

## 第一轮 🔴 的收尾（后续补做，测试 806 passed）

### 第一轮 #1 — 事件批次提交失败误报成功

复查发现主修复**已在工作区落地但无测试守护**：`orchestrator.py` 的 `except Exception` 现在会在 `"turn" in turn_holder` 时重新抛出，不再把已进入提交阶段的失败降级为"无事件结果"。群聊侧 `multi_character_orchestrator.py:704-716` 本就没有包裹 `except`，异常正常传播。

本次补做两项：

1. **清理路径不再掩盖原始异常**（[orchestrator.py:1074](src/memoria/core/orchestrator.py#L1074)、[multi_character_orchestrator.py:442](src/memoria/core/multi_character_orchestrator.py#L442)）
   两处 `except Exception as exc: repository.fail_dialogue_turn(...); raise` 中，`fail_dialogue_turn` 自身要写库——而触发这条路径的往往正是"DB 写不进去"。它一旦抛出，原始异常被顶替，且后面的 `raise` **永远不会执行**，调用方看到的是误导性的清理错误。现改为包裹 `try/except` + `logger.exception`，原始异常始终向上传播。
2. **补齐回归测试**（`tests/test_orchestrator.py`）
   - `test_event_batch_commit_failure_raises`：模拟 `_commit_planned_batch` 先调 factory 填充 `turn_holder`、再提交失败，断言异常上抛、不走非事件提交路径、且租约被显式标记失败
   - `test_lease_cleanup_failure_does_not_mask_original_error`：断言清理失败时调用方仍看到原始异常

   两条均已通过**临时回退修复**验证会真实失败，不是空转。

### 第一轮 #2 — 跨用户记忆泄露

查询侧（token 精确匹配 + LIKE 通配符转义 + JOIN `session.player_id`）此前已修，但仍有一条活的越权路径：

- [orchestrator.py:327-339](src/memoria/core/orchestrator.py#L327) 的 `_get_character_group_memories_for_player` 有一个 `except TypeError` 兼容回退，会改调**不带 `owner_user_id`** 的版本。签名不匹配会走到它，函数内部任何 `TypeError` 同样会走到它——两种情况都静默返回跨用户群体记忆。已删除该回退。
- [`get_character_group_memories`](src/memoria/db/repository/sessions_and_messages.py#L1080) 的 `owner_user_id` 由"可选、缺省则全库扫描"改为**必填的关键字参数**，空值抛 `ValueError`。租户限定不能有默认值——任何未限定的调用现在会直接 `TypeError` 失败，而不是静默返回别人的数据。函数体也随之简化（不再需要 `table_clause`/`prefix` 的动态拼接分支）。

测试更新：`test_core.py` 中两条依赖旧的未限定行为的用例改为先建会话再按租户查询；新增 `test_get_character_group_memories_requires_owner`；`test_relation_state_like_match` 原本只断言"结果非空"（对子串误命中根本无效），改为真实构造 `char_xy` 干扰数据后断言 `char_x` 不命中它。

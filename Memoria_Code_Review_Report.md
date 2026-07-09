# Memoria 项目代码审查报告

## 一、后端问题

### P0-1 Session结束后仍可继续对话

位置：
- `src/memoria/core/orchestrator.py`

问题：
- `run_dialogue_turn()` 只检查 session 是否存在。
- 未检查 `session.status == ended`。

影响：
- 已结束会话继续写入消息。
- session summary 与真实聊天不一致。
- 破坏 session 生命周期边界。

修复：
```python
if session["status"] == "ended":
    raise ValueError("会话已经结束")
```

---

### P0-2 Session summary 状态设计不完善

问题：
- session ended 与 summary 生成绑定。
- summary 生成失败后无法恢复。

建议：
增加 summary 状态：

```
pending
generating
completed
failed
```

---

### P1-3 SQLite并发风险

问题：
- 使用 SQLite WAL。
- 多请求写入时可能出现 database locked。

建议：

```python
sqlite3.connect(
    database,
    timeout=30,
    check_same_thread=False
)
```

长期建议迁移 PostgreSQL。

---

### P1-4 长期记忆缺少去重

问题：
- 已实现相似度检测。
- 但保存长期记忆时没有调用。

影响：
- 相同事实重复保存。

建议：
保存前调用 dedup。

---

### P1-5 事件执行失败无法回滚

问题：
流程：

```
更新状态
保存消息
执行事件
```

事件失败会导致数据不一致。

建议：
使用数据库事务。

---

## 二、前端问题

---

# P0-1 React StrictMode导致重复创建Session

位置：

`SingleChat.jsx`

问题：

React18 StrictMode会执行两次effect。

可能：

```
打开聊天
 -> 创建session A
 -> 创建session B
```

修复：

```javascript
const initialized = useRef(false)
```

防重复初始化。

---

# P0-2 组件卸载自动结束Session

问题：

当前逻辑：

```
组件卸载
=
结束聊天
```

错误。

卸载可能由：

- React StrictMode
- 热更新
- 路由切换

触发。

建议：

只有用户主动退出时调用 endSession。

---

# P0-3 三套聊天逻辑重复

当前：

```
SingleChat
MultiRoom
ChatRoom
```

三个地方维护聊天状态。

问题：

- bug需要修改多个地方。
- session逻辑容易不一致。

建议：

统一：

```
ChatRoom
 |
 +-- SingleMode
 +-- MultiMode
```

---

# P1-4 Token放URL参数

问题：

例如：

```
/api/user/me?token=xxxx
```

风险：

- nginx日志泄漏
- 浏览器历史泄漏

建议：

使用：

```
Authorization: Bearer token
```

---

# P1-5 历史分页offset异常

问题：

发现：

```
historyOffset=-20
```

分页offset通常应该：

```
0
20
40
```

建议修改。

---

# P1-6 消息发送存在竞态

问题：

用户连续点击发送：

```
request1
request2
request3
```

可能造成：

消息乱序。

建议：

发送期间禁用按钮。

---

# P1-7 API请求没有取消机制

问题：

快速切换页面：

旧请求可能覆盖新状态。

建议：

使用：

```
AbortController
```

---

# P1-8 群聊角色加载N+1请求

问题：

加载100角色：

```
1 + 100 HTTP请求
```

建议：

后端提供批量接口。

---

# P2-9 localStorage保存Token风险

问题：

XSS可以读取token。

建议：

使用：

```
HttpOnly Cookie
```

---

# P2-10 消息缺少唯一ID

问题：

消息只有：

```
role
content
```

没有id。

影响：

React列表渲染可能错乱。

建议：

增加：

```
message_id
created_at
character_id
```

---

# P2-11 刷新页面无法恢复聊天

问题：

刷新：

```
messages清空
session丢失
```

建议：

保存最近session或者提供：

```
GET latest-session
```

---

# 三、架构优化建议

## 当前问题

```
Page
 |
State
 |
API
```

状态分散。

---

## 推荐结构

```
src

api/
  dialogue.ts

stores/
  sessionStore.ts
  messageStore.ts
  characterStore.ts

components/
  ChatRoom/
  MessageList/

pages/
  ChatRoom.tsx
```

---

# 四、修复优先级

|等级|问题|
|-|-|
|P0|Session生命周期|
|P0|StrictMode重复创建session|
|P0|聊天逻辑统一|
|P1|SQLite并发|
|P1|历史分页|
|P1|消息竞态|
|P1|Token安全|
|P2|状态管理|
|P2|消息模型|
|P2|资源释放|

---

# 总结

Memoria 当前已经具备：

- 角色系统
- Session系统
- 记忆系统
- 事件系统
- 单聊/群聊

主要问题集中在：

1. 状态生命周期
2. 数据一致性
3. 前后端模型统一
4. 从Demo向产品化迁移

下一阶段建议：

```
SessionManager统一
+
Memory Pipeline重构
+
Frontend Store统一
+
数据库事务层
```

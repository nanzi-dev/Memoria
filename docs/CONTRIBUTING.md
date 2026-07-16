# 贡献指南

欢迎提交 Issue 和 Pull Request！

## 如何贡献

### 1. Fork 项目

```bash
git clone https://github.com/YOUR_USERNAME/Memoria.git
cd Memoria
```

### 2. 创建特性分支

```bash
git checkout -b feature/your-feature-name
```

### 3. 配置开发环境

后端（在仓库根目录运行）：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
PYTHONPATH=src uvicorn memoria.main:app --host 127.0.0.1 --port 8001
```

可编辑安装完成后通常不需要设置 `PYTHONPATH=src`；如果没有安装项目，运行 Uvicorn、脚本或临时检查命令时必须显式设置该环境变量。

前端：

```bash
cd web
npm install
npm test
npm run build
npm run dev
```

### 4. 提交代码

在提交代码前，请确保：

- 代码符合 PEP 8 规范
- 添加必要的注释和文档字符串
- 测试所有相关功能
- 更新相关文档
- UI 改动附带桌面端和移动端截图
- API、行为或配置变更同步更新相应 `docs/` 文档

**代码风格示例：**
```python
def calculate_affinity_change(
    player_message: str,
    character_mood: str,
    current_affinity: float
) -> float:
    """
    计算好感度变化值

    Args:
        player_message: 玩家消息内容
        character_mood: 角色当前情绪
        current_affinity: 当前好感度

    Returns:
        float: 好感度变化值（-10 ~ +10）

    Examples:
        >>> calculate_affinity_change("你真可爱", "开心", 50.0)
        5.0
    """
    pass
```

### 5. 核对实现事实

编写或更新文档时，按以下顺序核对事实，避免复制过时示例：

1. 运行中服务生成的 OpenAPI 文档，确认实际端点、请求和响应。
2. `src/memoria/core/config.py`，确认环境变量、默认值和运行时配置来源。
3. API 使用的 Pydantic schema 及请求/响应模型，确认字段、类型和约束。

描述群聊行为时必须区分玩家轮次与自主脉冲。玩家发起的轮次使用请求生成、幂等和 `max_responses` 等轮次语义；普通/事件自主脉冲使用各自的触发条件、冷却、预算和每次消息上限。不要把两条执行路径的配置、限制或调用时序混写。

### 6. 运行测试

后端：

```bash
pytest
pytest tests/test_core.py
bash scripts/run_tests.sh
```

前端：

```bash
cd web
npm test
npm run build
```

根据改动范围运行相关测试；提交 PR 时记录实际执行的命令和结果。只改文档时至少检查 Markdown diff 和 `git diff --check`。

### 7. 提交 Pull Request

```bash
git add <changed-files>
git commit -m "feat: 添加 XXX 功能"
git push origin feature/your-feature-name
# 在 GitHub 上创建 Pull Request
```

请显式暂存本次修改的文件，不要使用 `git add .`，以免把其他工作区改动带入提交。前端/UI 变更应在 PR 中附截图；API、行为或配置变更应说明同步更新了哪些文档。

---

## Commit 消息规范

使用语义化提交消息（Conventional Commits）：

提交主题行应少于 72 个字符，并准确描述单一改动。

| 类型 | 说明 |
|------|------|
| `feat:` | 新增功能 |
| `fix:` | 修复 Bug |
| `docs:` | 文档更新 |
| `style:` | 代码格式调整（不影响功能）|
| `refactor:` | 代码重构 |
| `perf:` | 性能优化 |
| `test:` | 添加测试 |
| `chore:` | 构建/工具链更新 |

**示例：**
```
feat: 添加多角色对话支持
fix: 修复向量检索返回空结果的问题
docs: 更新 API 文档中的事件系统说明
```

---

## 代码审查标准

**必须满足：**
- 功能完整，无明显 Bug
- 代码可读性强，注释充分
- 符合现有架构和设计模式
- 不引入安全风险

**推荐满足：**
- 有单元测试覆盖
- 性能无明显下降
- 兼容现有 API

---

## 项目结构约定

- 源代码放在 `src/memoria/` 下
- API 端点放在 `src/memoria/api/`
- 核心逻辑放在 `src/memoria/core/`
- 数据库操作放在 `src/memoria/db/`
- 角色卡 JSON 放在 `src/memoria/characters/`
- 测试放在 `tests/`
- 文档放在 `docs/`

## 需要帮助？

- 提交 Issue 描述问题或建议
- 在 Issue 或 PR 中参与讨论
- 阅读现有代码和注释

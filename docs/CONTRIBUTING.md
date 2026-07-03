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

### 3. 提交代码

在提交代码前，请确保：

- 代码符合 PEP 8 规范
- 添加必要的注释和文档字符串
- 测试所有相关功能
- 更新相关文档

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

### 4. 运行测试

```bash
pip install -e ".[dev]"
PYTHONPATH=src pytest tests/ -v
```

### 5. 提交 Pull Request

```bash
git add .
git commit -m "feat: 添加 XXX 功能"
git push origin feature/your-feature-name
# 在 GitHub 上创建 Pull Request
```

---

## Commit 消息规范

使用语义化提交消息（Conventional Commits）：

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

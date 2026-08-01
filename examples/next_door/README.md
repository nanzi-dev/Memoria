# 隔壁寝室

这是 Memoria 的日常聊天示例模块。没有案件、没有谜题、没有任务——就是大学校园里认识新朋友、一起吃饭聊天的日常。

你是一名大二转学生，刚搬进宿舍楼，隔壁寝室有四个性格迥异的同学：热情到第一天就拉你去干饭的陈大壮、冷幽默体质的图书馆幽灵林小溪、把所有事都变成比赛的王奔奔、以及走到哪画到哪的迷糊少女苏糖。

模块包含：

- 1 张玩家角色卡。
- 4 张 NPC 角色卡。
- 10 条关系（NPC 之间 6 条 + 玩家与 NPC 之间 4 条）。
- 10 个社交日常事件（干饭邀请、推书、打球挑战、深夜夜宵、卧谈会等）。
- 3 个知识库和 3 篇 Markdown 文档，覆盖校园地理、觅食指南和校园文化。
- 1 个群聊线程和 8 道检索评测问题。

## 播种

```bash
python scripts/seed_next_door_demo.py --password 'a1008611'
```

也可以先设置 `MEMORIA_DEMO_PASSWORD`。账户已存在时不会修改密码。

```bash
python scripts/seed_next_door_demo.py --skip-knowledge-index
```

需要重建时使用 `--reset-module`：

```bash
python scripts/seed_next_door_demo.py --reset-module --password '<password>'
```

## 别想着通关，想着交朋友

这个模块没有通关条件。随便聊，聊什么都可以。

推荐的开场白见 [WALKTHROUGH.md](WALKTHROUGH.md)，但那只是参考——你可以直接跟他们聊任何事。

模块结构和评测数据可通过以下测试验证：

```bash
.venv/bin/pytest -q tests/test_story_module.py
```

#!/usr/bin/env python3
"""
命令行聊天界面 (CLI Chat)

用途：
- 提供简单的命令行交互界面，用于测试和演示对话系统
- 支持单角色和多角色对话模式
- 方便开发者快速验证系统功能

功能特性：
- 🎭 单角色/多角色对话模式
- 💬 流畅的对话体验
- 📊 实时状态显示
- 💾 会话历史查看
- 🎉 事件触发提醒
- 📝 自动会话摘要
- 🤝 角色间互动支持
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

import logging
import time
from typing import Optional
from datetime import datetime, timezone

from app.core import character_loader, orchestrator
from app.core.multi_character_orchestrator import (
    start_multi_character_session,
    process_multi_character_turn,
    MultiCharacterOrchestrator
)
from app.db import repository

# 配置日志
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)


# =========================
# 配置选项
# =========================
class ChatConfig:
    """聊天配置"""
    show_affinity_changes = True  # 是否显示好感度变化
    show_timestamps = False       # 是否显示时间戳
    auto_save_interval = 5        # 自动提醒保存的回合数（0=禁用）
    enable_typing_effect = False  # 是否启用打字机效果
    max_history_display = 10      # 历史记录最大显示条数
    history_offset = 0            # 历史记录偏移量（用于分页）


# =========================
# 颜色输出（终端美化）
# =========================
class Colors:
    """ANSI 颜色代码"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # 前景色
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # 背景色
    BG_BLACK = "\033[40m"
    BG_BLUE = "\033[44m"


def colored(text: str, color: str = "") -> str:
    """为文本添加颜色"""
    if not color:
        return text
    return f"{color}{text}{Colors.RESET}"


def clear_screen():
    """清屏"""
    os.system('clear' if os.name != 'nt' else 'cls')


def print_banner():
    """打印欢迎横幅"""
    banner = """
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║           🎭 Memoria - 角色记忆对话系统 🎭              ║
║                                                          ║
║               命令行聊天界面 (CLI Chat)                 ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """
    print(colored(banner, Colors.CYAN + Colors.BOLD))


def print_help(is_multi_character: bool = False):
    """打印帮助信息"""
    help_text = """
╔══════════════════════════════════════════════════════════╗
║                     📖 命令帮助                          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  💬 对话命令：                                           ║
║     • 直接输入文本 - 与角色对话                          ║"""
    
    if is_multi_character:
        help_text += """
║     • interact / 互动  - 触发角色间互动                 ║
║     • participants / 参与者 - 查看所有参与角色          ║
║     • toggle:discussion - 切换讨论模式                  ║"""
    
    help_text += """
║                                                          ║
║  🔧 功能命令：                                           ║
║     • help / 帮助      - 显示此帮助信息                  ║
║     • status / 状态    - 查看角色当前状态                ║
║     • history / 历史   - 查看所有会话的历史记录          ║
║       · history:more   - 查看下一页历史                  ║
║       · history:prev   - 查看上一页历史                  ║
║       · history:all    - 查看所有历史                    ║
║       · history:50     - 查看最近50条                    ║
║     • session / 本次   - 查看当前会话的对话记录          ║
║     • stats / 统计     - 显示会话统计信息                ║
║     • clear / 清屏     - 清除屏幕                        ║
║     • quit / exit      - 结束对话并保存                  ║
║                                                          ║
║  ⚙️  设置命令：                                          ║
║     • toggle:affinity  - 切换好感度显示                  ║
║     • toggle:timestamp - 切换时间戳显示                  ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """
    print(colored(help_text, Colors.CYAN))


def print_separator(char: str = "─", length: int = 60):
    """打印分隔线"""
    print(colored(char * length, Colors.DIM))


# =========================
# 角色选择
# =========================
def select_dialogue_mode() -> str:
    """选择对话模式"""
    print(colored("\n🎮 选择对话模式：", Colors.CYAN + Colors.BOLD))
    print_separator()
    print(f"{colored('[1]', Colors.CYAN)} {colored('单角色对话', Colors.WHITE)} - 与一个NPC一对一交流")
    print(f"{colored('[2]', Colors.CYAN)} {colored('多角色对话', Colors.WHITE)} - 与2个或更多NPC群聊")
    print(f"{colored('[0]', Colors.CYAN)} {colored('退出', Colors.DIM)}")
    print_separator()
    
    while True:
        choice = input(colored("请选择模式（1=单角色，2=多角色）: ", Colors.GREEN))
        
        if choice.strip() == "0":
            return "exit"
        elif choice.strip() == "1":
            return "single"
        elif choice.strip() == "2":
            return "multi"
        else:
            print(colored("❌ 请输入 1 或 2", Colors.RED))


def select_character() -> Optional[str]:
    """让用户选择一个角色"""
    try:
        character_ids = character_loader.list_character_ids()
        
        if not character_ids:
            print(colored("\n❌ 没有找到任何角色卡！", Colors.RED))
            print(colored("   请确保 app/characters/ 目录下有角色 JSON 文件", Colors.YELLOW))
            return None
        
        print(colored("\n📋 可用角色列表：", Colors.GREEN + Colors.BOLD))
        print_separator()
        
        # 显示角色列表
        for idx, cid in enumerate(character_ids, 1):
            try:
                card = character_loader.load_character_card(cid)
                display_name = card.meta.display_name
                identity_summary = card.identity.core_identity_summary[:50]
                
                print(f"{colored(f'[{idx}]', Colors.CYAN)} "
                      f"{colored(display_name, Colors.YELLOW + Colors.BOLD)} "
                      f"{colored(f'({cid})', Colors.DIM)}")
                print(f"    {colored(identity_summary, Colors.WHITE)}...")
                
            except Exception as e:
                logger.warning(f"加载角色卡 {cid} 失败: {e}")
                print(f"{colored(f'[{idx}]', Colors.CYAN)} "
                      f"{colored(cid, Colors.RED)} {colored('(加载失败)', Colors.RED)}")
        
        print_separator()
        
        # 用户选择
        while True:
            try:
                choice = input(colored("\n请选择角色编号（输入 0 退出）: ", Colors.GREEN))
                
                if not choice.strip():
                    continue
                
                choice_num = int(choice)
                
                if choice_num == 0:
                    return None
                
                if 1 <= choice_num <= len(character_ids):
                    selected_id = character_ids[choice_num - 1]
                    card = character_loader.load_character_card(selected_id)
                    
                    print(colored(f"\n✓ 已选择角色: {card.meta.display_name}", Colors.GREEN))
                    return selected_id
                else:
                    print(colored("❌ 无效的编号，请重新输入", Colors.RED))
                    
            except ValueError:
                print(colored("❌ 请输入有效的数字", Colors.RED))
            except KeyboardInterrupt:
                print(colored("\n\n👋 已取消", Colors.YELLOW))
                return None
                
    except Exception as e:
        logger.error(f"选择角色时出错: {e}", exc_info=True)
        print(colored(f"\n❌ 发生错误: {e}", Colors.RED))
        return None


def select_multiple_characters(min_count: int = 2) -> Optional[list[str]]:
    """让用户选择多个角色"""
    try:
        character_ids = character_loader.list_character_ids()
        
        if not character_ids:
            print(colored("\n❌ 没有找到任何角色卡！", Colors.RED))
            return None
        
        if len(character_ids) < min_count:
            print(colored(f"\n❌ 角色数量不足！多角色对话至少需要 {min_count} 个角色", Colors.RED))
            return None
        
        print(colored(f"\n📋 可用角色列表（至少选择 {min_count} 个）：", Colors.GREEN + Colors.BOLD))
        print_separator()
        
        # 显示角色列表
        for idx, cid in enumerate(character_ids, 1):
            try:
                card = character_loader.load_character_card(cid)
                display_name = card.meta.display_name
                identity_summary = card.identity.core_identity_summary[:50]
                
                print(f"{colored(f'[{idx}]', Colors.CYAN)} "
                      f"{colored(display_name, Colors.YELLOW + Colors.BOLD)} "
                      f"{colored(f'({cid})', Colors.DIM)}")
                print(f"    {colored(identity_summary, Colors.WHITE)}...")
                
            except Exception as e:
                logger.warning(f"加载角色卡 {cid} 失败: {e}")
                print(f"{colored(f'[{idx}]', Colors.CYAN)} "
                      f"{colored(cid, Colors.RED)} {colored('(加载失败)', Colors.RED)}")
        
        print_separator()
        print(colored(f"💡 输入多个编号，用空格或逗号分隔，例如: 1 2 3 或 1,2,3", Colors.YELLOW))
        
        # 用户选择
        while True:
            try:
                choice = input(colored(f"\n请选择角色编号（输入 0 退出）: ", Colors.GREEN))
                
                if not choice.strip():
                    continue
                
                if choice.strip() == "0":
                    return None
                
                # 解析输入（支持空格和逗号分隔）
                choice_str = choice.replace(',', ' ')
                choice_nums = [int(x) for x in choice_str.split() if x.strip()]
                
                if len(choice_nums) < min_count:
                    print(colored(f"❌ 至少需要选择 {min_count} 个角色", Colors.RED))
                    continue
                
                # 验证编号有效性
                invalid_nums = [n for n in choice_nums if n < 1 or n > len(character_ids)]
                if invalid_nums:
                    print(colored(f"❌ 无效的编号: {invalid_nums}", Colors.RED))
                    continue
                
                # 检查重复
                if len(choice_nums) != len(set(choice_nums)):
                    print(colored("❌ 存在重复的编号，请重新输入", Colors.RED))
                    continue
                
                # 获取选中的角色
                selected_ids = [character_ids[n - 1] for n in choice_nums]
                
                # 确认选择
                print(colored("\n✓ 已选择以下角色:", Colors.GREEN))
                for cid in selected_ids:
                    card = character_loader.load_character_card(cid)
                    print(f"  • {colored(card.meta.display_name, Colors.YELLOW)} ({cid})")
                
                confirm = input(colored("\n确认选择？(y/n): ", Colors.GREEN))
                if confirm.lower() in ['y', 'yes', '是', '']:
                    return selected_ids
                else:
                    print(colored("请重新选择...", Colors.YELLOW))
                    
            except ValueError:
                print(colored("❌ 请输入有效的数字", Colors.RED))
            except KeyboardInterrupt:
                print(colored("\n\n👋 已取消", Colors.YELLOW))
                return None
                
    except Exception as e:
        logger.error(f"选择角色时出错: {e}", exc_info=True)
        print(colored(f"\n❌ 发生错误: {e}", Colors.RED))
        return None


# =========================
# 玩家信息输入
# =========================
def get_player_info() -> tuple[str, str]:
    """获取玩家 ID 和名称"""
    print(colored("\n👤 玩家信息设置", Colors.CYAN + Colors.BOLD))
    print_separator()
    
    player_id = input(colored("请输入玩家 ID（用于区分不同玩家，默认: player_001）: ", Colors.GREEN))
    if not player_id.strip():
        player_id = "player_001"
    
    player_name = input(colored("请输入玩家昵称（角色会这样称呼你，默认: 旅行者）: ", Colors.GREEN))
    if not player_name.strip():
        player_name = "旅行者"
    
    print(colored(f"\n✓ 玩家 ID: {player_id}", Colors.GREEN))
    print(colored(f"✓ 玩家昵称: {player_name}", Colors.GREEN))
    
    return player_id, player_name


# =========================
# 显示角色状态
# =========================
def show_character_state(character_id: str, player_id: str):
    """显示角色当前状态"""
    try:
        card = character_loader.load_character_card(character_id)
        runtime_state = repository.get_runtime_state(character_id, player_id, card)
        
        affinity = runtime_state.get("affection_level", 0)
        trust = runtime_state.get("trust_level", 0)
        mood = runtime_state.get("current_mood", "neutral")
        
        print(colored("\n📊 角色状态：", Colors.CYAN + Colors.BOLD))
        print_separator("─", 40)
        
        # 好感度（带颜色）
        affinity_color = Colors.GREEN if affinity >= 30 else Colors.YELLOW if affinity >= 0 else Colors.RED
        print(f"  {colored('❤️  好感度:', Colors.WHITE)} {colored(f'{affinity:+.0f}', affinity_color)}")
        
        # 信任度
        trust_color = Colors.GREEN if trust >= 50 else Colors.YELLOW if trust >= 20 else Colors.RED
        print(f"  {colored('🤝 信任度:', Colors.WHITE)} {colored(f'{trust:.0f}', trust_color)}")
        
        # 情绪
        mood_emoji = {
            "happy": "😊", "sad": "😢", "angry": "😠", "neutral": "😐",
            "excited": "🤩", "anxious": "😰", "calm": "😌", "surprised": "😲"
        }
        print(f"  {colored('😊 情绪:', Colors.WHITE)} {mood_emoji.get(mood, '😐')} {colored(mood, Colors.MAGENTA)}")
        
        print_separator("─", 40)
        
    except Exception as e:
        logger.error(f"显示角色状态失败: {e}", exc_info=True)


# =========================
# 显示历史摘要
# =========================
def show_recent_summaries(character_id: str, player_id: str):
    """显示最近的会话摘要"""
    try:
        summaries = repository.get_recent_summaries(character_id, player_id, limit=3)
        
        if not summaries:
            print(colored("\n💭 这是你们第一次见面", Colors.DIM))
            return
        
        print(colored("\n💭 过往回忆（最近3次会话摘要）：", Colors.CYAN + Colors.BOLD))
        print_separator()
        
        for idx, summary in enumerate(summaries, 1):
            summary_text = summary["summary_text"]
            message_count = summary.get("message_count", 0)
            created_at = summary.get("created_at", "")
            
            # 格式化时间
            time_str = ""
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            
            print(f"{colored(f'[{idx}]', Colors.CYAN)} "
                  f"{colored(summary_text[:80], Colors.WHITE)}...")
            print(f"    {colored(f'({message_count} 条消息)', Colors.DIM)}"
                  + (f" {colored(time_str, Colors.DIM)}" if time_str else ""))
        
        print_separator()
        
    except Exception as e:
        logger.warning(f"显示历史摘要失败: {e}")


# =========================
# 显示当前会话历史
# =========================
def show_session_history(session_id: str, character_name: str, player_name: str, limit: int = 10):
    """显示当前会话的对话历史"""
    try:
        history = repository.get_short_term_history(session_id, limit_turns=limit)
        
        if not history:
            print(colored("\n📜 本次会话暂无对话记录", Colors.DIM))
            return
        
        print(colored(f"\n📜 本次会话的最近 {len(history)} 条消息：", Colors.CYAN + Colors.BOLD))
        print_separator()
        
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            
            if role == "user":
                print(colored(f"{player_name}: ", Colors.GREEN) + content)
            else:
                print(colored(f"{character_name}: ", Colors.YELLOW) + content)
        
        print_separator()
        
    except Exception as e:
        logger.warning(f"显示当前会话历史失败: {e}")
        print(colored(f"❌ 显示历史失败: {e}", Colors.RED))


# =========================
# 显示跨会话历史
# =========================
# =========================
# 显示跨会话历史
# =========================
def show_chat_history(character_id: str, player_id: str, character_name: str, 
                     player_name: str, limit: int = 20, offset: int = 0):
    """显示跨所有会话的对话历史
    
    Args:
        offset: 偏移量，用于分页（0=第一页，20=第二页，40=第三页...）
    """
    try:
        # 跨会话查询所有历史消息
        messages, has_more = repository.get_messages_by_player_and_character(
            character_id=character_id,
            player_id=player_id,
            offset=offset,
            limit=limit
        )
        
        if not messages:
            if offset == 0:
                print(colored("\n📜 暂无对话记录", Colors.DIM))
            else:
                print(colored("\n📜 没有更多历史记录了", Colors.DIM))
            return False  # 返回 False 表示没有更多数据
        
        # 反转顺序（从旧到新显示）
        messages.reverse()
        
        page_num = (offset // limit) + 1
        print(colored(f"\n📜 跨所有会话的历史记录（第 {page_num} 页，共 {len(messages)} 条）：", 
                     Colors.CYAN + Colors.BOLD))
        if has_more:
            print(colored(f"   （还有更多历史记录）", Colors.DIM))
        print_separator()
        
        current_session = None
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            session_id = msg.get("session_id")
            created_at = msg.get("created_at", "")
            
            # 显示会话分隔
            if session_id != current_session:
                if current_session is not None:
                    print(colored("  " + "─" * 56, Colors.DIM))
                current_session = session_id
                
                # 格式化时间
                time_str = ""
                if created_at:
                    try:
                        dt = datetime.fromisoformat(created_at)
                        time_str = dt.strftime("%m-%d %H:%M")
                    except:
                        pass
                
                session_label = f"会话 {session_id[:8]}..."
                if time_str:
                    session_label += f" ({time_str})"
                print(colored(f"  [{session_label}]", Colors.CYAN + Colors.DIM))
            
            # 显示消息
            if role == "user":
                print(colored(f"{player_name}: ", Colors.GREEN) + content)
            else:
                print(colored(f"{character_name}: ", Colors.YELLOW) + content)
        
        print_separator()
        
        # 显示翻页提示
        if has_more:
            print(colored("💡 输入 'history:more' 或 'history:next' 查看下一页", Colors.YELLOW))
            print(colored("   输入 'history:prev' 返回上一页", Colors.YELLOW))
            print(colored("   输入 'history:all' 查看所有历史（可能较多）", Colors.YELLOW))
        elif offset > 0:
            print(colored("💡 已到最后一页，输入 'history:prev' 返回上一页", Colors.YELLOW))
        
        return has_more  # 返回是否有更多数据
        
    except Exception as e:
        logger.warning(f"显示对话历史失败: {e}")
        print(colored(f"❌ 显示历史失败: {e}", Colors.RED))
        return False


# =========================
# 显示会话统计
# =========================
def show_session_stats(session_id: str, character_id: str, player_id: str, turn_count: int):
    """显示会话统计信息"""
    try:
        history = repository.get_short_term_history(session_id, limit_turns=1000)
        card = character_loader.load_character_card(character_id)
        runtime_state = repository.get_runtime_state(character_id, player_id, card)
        
        message_count = len(history)
        user_messages = sum(1 for m in history if m["role"] == "user")
        assistant_messages = sum(1 for m in history if m["role"] == "assistant")
        
        # 计算平均消息长度
        avg_user_length = sum(len(m["content"]) for m in history if m["role"] == "user") / max(user_messages, 1)
        avg_assistant_length = sum(len(m["content"]) for m in history if m["role"] == "assistant") / max(assistant_messages, 1)
        
        print(colored("\n📊 会话统计：", Colors.CYAN + Colors.BOLD))
        print_separator("─", 40)
        print(f"  {colored('🔢 当前回合:', Colors.WHITE)} {turn_count}")
        print(f"  {colored('💬 总消息数:', Colors.WHITE)} {message_count}")
        print(f"  {colored('   玩家消息:', Colors.WHITE)} {user_messages} (平均 {avg_user_length:.0f} 字)")
        print(f"  {colored('   角色消息:', Colors.WHITE)} {assistant_messages} (平均 {avg_assistant_length:.0f} 字)")
        print(f"  {colored('❤️  好感度:', Colors.WHITE)} {runtime_state.get('affection_level', 0):+.0f}")
        print(f"  {colored('🤝 信任度:', Colors.WHITE)} {runtime_state.get('trust_level', 0):.0f}")
        print(f"  {colored('😊 当前情绪:', Colors.WHITE)} {runtime_state.get('current_mood', 'neutral')}")
        print_separator("─", 40)
        
    except Exception as e:
        logger.warning(f"显示会话统计失败: {e}")


# =========================
# 打字机效果
# =========================
def type_effect(text: str, delay: float = 0.03):
    """打字机效果输出"""
    for char in text:
        print(char, end='', flush=True)
        time.sleep(delay)
    print()  # 换行


# =========================
# 对话循环
# =========================
def chat_loop(session_id: str, character_id: str, player_id: str, player_name: str):
    """主对话循环"""
    config = ChatConfig()
    
    try:
        card = character_loader.load_character_card(character_id)
        character_name = card.meta.display_name
        
        print(colored(f"\n💬 开始对话（输入 'help' 查看命令帮助）", Colors.CYAN))
        print_separator("═", 60)
        
        turn_count = 0
        last_save_reminder = 0
        
        while True:
            try:
                # 自动保存提醒
                if config.auto_save_interval > 0 and turn_count > 0:
                    if (turn_count - last_save_reminder) >= config.auto_save_interval:
                        print(colored(f"\n💡 提示: 已进行 {turn_count} 回合对话，输入 'quit' 可保存并退出", 
                                    Colors.YELLOW + Colors.DIM))
                        last_save_reminder = turn_count
                
                # 显示回合数
                turn_count += 1
                turn_prefix = f"[回合 {turn_count}]"
                if config.show_timestamps:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    turn_prefix += f" {timestamp}"
                print(colored(f"\n{turn_prefix}", Colors.DIM))
                
                # 玩家输入
                user_input = input(colored(f"{player_name}: ", Colors.GREEN + Colors.BOLD))
                
                if not user_input.strip():
                    turn_count -= 1
                    continue
                
                # 命令处理
                cmd = user_input.lower().strip()
                
                # 退出命令
                if cmd in ["quit", "exit", "退出", "q"]:
                    print(colored("\n👋 准备结束对话...", Colors.YELLOW))
                    break
                
                # 帮助命令
                if cmd in ["help", "帮助", "h", "?"]:
                    print_help()
                    turn_count -= 1
                    continue
                
                # 状态命令
                if cmd in ["status", "状态", "s"]:
                    show_character_state(character_id, player_id)
                    turn_count -= 1
                    continue
                
                # 当前会话历史命令
                if cmd in ["session", "本次", "sess"]:
                    show_session_history(
                        session_id=session_id,
                        character_name=character_name, 
                        player_name=player_name,
                        limit=config.max_history_display
                    )
                    turn_count -= 1
                    continue
                
                # 跨会话历史命令（支持分页和扩展语法）
                if cmd.startswith("history"):
                    parts = cmd.split(":", 1)
                    
                    if len(parts) == 1 or parts[1] == "":
                        # 默认显示第一页
                        config.history_offset = 0
                        show_chat_history(
                            character_id=character_id,
                            player_id=player_id,
                            character_name=character_name, 
                            player_name=player_name,
                            limit=config.max_history_display * 2,
                            offset=config.history_offset
                        )
                    elif parts[1] in ["more", "next", "下一页", "n"]:
                        # 下一页
                        config.history_offset += config.max_history_display * 2
                        has_more = show_chat_history(
                            character_id=character_id,
                            player_id=player_id,
                            character_name=character_name, 
                            player_name=player_name,
                            limit=config.max_history_display * 2,
                            offset=config.history_offset
                        )
                        # 如果没有更多数据，回退偏移量
                        if not has_more and config.history_offset > 0:
                            config.history_offset -= config.max_history_display * 2
                    elif parts[1] in ["prev", "previous", "上一页", "p"]:
                        # 上一页
                        config.history_offset = max(0, config.history_offset - config.max_history_display * 2)
                        show_chat_history(
                            character_id=character_id,
                            player_id=player_id,
                            character_name=character_name, 
                            player_name=player_name,
                            limit=config.max_history_display * 2,
                            offset=config.history_offset
                        )
                    elif parts[1] in ["all", "全部", "a"]:
                        # 查看所有历史（最多500条）
                        config.history_offset = 0
                        print(colored("\n⚠️  正在加载所有历史记录，可能需要一些时间...", Colors.YELLOW))
                        show_chat_history(
                            character_id=character_id,
                            player_id=player_id,
                            character_name=character_name, 
                            player_name=player_name,
                            limit=500,  # 最多显示500条
                            offset=0
                        )
                    elif parts[1].isdigit():
                        # 指定数量：history:50
                        limit = int(parts[1])
                        if limit > 500:
                            print(colored("⚠️  最多只能查看 500 条记录", Colors.YELLOW))
                            limit = 500
                        config.history_offset = 0
                        show_chat_history(
                            character_id=character_id,
                            player_id=player_id,
                            character_name=character_name, 
                            player_name=player_name,
                            limit=limit,
                            offset=0
                        )
                    else:
                        print(colored(f"❌ 未知的历史命令: {cmd}", Colors.RED))
                        print(colored("   支持的命令:", Colors.YELLOW))
                        print(colored("   - history 或 history:1     (第一页)", Colors.DIM))
                        print(colored("   - history:more/next       (下一页)", Colors.DIM))
                        print(colored("   - history:prev/previous   (上一页)", Colors.DIM))
                        print(colored("   - history:all             (所有记录)", Colors.DIM))
                        print(colored("   - history:50              (指定数量)", Colors.DIM))
                    
                    turn_count -= 1
                    continue
                
                # 统计命令
                if cmd in ["stats", "统计", "info"]:
                    show_session_stats(session_id, character_id, player_id, turn_count - 1)
                    turn_count -= 1
                    continue
                
                # 清屏命令
                if cmd in ["clear", "cls", "清屏"]:
                    clear_screen()
                    print_banner()
                    print(colored(f"💬 与 {character_name} 的对话继续中...", Colors.CYAN))
                    turn_count -= 1
                    continue
                
                # 切换设置
                if cmd.startswith("toggle:"):
                    setting = cmd.split(":", 1)[1]
                    if setting == "affinity":
                        config.show_affinity_changes = not config.show_affinity_changes
                        status = "开启" if config.show_affinity_changes else "关闭"
                        print(colored(f"✓ 好感度显示已{status}", Colors.GREEN))
                    elif setting == "timestamp":
                        config.show_timestamps = not config.show_timestamps
                        status = "开启" if config.show_timestamps else "关闭"
                        print(colored(f"✓ 时间戳显示已{status}", Colors.GREEN))
                    elif setting == "typing":
                        config.enable_typing_effect = not config.enable_typing_effect
                        status = "开启" if config.enable_typing_effect else "关闭"
                        print(colored(f"✓ 打字机效果已{status}", Colors.GREEN))
                    else:
                        print(colored(f"❌ 未知设置: {setting}", Colors.RED))
                    turn_count -= 1
                    continue
                
                # 调用对话系统（显示等待提示）
                print(colored("  ⏳ 思考中...", Colors.DIM), end='\r')
                
                try:
                    result = orchestrator.run_dialogue_turn(session_id, user_input)
                except Exception as e:
                    logger.error(f"对话系统调用失败: {e}", exc_info=True)
                    print(colored(f"\n❌ 对话失败: {e}", Colors.RED))
                    print(colored("   请重试或输入 'quit' 退出", Colors.YELLOW))
                    turn_count -= 1
                    continue
                
                # 清除等待提示
                print(" " * 30, end='\r')
                
                # 显示角色回应
                dialogue = result.get("dialogue", "")
                action = result.get("action", "")
                affinity_delta = result.get("affinity_delta", 0)
                current_affinity = result.get("current_affinity", 0)
                current_mood = result.get("current_mood", "neutral")
                
                # NPC 对话（带动作）
                npc_name_colored = colored(f"{character_name}", Colors.YELLOW + Colors.BOLD)
                if action and action != "default":
                    action_colored = colored(f"[{action}]", Colors.MAGENTA)
                    npc_prefix = f"{npc_name_colored} {action_colored}: "
                else:
                    npc_prefix = f"{npc_name_colored}: "
                
                # 打字机效果或直接输出
                if config.enable_typing_effect:
                    print(npc_prefix, end='')
                    type_effect(dialogue, delay=0.02)
                else:
                    print(npc_prefix + dialogue)
                
                # 显示状态变化
                if config.show_affinity_changes:
                    changes = []
                    
                    if affinity_delta != 0:
                        delta_str = f"{affinity_delta:+.0f}"
                        delta_color = Colors.GREEN if affinity_delta > 0 else Colors.RED
                        changes.append(colored(f"好感度 {delta_str} (当前: {current_affinity:+.0f})", 
                                             delta_color))
                    
                    if changes:
                        print(colored(f"  [{' | '.join(changes)}]", Colors.DIM))
                
                # 事件通知
                event_notification = result.get("event_notification")
                if event_notification:
                    print(colored(f"\n🎉 事件触发: {event_notification}", Colors.MAGENTA + Colors.BOLD))
                
                triggered_events = result.get("triggered_events", [])
                if triggered_events:
                    for event_info in triggered_events:
                        event_name = event_info.get("event_name", "未知事件")
                        effects = event_info.get("effects", [])
                        print(colored(f"  ⚡ {event_name}", Colors.MAGENTA))
                        if effects:
                            for effect in effects[:3]:  # 最多显示3个效果
                                print(colored(f"     • {effect}", Colors.DIM))
                
            except KeyboardInterrupt:
                print(colored("\n\n⚠️  检测到中断信号", Colors.YELLOW))
                confirm = input(colored("确定要退出吗？(y/n): ", Colors.YELLOW))
                if confirm.lower() in ['y', 'yes', '是']:
                    break
                else:
                    print(colored("继续对话...", Colors.GREEN))
                    continue
                
            except Exception as e:
                logger.error(f"对话回合出错: {e}", exc_info=True)
                print(colored(f"\n❌ 发生错误: {e}", Colors.RED))
                print(colored("   继续下一回合...", Colors.YELLOW))
                turn_count -= 1
        
        print_separator("═", 60)
        
        # 结束会话
        print(colored("\n📝 正在生成会话摘要...", Colors.CYAN))
        
        try:
            from app.core.memory_extractor import summarize_session
            
            history = repository.get_short_term_history(session_id, limit_turns=1000)
            
            if len(history) > 2:  # 至少有实质对话才生成摘要
                summary_text = summarize_session(history)
                
                if summary_text:
                    # 保存摘要
                    repository.save_session_summary(
                        session_id=session_id,
                        character_id=character_id,
                        player_id=player_id,
                        summary_text=summary_text,
                        message_count=len(history)
                    )
                    
                    print(colored("\n💾 会话摘要：", Colors.GREEN + Colors.BOLD))
                    print_separator()
                    print(colored(summary_text, Colors.WHITE))
                    print_separator()
                else:
                    print(colored("⚠️  本次对话内容较少，未生成摘要", Colors.YELLOW))
            else:
                print(colored("⚠️  对话内容不足，未生成摘要", Colors.YELLOW))
            
            # 标记会话结束
            repository.end_session(session_id)
            
            print(colored(f"\n✓ 会话已结束（共 {turn_count - 1} 回合）", Colors.GREEN))
            
        except Exception as e:
            logger.warning(f"生成会话摘要失败: {e}", exc_info=True)
            print(colored("⚠️  会话摘要生成失败，但对话记录已保存", Colors.YELLOW))
        
        # 显示最终状态
        show_character_state(character_id, player_id)
        
    except Exception as e:
        logger.error(f"对话循环出错: {e}", exc_info=True)
        print(colored(f"\n❌ 对话系统错误: {e}", Colors.RED))


# =========================
# 多角色对话循环
# =========================
def multi_character_chat_loop(session_id: str, character_ids: list[str], 
                               player_id: str, player_name: str, strategy_type: str = "hybrid",
                               discussion_mode: bool = False):
    """多角色对话循环"""
    config = ChatConfig()
    
    try:
        # 加载所有角色
        character_cards = {}
        for cid in character_ids:
            card = character_loader.load_character_card(cid)
            character_cards[cid] = card
        
        # 初始化编排器
        orchestrator = MultiCharacterOrchestrator(session_id, strategy_type=strategy_type)
        
        mode_text = "多角色讨论模式" if discussion_mode else "多角色群聊"
        print(colored(f"\n💬 {mode_text}开始（输入 'help' 查看命令帮助）", Colors.CYAN))
        print(colored(f"   发言策略: {strategy_type}", Colors.DIM))
        if discussion_mode:
            print(colored(f"   讨论模式已启用: 每轮最多3个角色发言", Colors.YELLOW))
        print_separator("═", 60)
        
        turn_count = 0
        last_save_reminder = 0
        
        while True:
            try:
                # 自动保存提醒
                if config.auto_save_interval > 0 and turn_count > 0:
                    if (turn_count - last_save_reminder) >= config.auto_save_interval:
                        print(colored(f"\n💡 提示: 已进行 {turn_count} 回合对话，输入 'quit' 可保存并退出", 
                                    Colors.YELLOW + Colors.DIM))
                        last_save_reminder = turn_count
                
                # 显示回合数
                turn_count += 1
                turn_prefix = f"[回合 {turn_count}]"
                if config.show_timestamps:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    turn_prefix += f" {timestamp}"
                print(colored(f"\n{turn_prefix}", Colors.DIM))
                
                # 玩家输入
                user_input = input(colored(f"{player_name}: ", Colors.GREEN + Colors.BOLD))
                
                if not user_input.strip():
                    turn_count -= 1
                    continue
                
                # 命令处理
                cmd = user_input.lower().strip()
                
                # 退出命令
                if cmd in ["quit", "exit", "退出", "q"]:
                    print(colored("\n👋 准备结束对话...", Colors.YELLOW))
                    break
                
                # 帮助命令
                if cmd in ["help", "帮助", "h", "?"]:
                    print_help(is_multi_character=True)
                    turn_count -= 1
                    continue
                
                # 切换讨论模式
                if cmd in ["toggle:discussion", "讨论模式"]:
                    discussion_mode = not discussion_mode
                    status = "开启" if discussion_mode else "关闭"
                    print(colored(f"✓ 讨论模式已{status}", Colors.GREEN))
                    if discussion_mode:
                        print(colored("   现在每轮最多3个角色会连续发言", Colors.YELLOW))
                    else:
                        print(colored("   现在每轮只有1个角色发言", Colors.YELLOW))
                    turn_count -= 1
                    continue
                
                # 查看参与者
                if cmd in ["participants", "参与者", "角色", "chars"]:
                    show_participants(session_id)
                    turn_count -= 1
                    continue
                
                # 触发角色互动
                if cmd in ["interact", "互动", "int"]:
                    print(colored("  ⏳ 角色思考中...", Colors.DIM), end='\r')
                    
                    try:
                        result = orchestrator.trigger_character_interaction()
                        print(" " * 30, end='\r')
                        
                        # 显示角色发言
                        character_id = result["character_id"]
                        character_name = result["character_name"]
                        dialogue = result["dialogue"]
                        action = result.get("action", "")
                        
                        npc_name_colored = colored(f"{character_name}", Colors.MAGENTA + Colors.BOLD)
                        if action and action != "default":
                            action_colored = colored(f"[{action}]", Colors.CYAN)
                            npc_prefix = f"{npc_name_colored} {action_colored}: "
                        else:
                            npc_prefix = f"{npc_name_colored}: "
                        
                        print(npc_prefix + dialogue)
                        
                    except Exception as e:
                        logger.error(f"角色互动失败: {e}", exc_info=True)
                        print(colored(f"\n❌ 互动失败: {e}", Colors.RED))
                    
                    turn_count -= 1
                    continue
                
                # 状态命令
                if cmd in ["status", "状态", "s"]:
                    show_all_character_states(character_ids, player_id)
                    turn_count -= 1
                    continue
                
                # 当前会话历史命令
                if cmd in ["session", "本次", "sess"]:
                    show_multi_character_session_history(
                        session_id=session_id,
                        player_name=player_name,
                        limit=config.max_history_display
                    )
                    turn_count -= 1
                    continue
                
                # 统计命令
                if cmd in ["stats", "统计", "info"]:
                    show_multi_character_session_stats(session_id, turn_count - 1)
                    turn_count -= 1
                    continue
                
                # 清屏命令
                if cmd in ["clear", "cls", "清屏"]:
                    clear_screen()
                    print_banner()
                    print(colored(f"💬 {mode_text}继续中...", Colors.CYAN))
                    turn_count -= 1
                    continue
                
                # 切换设置
                if cmd.startswith("toggle:"):
                    setting = cmd.split(":", 1)[1]
                    if setting == "affinity":
                        config.show_affinity_changes = not config.show_affinity_changes
                        status = "开启" if config.show_affinity_changes else "关闭"
                        print(colored(f"✓ 好感度显示已{status}", Colors.GREEN))
                    elif setting == "timestamp":
                        config.show_timestamps = not config.show_timestamps
                        status = "开启" if config.show_timestamps else "关闭"
                        print(colored(f"✓ 时间戳显示已{status}", Colors.GREEN))
                    else:
                        print(colored(f"❌ 未知设置: {setting}", Colors.RED))
                    turn_count -= 1
                    continue
                
                # 调用多角色对话系统
                print(colored("  ⏳ 角色思考中...", Colors.DIM), end='\r')
                
                try:
                    result = process_multi_character_turn(
                        session_id=session_id,
                        player_message=user_input,
                        strategy_type=strategy_type,
                        discussion_mode=discussion_mode,
                        max_responses=3
                    )
                except Exception as e:
                    logger.error(f"多角色对话失败: {e}", exc_info=True)
                    print(colored(f"\n❌ 对话失败: {e}", Colors.RED))
                    turn_count -= 1
                    continue
                
                # 清除等待提示
                print(" " * 30, end='\r')
                
                # 处理单个或多个回应
                responses = result if isinstance(result, list) else [result]
                
                for idx, response in enumerate(responses):
                    character_id = response["character_id"]
                    character_name = response["character_name"]
                    dialogue = response["dialogue"]
                    action = response.get("action", "")
                    affinity_delta = response.get("affinity_delta", 0)
                    current_affinity = response.get("current_affinity", 0)
                    
                    # NPC 对话（不同角色用不同颜色）
                    name_color = Colors.YELLOW if character_id == character_ids[0] else Colors.MAGENTA
                    npc_name_colored = colored(f"{character_name}", name_color + Colors.BOLD)
                    
                    if action and action != "default":
                        action_colored = colored(f"[{action}]", Colors.CYAN)
                        npc_prefix = f"{npc_name_colored} {action_colored}: "
                    else:
                        npc_prefix = f"{npc_name_colored}: "
                    
                    # 多个回应之间添加间隔
                    if idx > 0:
                        print()
                    
                    print(npc_prefix + dialogue)
                    
                    # 显示状态变化
                    if config.show_affinity_changes and affinity_delta != 0:
                        delta_str = f"{affinity_delta:+.0f}"
                        delta_color = Colors.GREEN if affinity_delta > 0 else Colors.RED
                        print(colored(f"  [{character_name} 好感度 {delta_str} (当前: {current_affinity:+.0f})]", 
                                    delta_color + Colors.DIM))
                
            except KeyboardInterrupt:
                print(colored("\n\n⚠️  检测到中断信号", Colors.YELLOW))
                confirm = input(colored("确定要退出吗？(y/n): ", Colors.YELLOW))
                if confirm.lower() in ['y', 'yes', '是']:
                    break
                else:
                    print(colored("继续对话...", Colors.GREEN))
                    continue
                
            except Exception as e:
                logger.error(f"对话回合出错: {e}", exc_info=True)
                print(colored(f"\n❌ 发生错误: {e}", Colors.RED))
                turn_count -= 1
        
        print_separator("═", 60)
        
        # 结束会话
        print(colored(f"\n✓ 会话已结束（共 {turn_count - 1} 回合）", Colors.GREEN))
        repository.end_session(session_id)
        
        # 显示最终状态
        print(colored("\n📊 最终状态：", Colors.CYAN + Colors.BOLD))
        show_all_character_states(character_ids, player_id)
        
    except Exception as e:
        logger.error(f"多角色对话循环出错: {e}", exc_info=True)
        print(colored(f"\n❌ 对话系统错误: {e}", Colors.RED))


def show_participants(session_id: str):
    """显示当前会话的所有参与者"""
    try:
        participants = repository.get_session_participants(session_id, only_active=True)
        
        print(colored("\n👥 当前参与角色：", Colors.CYAN + Colors.BOLD))
        print_separator()
        
        for idx, p in enumerate(participants, 1):
            char_id = p["character_id"]
            display_name = p["display_name"]
            speak_freq = p.get("speak_frequency", 1.0)
            message_count = p.get("message_count", 0)
            last_spoke = p.get("last_spoke_at", "")
            
            # 格式化时间
            time_str = "从未发言"
            if last_spoke:
                try:
                    dt = datetime.fromisoformat(last_spoke)
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    pass
            
            print(f"{colored(f'[{idx}]', Colors.CYAN)} "
                  f"{colored(display_name, Colors.YELLOW + Colors.BOLD)} "
                  f"{colored(f'({char_id})', Colors.DIM)}")
            print(f"    发言频率: {speak_freq:.1f} | "
                  f"消息数: {message_count} | "
                  f"最后发言: {time_str}")
        
        print_separator()
        
    except Exception as e:
        logger.warning(f"显示参与者失败: {e}")
        print(colored(f"❌ 显示失败: {e}", Colors.RED))


def show_all_character_states(character_ids: list[str], player_id: str):
    """显示所有角色的状态"""
    try:
        for char_id in character_ids:
            card = character_loader.load_character_card(char_id)
            runtime_state = repository.get_runtime_state(char_id, player_id, card)
            
            affinity = runtime_state.get("affection_level", 0)
            trust = runtime_state.get("trust_level", 0)
            mood = runtime_state.get("current_mood", "neutral")
            
            print(colored(f"\n{card.meta.display_name} 的状态：", Colors.CYAN))
            print(f"  好感度: {affinity:+.0f} | 信任度: {trust:.0f} | 情绪: {mood}")
        
    except Exception as e:
        logger.warning(f"显示角色状态失败: {e}")


def show_multi_character_session_history(session_id: str, player_name: str, limit: int = 10):
    """显示多角色会话的对话历史"""
    try:
        history = repository.get_multi_character_history(session_id, limit_messages=limit)
        
        if not history:
            print(colored("\n📜 本次会话暂无对话记录", Colors.DIM))
            return
        
        print(colored(f"\n📜 本次会话的最近 {len(history)} 条消息：", Colors.CYAN + Colors.BOLD))
        print_separator()
        
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            char_name = msg.get("character_name")
            
            if role == "user":
                print(colored(f"{player_name}: ", Colors.GREEN) + content)
            else:
                if char_name:
                    print(colored(f"{char_name}: ", Colors.YELLOW) + content)
                else:
                    print(colored(f"[角色]: ", Colors.YELLOW) + content)
        
        print_separator()
        
    except Exception as e:
        logger.warning(f"显示会话历史失败: {e}")
        print(colored(f"❌ 显示历史失败: {e}", Colors.RED))


def show_multi_character_session_stats(session_id: str, turn_count: int):
    """显示多角色会话统计"""
    try:
        history = repository.get_multi_character_history(session_id, limit_messages=1000)
        participants = repository.get_session_participants(session_id, only_active=True)
        
        message_count = len(history)
        user_messages = sum(1 for m in history if m["role"] == "user")
        assistant_messages = sum(1 for m in history if m["role"] == "assistant")
        
        print(colored("\n📊 会话统计：", Colors.CYAN + Colors.BOLD))
        print_separator("─", 40)
        print(f"  {colored('🔢 当前回合:', Colors.WHITE)} {turn_count}")
        print(f"  {colored('💬 总消息数:', Colors.WHITE)} {message_count}")
        print(f"  {colored('   玩家消息:', Colors.WHITE)} {user_messages}")
        print(f"  {colored('   角色消息:', Colors.WHITE)} {assistant_messages}")
        print(f"  {colored('👥 参与角色:', Colors.WHITE)} {len(participants)}")
        
        # 显示每个角色的发言统计
        print(colored("\n  各角色发言:", Colors.WHITE))
        for p in participants:
            char_name = p["display_name"]
            msg_count = p.get("message_count", 0)
            percentage = (msg_count / assistant_messages * 100) if assistant_messages > 0 else 0
            print(f"    • {char_name}: {msg_count} 条 ({percentage:.1f}%)")
        
        print_separator("─", 40)
        
    except Exception as e:
        logger.warning(f"显示会话统计失败: {e}")


# =========================
# 会话管理
# =========================
def select_or_create_session(character_id: str, player_id: str, player_name: str) -> tuple[str, bool]:
    """
    选择已有会话或创建新会话
    
    Returns:
        (session_id, is_new): 会话ID和是否为新会话
    """
    try:
        # 查询已有会话
        sessions = repository.get_sessions_by_player_and_character(character_id, player_id)
        active_sessions = [s for s in sessions if s.get("status") == "active"]
        
        if not active_sessions:
            # 没有活动会话，创建新会话
            return create_new_session(character_id, player_id, player_name)
        
        # 显示会话选项
        print(colored("\n📂 发现已有会话：", Colors.CYAN + Colors.BOLD))
        print_separator()
        
        for idx, session in enumerate(active_sessions[:5], 1):  # 最多显示5个
            session_id = session["session_id"]
            created_at = session.get("created_at", "")
            last_message = session.get("last_message", "")
            message_count = session.get("message_count", 0)
            
            # 格式化时间
            time_str = ""
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            
            print(f"{colored(f'[{idx}]', Colors.CYAN)} "
                  f"{colored(session_id[:8], Colors.YELLOW)}... "
                  f"{colored(time_str, Colors.DIM)}")
            print(f"    {colored(f'消息数: {message_count}', Colors.WHITE)} "
                  f"| 最后: {colored(last_message[:30] if last_message else '无', Colors.DIM)}...")
        
        print(f"\n{colored('[0]', Colors.CYAN)} {colored('创建新会话', Colors.GREEN)}")
        print_separator()
        
        # 用户选择
        while True:
            choice = input(colored("请选择会话编号（0=新建）: ", Colors.GREEN))
            
            if not choice.strip():
                continue
            
            try:
                choice_num = int(choice)
                
                if choice_num == 0:
                    return create_new_session(character_id, player_id, player_name)
                
                if 1 <= choice_num <= len(active_sessions):
                    selected_session = active_sessions[choice_num - 1]
                    session_id = selected_session["session_id"]
                    print(colored(f"\n✓ 已选择会话: {session_id[:8]}...", Colors.GREEN))
                    return session_id, False
                else:
                    print(colored("❌ 无效的编号，请重新输入", Colors.RED))
                    
            except ValueError:
                print(colored("❌ 请输入有效的数字", Colors.RED))
    
    except Exception as e:
        logger.warning(f"会话选择失败，创建新会话: {e}")
        return create_new_session(character_id, player_id, player_name)


def create_new_session(character_id: str, player_id: str, player_name: str) -> tuple[str, bool]:
    """创建新会话并返回开场白"""
    print(colored("\n🚀 正在创建新会话...", Colors.CYAN))
    
    result = orchestrator.start_session(character_id, player_id, player_name)
    session_id = result["session_id"]
    
    print(colored(f"✓ 会话已创建（ID: {session_id[:8]}...）", Colors.GREEN))
    
    return session_id, True


# =========================
# 主函数
# =========================
def main():
    """主入口函数"""
    try:
        # 初始化数据库
        repository.init_db()
        
        # 清屏并打印欢迎信息
        clear_screen()
        print_banner()
        print(colored("💡 提示: 输入 'help' 查看所有可用命令\n", Colors.DIM))
        
        # 选择对话模式
        mode = select_dialogue_mode()
        if mode == "exit":
            print(colored("\n👋 再见！", Colors.YELLOW))
            return
        
        # 获取玩家信息
        player_id, player_name = get_player_info()
        
        if mode == "single":
            # 单角色对话模式
            character_id = select_character()
            if not character_id:
                print(colored("\n👋 再见！", Colors.YELLOW))
                return
            
            # 显示角色状态和历史
            show_character_state(character_id, player_id)
            show_recent_summaries(character_id, player_id)
            
            # 选择或创建会话
            try:
                session_id, is_new_session = select_or_create_session(character_id, player_id, player_name)
                
                card = character_loader.load_character_card(character_id)
                character_name = card.meta.display_name
                
                print_separator("═", 60)
                
                # 如果是新会话，显示开场白
                if is_new_session:
                    result = orchestrator.start_session(character_id, player_id, player_name)
                    session_id = result["session_id"]
                    opening_line = result["opening_line"]
                    
                    print(colored(f"\n{character_name}: {opening_line}", Colors.YELLOW + Colors.BOLD))
                else:
                    # 继续已有会话
                    print(colored(f"\n📜 回顾最近的对话：", Colors.CYAN))
                    print_separator()
                    
                    history = repository.get_short_term_history(session_id, limit_turns=3)
                    for msg in history[-6:]:
                        role = msg["role"]
                        content = msg["content"]
                        
                        if role == "user":
                            print(colored(f"{player_name}: ", Colors.GREEN) + content)
                        else:
                            print(colored(f"{character_name}: ", Colors.YELLOW) + content)
                    
                    print_separator()
                    print(colored(f"\n{character_name}: 欢迎回来！我们继续吧。", Colors.YELLOW + Colors.BOLD))
                
                # 进入对话循环
                chat_loop(session_id, character_id, player_id, player_name)
                
            except FileNotFoundError as e:
                print(colored(f"\n❌ 角色卡未找到: {e}", Colors.RED))
            except Exception as e:
                logger.error(f"会话处理失败: {e}", exc_info=True)
                print(colored(f"\n❌ 会话处理失败: {e}", Colors.RED))
        
        elif mode == "multi":
            # 多角色对话模式
            character_ids = select_multiple_characters(min_count=2)
            if not character_ids:
                print(colored("\n👋 再见！", Colors.YELLOW))
                return
            
            # 显示所有角色状态
            show_all_character_states(character_ids, player_id)
            
            # 选择发言策略
            print(colored("\n⚙️  选择发言策略：", Colors.CYAN + Colors.BOLD))
            print_separator()
            print(f"{colored('[1]', Colors.CYAN)} {colored('轮询策略', Colors.WHITE)} - 角色按顺序轮流发言")
            print(f"{colored('[2]', Colors.CYAN)} {colored('权重随机', Colors.WHITE)} - 根据频率权重随机选择")
            print(f"{colored('[3]', Colors.CYAN)} {colored('智能选择', Colors.WHITE)} - 综合多因素决策（推荐）")
            print(f"{colored('[4]', Colors.CYAN)} {colored('混合策略', Colors.WHITE)} - 结合多种策略（默认）")
            print_separator()
            
            strategy_choice = input(colored("请选择策略（1-4，默认4）: ", Colors.GREEN))
            
            strategy_map = {
                "1": "round_robin",
                "2": "weighted",
                "3": "smart",
                "4": "hybrid",
                "": "hybrid"
            }
            
            strategy_type = strategy_map.get(strategy_choice.strip(), "hybrid")
            
            # 选择是否启用讨论模式
            print()
            print(colored("💬 选择对话模式：", Colors.CYAN + Colors.BOLD))
            print_separator()
            print(f"{colored('[1]', Colors.CYAN)} {colored('标准模式', Colors.WHITE)} - 每轮1个角色回应")
            print(f"{colored('[2]', Colors.CYAN)} {colored('讨论模式', Colors.WHITE)} - 每轮最多3个角色连续发言（推荐）")
            print_separator()
            
            mode_choice = input(colored("请选择对话模式（1-2，默认2）: ", Colors.GREEN))
            discussion_mode = mode_choice.strip() != "1"  # 默认启用讨论模式
            
            if discussion_mode:
                print(colored("✓ 讨论模式已启用，角色们会自然地连续讨论", Colors.GREEN))
            else:
                print(colored("✓ 标准模式，每轮只有1个角色发言", Colors.GREEN))
            
            try:
                # 创建多角色会话
                print(colored("\n🚀 正在创建多角色会话...", Colors.CYAN))
                
                result = start_multi_character_session(
                    player_id=player_id,
                    player_name=player_name,
                    character_ids=character_ids,
                    strategy_type=strategy_type
                )
                
                session_id = result["session_id"]
                opening = result["opening"]
                
                print(colored(f"✓ 会话已创建（ID: {session_id[:8]}...）", Colors.GREEN))
                print_separator("═", 60)
                
                # 显示开场白
                character_name = opening["character_name"]
                dialogue = opening["dialogue"]
                action = opening.get("action", "")
                
                if action and action != "default":
                    print(colored(f"\n{character_name} [{action}]: {dialogue}", 
                                Colors.YELLOW + Colors.BOLD))
                else:
                    print(colored(f"\n{character_name}: {dialogue}", Colors.YELLOW + Colors.BOLD))
                
                # 进入多角色对话循环
                multi_character_chat_loop(
                    session_id=session_id,
                    character_ids=character_ids,
                    player_id=player_id,
                    player_name=player_name,
                    strategy_type=strategy_type,
                    discussion_mode=discussion_mode
                )
                
            except Exception as e:
                logger.error(f"多角色会话处理失败: {e}", exc_info=True)
                print(colored(f"\n❌ 会话处理失败: {e}", Colors.RED))
        
    except KeyboardInterrupt:
        print(colored("\n\n👋 程序已退出", Colors.YELLOW))
    except Exception as e:
        logger.error(f"主程序错误: {e}", exc_info=True)
        print(colored(f"\n❌ 程序错误: {e}", Colors.RED))
    finally:
        print(colored("\n感谢使用 Memoria！\n", Colors.CYAN))


if __name__ == "__main__":
    main()

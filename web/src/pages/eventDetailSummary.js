const EFFECT_LABELS = {
  modify_state: '修改状态',
  unlock_content: '解锁内容',
  trigger_dialogue: '触发对话',
  add_memory: '添加记忆',
  change_mood: '改变情绪',
  notify_player: '通知玩家',
  trigger_event: '触发事件链',
  branch_event: '分支事件',
  npc_proactive_dialogue: 'NPC 主动发言',
  update_event_progress: '更新事件进度',
};

export function eventEffectLabel(effectType) {
  return Object.hasOwn(EFFECT_LABELS, effectType)
    ? EFFECT_LABELS[effectType]
    : '其他效果';
}

export function summarizeEventEffect(effect = {}) {
  if (effect.effect_type === 'modify_state') {
    const count = Object.keys(effect.state_changes || {}).length;
    return count ? `调整 ${count} 项状态` : '调整角色状态';
  }

  if (effect.effect_type === 'unlock_content') {
    const count = Array.isArray(effect.unlock_keys)
      ? effect.unlock_keys.filter(Boolean).length
      : 0;
    return count ? `解锁 ${count} 项内容` : '解锁剧情内容';
  }

  if (effect.effect_type === 'trigger_dialogue') return '播放预设对白';
  if (effect.effect_type === 'add_memory') return '写入一条长期记忆';
  if (effect.effect_type === 'change_mood') {
    return effect.target_mood ? `情绪变为 ${effect.target_mood}` : '调整角色情绪';
  }
  if (effect.effect_type === 'notify_player') return '向玩家发送通知';
  if (effect.effect_type === 'trigger_event') return '继续触发后续事件';

  if (effect.effect_type === 'branch_event') {
    const count = Array.isArray(effect.branch_conditions)
      ? effect.branch_conditions.length
      : 0;
    return count ? `按 ${count} 个条件选择分支` : '按条件选择事件分支';
  }

  if (effect.effect_type === 'npc_proactive_dialogue') return '安排 NPC 主动发言';
  if (effect.effect_type === 'update_event_progress') {
    return effect.progress_delta != null ? '相对调整事件进度' : '设置事件进度';
  }

  return '执行其他事件效果';
}

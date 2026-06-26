/**
 * Memoria 可视化角色卡编辑器 JavaScript 逻辑
 */

// =========================
// 全局状态
// =========================
let currentEditingId = null; // 当前正在编辑的角色 ID（编辑模式）

// =========================
// 页面加载初始化
// =========================
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initTagInputs();
    
    // 检查是否是编辑模式（从 URL 参数获取）
    const urlParams = new URLSearchParams(window.location.search);
    const editId = urlParams.get('id');
    
    if (editId) {
        currentEditingId = editId;
        loadCharacterForEdit(editId);
    }
});

// =========================
// 侧边栏导航切换
// =========================
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            // 移除所有激活状态
            navItems.forEach(nav => nav.classList.remove('active'));
            document.querySelectorAll('.section').forEach(section => {
                section.classList.remove('active');
            });
            
            // 激活当前项
            item.classList.add('active');
            const sectionId = item.getAttribute('data-section');
            const section = document.getElementById(`section-${sectionId}`);
            if (section) {
                section.classList.add('active');
            }
        });
    });
}

// =========================
// 标签输入组件
// =========================
function initTagInputs() {
    const tagContainers = document.querySelectorAll('.tag-input-container');
    
    tagContainers.forEach(container => {
        const input = container.querySelector('.tag-input');
        
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                const value = input.value.trim();
                
                if (value) {
                    addTag(container, value);
                    input.value = '';
                }
            }
        });
        
        // 失去焦点时也尝试添加
        input.addEventListener('blur', () => {
            const value = input.value.trim();
            if (value) {
                addTag(container, value);
                input.value = '';
            }
        });
    });
}

function addTag(container, text) {
    const tag = document.createElement('div');
    tag.className = 'tag';
    tag.innerHTML = `
        <span>${escapeHtml(text)}</span>
        <span class="tag-remove" onclick="removeTag(this)">×</span>
    `;
    
    const input = container.querySelector('.tag-input');
    container.insertBefore(tag, input);
}

function removeTag(element) {
    element.parentElement.remove();
}

function getTags(containerId) {
    const container = document.getElementById(containerId);
    const tags = container.querySelectorAll('.tag span:first-child');
    return Array.from(tags).map(tag => tag.textContent);
}

// =========================
// 列表编辑器
// =========================
function addListItem(listType) {
    const listContainer = document.getElementById(`${listType}-list`);
    
    const listItem = document.createElement('div');
    listItem.className = 'list-item';
    listItem.innerHTML = `
        <input type="text" placeholder="输入内容">
        <button class="list-item-remove" onclick="removeListItem(this)">删除</button>
    `;
    
    listContainer.appendChild(listItem);
}

function removeListItem(button) {
    button.parentElement.remove();
}

function getListItems(listType) {
    const listContainer = document.getElementById(`${listType}-list`);
    const inputs = listContainer.querySelectorAll('input');
    return Array.from(inputs)
        .map(input => input.value.trim())
        .filter(value => value !== '');
}

function setListItems(listType, items) {
    const listContainer = document.getElementById(`${listType}-list`);
    listContainer.innerHTML = ''; // 清空现有内容
    
    items.forEach(item => {
        const listItem = document.createElement('div');
        listItem.className = 'list-item';
        listItem.innerHTML = `
            <input type="text" value="${escapeHtml(item)}">
            <button class="list-item-remove" onclick="removeListItem(this)">删除</button>
        `;
        listContainer.appendChild(listItem);
    });
}

// =========================
// 数据收集 - 从表单生成 JSON
// =========================
function collectFormData() {
    const data = {
        character_id: getValue('character_id'),
        version: getValue('version') || '1.0.0',
        
        meta: {
            name: getValue('meta_name'),
            display_name: getValue('meta_display_name') || getValue('meta_name'),
            aliases: getTags('aliases-container'),
            game_module: '',
            created_by: '',
            last_updated: new Date().toISOString()
        },
        
        identity: {
            age: getValue('age') || 'unknown',
            gender: getValue('gender') || '未知',
            occupation: getValue('occupation') || '',
            race_or_species: '',
            appearance: getValue('appearance') || '',
            social_status: '',
            core_identity_summary: getValue('core_identity_summary') || ''
        },
        
        personality: {
            mbti_or_archetype: '',
            core_traits: getTags('core-traits-container'),
            values_and_beliefs: getListItems('values'),
            fears_and_tabooes: getListItems('fears'),
            quirks_and_habits: getListItems('quirks'),
            moral_alignment: ''
        },
        
        speech_style: {
            tone_register: getValue('tone_register') || '',
            vocabulary_notes: getValue('vocabulary_notes') || '',
            sentence_patterns: getListItems('sentence-patterns'),
            catchphrases: getTags('catchphrases-container'),
            things_never_to_say: getListItems('never-say'),
            language: 'zh-CN',
            formality_default: ''
        },
        
        background: {
            story_bio: getValue('story_bio') || '',
            key_events: [],
            relationships: [],
            secrets: []
        },
        
        goals_and_motivations: {
            current_goals: [],
            long_term_goals: [],
            what_triggers_anger: [],
            what_brings_joy: []
        },
        
        interaction_rules: {
            initial_attitude_to_player: getValue('initial_attitude') || 'neutral',
            topics_to_avoid_unless_trusted: getTags('avoid-topics-container'),
            topics_he_or_she_loves_to_discuss: getTags('love-topics-container'),
            response_to_rudeness: getListItems('rudeness-response'),
            gift_reactions: []
        },
        
        action_vocabulary: {
            greeting_actions: getListItems('greeting-actions'),
            farewell_actions: getListItems('farewell-actions'),
            agreement_actions: getListItems('agreement-actions'),
            disagreement_actions: getListItems('disagreement-actions'),
            emotional_reactions: getListItems('emotional-reactions'),
            default_action: getValue('default_action') || 'neutral',
            fallback_priority: [
                'emotional_reactions',
                'agreement_actions',
                'disagreement_actions',
                'greeting_actions',
                'farewell_actions'
            ]
        },
        
        runtime_state_schema: {
            relationships: [
                {
                    target_id: 'player',
                    affection_level: parseFloat(getValue('initial_affection')) || 0,
                    trust_level: parseFloat(getValue('initial_trust')) || 10
                }
            ],
            current_mood: {
                type: 'enum',
                emotions: getTags('emotions-container'),
                intensity: 0,
                default_mood: getValue('default_mood') || 'neutral'
            },
            known_player_facts: {}
        },
        
        safety_constraints: {
            topics_to_avoid: [],
            out_of_character_handling: ''
        }
    };
    
    // 添加关键经历
    const keyExperiences = getListItems('key-experiences');
    data.background.key_events = keyExperiences.map(exp => ({
        event: exp,
        description: '',
        emotional_weight: 0
    }));
    
    return data;
}

// =========================
// 辅助函数
// =========================
function getValue(id) {
    const element = document.getElementById(id);
    return element ? element.value.trim() : '';
}

function setValue(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.value = value || '';
    }
}

function setTags(containerId, tags) {
    const container = document.getElementById(containerId);
    // 清除现有标签（保留输入框）
    const existingTags = container.querySelectorAll('.tag');
    existingTags.forEach(tag => tag.remove());
    
    // 添加新标签
    tags.forEach(tag => addTag(container, tag));
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =========================
// 预览功能
// =========================
function generatePreview() {
    try {
        const data = collectFormData();
        
        // 验证必填字段
        if (!data.character_id) {
            showToast('请填写角色 ID', 'error');
            return;
        }
        if (!data.meta.name) {
            showToast('请填写角色名称', 'error');
            return;
        }
        
        const previewContent = document.getElementById('json-preview');
        previewContent.textContent = JSON.stringify(data, null, 2);
        
        showToast('预览已更新', 'success');
    } catch (error) {
        console.error('生成预览失败:', error);
        showToast('生成预览失败: ' + error.message, 'error');
    }
}

// =========================
// 保存到服务器
// =========================
async function saveCharacter() {
    try {
        const data = collectFormData();
        
        // 验证必填字段
        if (!data.character_id) {
            showToast('请填写角色 ID', 'error');
            return;
        }
        if (!data.meta.name) {
            showToast('请填写角色名称', 'error');
            return;
        }
        if (!data.identity.core_identity_summary) {
            showToast('请填写核心身份概述', 'error');
            return;
        }
        
        // 确定是创建还是更新
        const isEdit = !!currentEditingId;
        const url = isEdit 
            ? `/admin/characters/${currentEditingId}`
            : '/admin/characters';
        const method = isEdit ? 'PUT' : 'POST';
        
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                character_data: data
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '保存失败');
        }
        
        const result = await response.json();
        
        showToast(result.message || '保存成功！', 'success');
        
        // 如果是新建，跳转到编辑模式
        if (!isEdit && result.character_id) {
            setTimeout(() => {
                window.location.href = `/editor?id=${result.character_id}`;
            }, 1500);
        }
        
    } catch (error) {
        console.error('保存角色卡失败:', error);
        showToast('保存失败: ' + error.message, 'error');
    }
}

// =========================
// 下载 JSON 文件
// =========================
function downloadJSON() {
    try {
        const data = collectFormData();
        
        if (!data.character_id) {
            showToast('请填写角色 ID', 'error');
            return;
        }
        
        const json = JSON.stringify(data, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `${data.character_id}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showToast('JSON 文件已下载', 'success');
    } catch (error) {
        console.error('下载失败:', error);
        showToast('下载失败: ' + error.message, 'error');
    }
}

// =========================
// 加载现有角色卡（编辑模式）
// =========================
async function loadCharacterForEdit(characterId) {
    try {
        showToast('正在加载角色卡...', 'info');
        
        const response = await fetch(`/admin/characters/${characterId}`);
        
        if (!response.ok) {
            throw new Error('加载角色卡失败');
        }
        
        const result = await response.json();
        const data = result.card_data;
        
        // 填充表单
        populateForm(data);
        
        // 更新页面标题
        document.querySelector('.header h1').textContent = `🎨 编辑角色卡: ${data.meta.name}`;
        
        showToast('角色卡加载成功', 'success');
        
    } catch (error) {
        console.error('加载角色卡失败:', error);
        showToast('加载失败: ' + error.message, 'error');
    }
}

// =========================
// 填充表单
// =========================
function populateForm(data) {
    // 基础信息
    setValue('character_id', data.character_id);
    setValue('version', data.version);
    setValue('meta_name', data.meta?.name || '');
    setValue('meta_display_name', data.meta?.display_name || '');
    setTags('aliases-container', data.meta?.aliases || []);
    
    // 身份与外貌
    setValue('core_identity_summary', data.identity?.core_identity_summary || '');
    setValue('age', data.identity?.age || '');
    setValue('gender', data.identity?.gender || '男');
    setValue('occupation', data.identity?.occupation || '');
    setValue('appearance', data.identity?.appearance || '');
    
    // 性格特质
    setTags('core-traits-container', data.personality?.core_traits || []);
    setListItems('values', data.personality?.values_and_beliefs || []);
    setListItems('fears', data.personality?.fears_and_tabooes || []);
    setListItems('quirks', data.personality?.quirks_and_habits || []);
    
    // 语言风格
    setValue('tone_register', data.speech_style?.tone_register || '');
    setValue('vocabulary_notes', data.speech_style?.vocabulary_notes || '');
    setListItems('sentence-patterns', data.speech_style?.sentence_patterns || []);
    setTags('catchphrases-container', data.speech_style?.catchphrases || []);
    setListItems('never-say', data.speech_style?.things_never_to_say || []);
    
    // 动作词库
    setListItems('greeting-actions', data.action_vocabulary?.greeting_actions || []);
    setListItems('farewell-actions', data.action_vocabulary?.farewell_actions || []);
    setListItems('agreement-actions', data.action_vocabulary?.agreement_actions || []);
    setListItems('disagreement-actions', data.action_vocabulary?.disagreement_actions || []);
    setListItems('emotional-reactions', data.action_vocabulary?.emotional_reactions || []);
    setValue('default_action', data.action_vocabulary?.default_action || 'neutral');
    
    // 背景故事
    setValue('story_bio', data.background?.story_bio || '');
    const keyEvents = (data.background?.key_events || []).map(e => e.event);
    setListItems('key-experiences', keyEvents);
    
    // 交互规则
    setValue('initial_attitude', data.interaction_rules?.initial_attitude_to_player || 'neutral');
    setTags('avoid-topics-container', data.interaction_rules?.topics_to_avoid_unless_trusted || []);
    setTags('love-topics-container', data.interaction_rules?.topics_he_or_she_loves_to_discuss || []);
    setListItems('rudeness-response', data.interaction_rules?.response_to_rudeness || []);
    
    // 运行时状态
    const playerRelation = data.runtime_state_schema?.relationships?.find(r => r.target_id === 'player');
    if (playerRelation) {
        setValue('initial_affection', playerRelation.affection_level || 0);
        setValue('initial_trust', playerRelation.trust_level || 10);
    }
    setTags('emotions-container', data.runtime_state_schema?.current_mood?.emotions || []);
    setValue('default_mood', data.runtime_state_schema?.current_mood?.default_mood || 'neutral');
}

// =========================
// Toast 通知
// =========================
function showToast(message, type = 'info') {
    // 移除现有 toast
    const existingToast = document.querySelector('.toast');
    if (existingToast) {
        existingToast.remove();
    }
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Power, PowerOff, Trash2, Loader2, Clock, Zap, Filter, Search, ChevronRight } from 'lucide-react';
import { eventAdmin } from '../api/memoria';

const TRIGGER_LABELS = {
  affinity_threshold: '好感度阈值',
  trust_threshold: '信任度阈值',
  keyword_match: '关键词匹配',
  dialogue_count: '对话次数',
  time_based: '时间条件',
  mood_match: '情绪匹配',
  relationship_change: '关系变化',
  composite: '复合条件',
};

const TRIGGER_ICONS = {
  affinity_threshold: '♥',
  trust_threshold: '★',
  keyword_match: '⌨',
  dialogue_count: '↻',
  time_based: '◷',
  mood_match: '☻',
  relationship_change: '↔',
  composite: '⊞',
};

export default function EventList() {
  const navigate = useNavigate();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all'); // all | active | disabled
  const [search, setSearch] = useState('');

  useEffect(() => { loadEvents(); }, []);

  async function loadEvents() {
    try {
      setLoading(true);
      const list = await eventAdmin.list();
      setEvents(list);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle(evt) {
    try {
      await eventAdmin.toggle(evt.event_id, !evt.is_active);
      setEvents(prev => prev.map(e =>
        e.event_id === evt.event_id ? { ...e, is_active: !e.is_active } : e
      ));
    } catch (e) {
      console.error('Toggle failed:', e.message);
    }
  }

  async function handleDelete(evt) {
    if (!window.confirm(`确定删除事件 "${evt.event_name}" 吗？此操作不可撤销。`)) return;
    try {
      await eventAdmin.delete(evt.event_id);
      setEvents(prev => prev.filter(e => e.event_id !== evt.event_id));
    } catch (e) {
      console.error('Delete failed:', e.message);
    }
  }

  const filtered = useMemo(() => {
    let list = events;
    if (filter === 'active') list = list.filter(e => e.is_active);
    if (filter === 'disabled') list = list.filter(e => !e.is_active);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(e =>
        e.event_name.toLowerCase().includes(q) ||
        e.event_id.toLowerCase().includes(q) ||
        (e.description || '').toLowerCase().includes(q)
      );
    }
    return list;
  }, [events, filter, search]);

  const activeCount = events.filter(e => e.is_active).length;

  return (
    <div className="min-h-screen bg-cyber-bg">
      {/* Header */}
      <div className="sticky top-0 z-20 bg-cyber-bg/95 backdrop-blur border-b border-cyber-green/15">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-2 text-cyber-green/50 hover:text-cyber-green transition-colors font-mono text-sm"
          >
            <ArrowLeft size={16} />
            Home
          </button>
          <div className="text-center">
            <h1 className="font-display text-base text-cyber-green tracking-[0.25em]">EVENT MANAGEMENT</h1>
            <p className="text-[10px] font-mono text-cyber-green/30 mt-0.5 tracking-[0.15em]">
              {events.length} TOTAL · {activeCount} ACTIVE
            </p>
          </div>
          <button
            onClick={() => navigate('/events/new')}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-cyber-green/15 border border-cyber-green/30 text-cyber-green font-mono text-xs rounded hover:bg-cyber-green/25 transition-colors"
          >
            <Plus size={14} />
            New
          </button>
        </div>

        {/* Toolbar */}
        <div className="max-w-6xl mx-auto px-6 pb-3 flex items-center gap-3">
          <div className="flex items-center gap-1 bg-cyber-surface/50 border border-cyber-green/10 rounded p-0.5">
            {[
              { value: 'all', label: '全部' },
              { value: 'active', label: '启用' },
              { value: 'disabled', label: '禁用' },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => setFilter(opt.value)}
                className={`px-3 py-1 text-[10px] font-mono rounded transition-colors ${
                  filter === opt.value
                    ? 'bg-cyber-green/15 text-cyber-green'
                    : 'text-cyber-green/40 hover:text-cyber-green/70'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="flex-1" />
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-cyber-green/30" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="搜索..."
              className="w-48 bg-cyber-surface/50 border border-cyber-green/10 text-cyber-green/80 text-[11px] font-mono rounded pl-7 pr-3 py-1.5 focus:outline-none focus:border-cyber-green/40 placeholder:text-cyber-green/20"
            />
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-6 py-6">
        {loading && (
          <div className="flex items-center gap-3 text-cyber-green/40 justify-center py-32">
            <Loader2 className="animate-spin" size={18} />
            <span className="font-mono text-sm">Loading events...</span>
          </div>
        )}

        {error && (
          <div className="text-red-400/70 font-mono text-xs mb-6 text-center bg-red-400/5 border border-red-400/10 rounded py-3">
            {error}
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="text-center py-32">
            <div className="text-4xl text-cyber-green/10 mb-4">
              <Zap size={48} className="mx-auto" />
            </div>
            <p className="font-mono text-sm text-cyber-green/25 mb-4">
              {events.length === 0 ? '暂无事件定义' : '无匹配结果'}
            </p>
            {events.length === 0 && (
              <button
                onClick={() => navigate('/events/new')}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-cyber-green/10 border border-cyber-green/25 text-cyber-green/70 font-mono text-xs rounded hover:bg-cyber-green/20 transition-colors"
              >
                <Plus size={14} /> 创建第一个事件
              </button>
            )}
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-2">
            {filtered.map(evt => (
              <div
                key={evt.event_id}
                onClick={() => navigate(`/events/${evt.event_id}`)}
                className={`group cursor-pointer border transition-all duration-200
                  ${evt.is_active
                    ? 'border-cyber-green/10 bg-cyber-surface/20 hover:border-cyber-green/30 hover:bg-cyber-surface/40'
                    : 'border-cyber-green/5 bg-cyber-surface/10 opacity-50 hover:opacity-70'
                  }`}
              >
                <div className="flex items-center gap-4 px-5 py-3.5">
                  {/* Trigger icon */}
                  <div className={`w-10 h-10 rounded flex items-center justify-center text-sm font-mono shrink-0
                    ${evt.is_active ? 'bg-cyber-green/10 text-cyber-green/60' : 'bg-cyber-green/5 text-cyber-green/20'}`}
                  >
                    {TRIGGER_ICONS[evt.trigger_type] || '⚡'}
                  </div>

                  {/* Main info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className={`font-mono text-sm truncate ${evt.is_active ? 'text-cyber-green/85 group-hover:text-cyber-green' : 'text-cyber-green/40'}`}>
                        {evt.event_name}
                      </h3>
                      <span className={`shrink-0 inline-block w-1.5 h-1.5 rounded-full ${evt.is_active ? 'bg-cyber-green/60' : 'bg-cyber-green/10'}`} />
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <span className="text-[10px] font-mono text-cyber-green/25 truncate max-w-[200px]">
                        {evt.event_id}
                      </span>
                      {evt.character_id && (
                        <span className="text-[10px] font-mono text-cyber-green/20 truncate max-w-[120px]">
                          @{evt.character_id}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Trigger type */}
                  <span className="hidden sm:inline text-[10px] font-mono text-cyber-green/35 whitespace-nowrap">
                    {TRIGGER_LABELS[evt.trigger_type] || evt.trigger_type}
                  </span>

                  {/* Stats */}
                  <div className="hidden md:flex items-center gap-4 text-[10px] font-mono text-cyber-green/25">
                    <span className="flex items-center gap-1">
                      <Clock size={10} />
                      {evt.trigger_count || 0}
                    </span>
                    <span>P{evt.priority}</span>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-0.5 shrink-0">
                    <button
                      onClick={e => { e.stopPropagation(); handleToggle(evt); }}
                      title={evt.is_active ? '禁用' : '启用'}
                      className={`p-1.5 rounded transition-colors ${
                        evt.is_active
                          ? 'text-cyber-green/40 hover:text-cyber-green hover:bg-cyber-green/10'
                          : 'text-cyber-green/20 hover:text-cyber-green/50 hover:bg-cyber-green/5'
                      }`}
                    >
                      {evt.is_active ? <PowerOff size={14} /> : <Power size={14} />}
                    </button>
                    <button
                      onClick={e => { e.stopPropagation(); handleDelete(evt); }}
                      className="p-1.5 rounded text-cyber-green/15 hover:text-red-400/70 hover:bg-red-400/5 transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                    <ChevronRight size={14} className="text-cyber-green/10 group-hover:text-cyber-green/40 transition-colors" />
                  </div>
                </div>

                {/* Description preview */}
                {evt.description && (
                  <div className="px-5 pb-3 -mt-1">
                    <p className="text-[10px] font-mono text-cyber-green/25 line-clamp-1 ml-14">
                      {evt.description}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

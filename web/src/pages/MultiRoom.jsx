import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { multiDialogue, characterAdmin } from '../api/memoria';
import { Send, ArrowLeft, Users, Loader2, User, X, Plus, Settings, MessageSquare, Radio, ShieldAlert } from 'lucide-react';

const PLAYER_ID = 'player-' + Math.random().toString(36).slice(2, 8);
const PLAYER_NAME = '旅行者';

const STRATEGIES = [
  { value: 'hybrid', label: '智能混合' },
  { value: 'round_robin', label: '轮流发言' },
  { value: 'smart', label: '情境感知' },
  { value: 'trigger', label: '事件触发' },
];

export default function MultiRoom() {
  const navigate = useNavigate();
  const [allChars, setAllChars] = useState([]);
  const [participants, setParticipants] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [discussionMode, setDiscussionMode] = useState(false);
  const [maxResponses, setMaxResponses] = useState(3);
  const [strategy, setStrategy] = useState('hybrid');
  const [phase, setPhase] = useState('setup'); // setup | chat
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showManage, setShowManage] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  // Load all characters
  useEffect(() => {
    (async () => {
      try {
        const list = await characterAdmin.list(false);
        const enriched = [];
        for (const c of list) {
          try {
            const detail = await characterAdmin.get(c.character_id);
            enriched.push({
              character_id: c.character_id,
              name: detail.card_data?.meta?.name || c.display_name || c.character_id,
              avatar_url: detail.avatar_url || null,
            });
          } catch {
            enriched.push({
              character_id: c.character_id,
              name: c.display_name || c.character_id,
              avatar_url: null,
            });
          }
        }
        setAllChars(enriched);
      } catch (e) {
        setError(e.message);
      }
    })();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (phase === 'chat') inputRef.current?.focus();
  }, [phase]);

  const toggleParticipant = (char) => {
    setParticipants(prev =>
      prev.find(p => p.character_id === char.character_id)
        ? prev.filter(p => p.character_id !== char.character_id)
        : [...prev, { ...char, frequency: 1.0 }]
    );
  };

  const updateFrequency = (charId, freq) => {
    setParticipants(prev => prev.map(p => p.character_id === charId ? { ...p, frequency: freq } : p));
  };

  const startSession = async () => {
    if (participants.length < 2) {
      setError('至少需要选择2个角色');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const freqs = {};
      participants.forEach(p => { freqs[p.character_id] = p.frequency; });
      const res = await multiDialogue.startSession(PLAYER_ID, PLAYER_NAME, participants.map(p => p.character_id), strategy, freqs);
      setSessionId(res.session_id);
      setPhase('chat');
      if (res.opening?.dialogue) {
        setMessages([{
          role: 'assistant',
          charId: res.opening.character_id,
          charName: res.opening.character_name || '未知',
          content: res.opening.dialogue,
          action: res.opening.action || '',
        }]);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || !sessionId || sending) return;
    setInput('');
    setSending(true);
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    try {
      let res;
      if (discussionMode) {
        res = await multiDialogue.discussMessage(sessionId, text, maxResponses, strategy);
        const msgs = res.responses.map(r => ({
          role: 'assistant',
          charId: r.character_id,
          charName: r.character_name || '未知',
          content: r.dialogue,
          action: r.action || '',
          affinity_delta: r.affinity_delta || 0,
          mood: r.current_mood || 'neutral',
        }));
        setMessages(prev => [...prev, ...msgs]);
      } else {
        res = await multiDialogue.sendMessage(sessionId, text, strategy);
        setMessages(prev => [...prev, {
          role: 'assistant',
          charId: res.character_id,
          charName: res.character_name || '未知',
          content: res.dialogue,
          action: res.action || '',
          affinity_delta: res.affinity_delta || 0,
          mood: res.current_mood || 'neutral',
        }]);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }, [input, sessionId, sending, discussionMode, maxResponses, strategy]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleAddParticipant = async (char) => {
    if (!sessionId) return;
    try {
      await multiDialogue.addParticipant(sessionId, char.character_id);
      setParticipants(prev => [...prev, char]);
    } catch (e) {
      setError(e.message);
    }
  };

  const handleRemoveParticipant = async (charId) => {
    if (!sessionId) return;
    try {
      await multiDialogue.removeParticipant(sessionId, charId);
      setParticipants(prev => prev.filter(p => p.character_id !== charId));
    } catch (e) {
      setError(e.message);
    }
  };

  const getCharById = (id) => {
    return participants.find(p => p.character_id === id)
      || allChars.find(c => c.character_id === id);
  };

  // ── Setup phase ──
  if (phase === 'setup') {
    return (
      <div className="min-h-screen bg-[#0b0b0c] flex flex-col font-mono">
        <header className="flex items-center gap-4 px-6 py-3 border-b border-cyber-green/10 bg-[#0d0d14]/80">
          <button onClick={() => navigate('/')} className="text-cyber-green/50 hover:text-cyber-green p-1">
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-sm font-bold text-cyber-green">多角色群聊 · 创建</h1>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-6 max-w-2xl mx-auto w-full space-y-6">
          {error && (
            <div className="text-red-400/60 text-xs p-2 bg-red-500/5 rounded border border-red-500/10">
              {error}
              <button onClick={() => setError(null)} className="ml-2 underline">关闭</button>
            </div>
          )}

          {/* Strategy selector */}
          <div>
            <label className="text-[10px] text-cyber-green/50 uppercase tracking-wider mb-2 block">发言策略</label>
            <div className="flex flex-wrap gap-1.5">
              {STRATEGIES.map(s => {
                const activeClass = strategy === s.value
                  ? 'border-cyber-green/50 bg-cyber-green/10 text-cyber-green'
                  : 'border-cyber-green/10 text-cyber-green/40 hover:border-cyber-green/30';
                return (
                  <button
                    key={s.value}
                    onClick={() => setStrategy(s.value)}
                    className={`text-xs px-3 py-1.5 rounded border transition-colors ${activeClass}`}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Discussion mode */}
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={discussionMode}
                onChange={e => setDiscussionMode(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-8 h-4 rounded-full bg-cyber-green/10 border border-cyber-green/20 peer-checked:bg-cyber-green/30 peer-checked:border-cyber-green/50 transition-colors relative after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:rounded-full after:bg-cyber-green/50 after:transition-transform peer-checked:after:translate-x-4" />
              <span className="text-xs text-cyber-green/70">讨论模式</span>
            </label>
            {discussionMode && (
              <select
                value={maxResponses}
                onChange={e => setMaxResponses(Number(e.target.value))}
                className="text-xs bg-[#0d0d14] border border-cyber-green/20 rounded px-2 py-1 text-cyber-green/60"
              >
                {[1, 2, 3, 4, 5].map(n => (
                  <option key={n} value={n}>最多 {n} 人回应</option>
                ))}
              </select>
            )}
          </div>

          {/* Character selection */}
          <div>
            <label className="text-[10px] text-cyber-green/50 uppercase tracking-wider mb-2 block">
              选择角色 ({participants.length}/5)
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {allChars.map(char => {
                const selected = participants.find(p => p.character_id === char.character_id);
                return (
                  <div
                    key={char.character_id}
                    onClick={() => toggleParticipant(char)}
                    className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-all ${
                      selected
                        ? 'border-cyber-green/40 bg-cyber-green/5'
                        : 'border-white/5 bg-[#0d0d14] hover:border-cyber-green/15'
                    }`}
                  >
                    <div className="w-8 h-8 rounded-full overflow-hidden border border-cyber-green/20 bg-[#0d0d14] shrink-0">
                      {char.avatar_url ? (
                        <img src={char.avatar_url} alt="" className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-cyber-green/30 text-xs font-bold">
                          {char.name?.charAt(0) || '?'}
                        </div>
                      )}
                    </div>
                    <span className="text-xs text-cyber-green/80 truncate flex-1">{char.name}</span>
                    {selected && (
                      <div className="text-[10px] flex items-center gap-1">
                        {/* Frequency slider for selected */}
                        <input
                          type="range"
                          min="0"
                          max="2"
                          step="0.1"
                          value={selected.frequency}
                          onClick={e => e.stopPropagation()}
                          onChange={e => { e.stopPropagation(); updateFrequency(char.character_id, parseFloat(e.target.value)); }}
                          className="w-12 h-1 accent-cyber-green"
                        />
                        <span className="text-cyber-green/40 w-5 text-right">{selected.frequency.toFixed(1)}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Selected participants summary */}
          {participants.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {participants.map(p => (
                <div key={p.character_id} className="flex items-center gap-1 text-[10px] bg-cyber-green/5 border border-cyber-green/15 rounded-full px-2 py-0.5 text-cyber-green/70">
                  {p.name}
                  <button onClick={() => toggleParticipant(p)} className="text-cyber-green/30 hover:text-red-400 ml-0.5">
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Start button */}
          <button
            onClick={startSession}
            disabled={participants.length < 2 || loading}
            className="w-full py-2.5 bg-cyber-green/10 hover:bg-cyber-green/20 border border-cyber-green/20 rounded-lg text-sm font-bold text-cyber-green disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="animate-spin" size={16} /> : <Users size={16} />}
            开始群聊 ({participants.length}人)
          </button>
        </div>
      </div>
    );
  }

  // ── Chat phase ──
  return (
    <div className="min-h-screen bg-[#0b0b0c] flex flex-col font-mono">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-cyber-green/10 bg-[#0d0d14]/80 backdrop-blur shrink-0">
        <button onClick={() => navigate('/')} className="text-cyber-green/50 hover:text-cyber-green p-1">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 flex items-center gap-2 min-w-0">
          <span className="text-xs font-bold text-cyber-green truncate">群聊</span>
          <span className="text-[10px] text-cyber-green/30">{participants.length}人</span>
        </div>
        <button
          onClick={() => setDiscussionMode(!discussionMode)}
          className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
            discussionMode
              ? 'border-purple-400/40 bg-purple-400/10 text-purple-300'
              : 'border-cyber-green/15 text-cyber-green/40'
          }`}
        >
          <Radio size={12} className="inline mr-1" />
          讨论: {discussionMode ? 'ON' : 'OFF'}
        </button>
        {discussionMode && (
          <select
            value={maxResponses}
            onChange={e => setMaxResponses(Number(e.target.value))}
            className="text-[10px] bg-[#0d0d14] border border-cyber-green/20 rounded px-1.5 py-0.5 text-cyber-green/60"
          >
            {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}人回应</option>)}
          </select>
        )}
        <button
          onClick={() => setShowManage(!showManage)}
          className={`text-cyber-green/40 hover:text-cyber-green p-1 transition-colors ${showManage ? 'text-cyber-green' : ''}`}
        >
          <Settings size={16} />
        </button>
        <Link to={`/chat/${participants[0]?.character_id || ''}`} className="text-[10px] text-cyber-green/40 hover:text-cyber-green border border-cyber-green/20 rounded px-2 py-0.5">
          单聊
        </Link>
      </header>

      {/* Manage panel */}
      {showManage && (
        <div className="mx-4 mt-2 p-3 border border-cyber-green/10 bg-[#0d0d14]/90 rounded-lg">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-cyber-green/50 uppercase tracking-wider">参与者管理</span>
            <button onClick={() => setShowManage(false)} className="text-cyber-green/30 hover:text-cyber-green">
              <X size={12} />
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {participants.map(p => (
              <div key={p.character_id} className="flex items-center gap-1 text-[10px] bg-cyber-green/5 border border-cyber-green/15 rounded-full px-2 py-0.5 text-cyber-green/70">
                {p.name}
                <button onClick={() => handleRemoveParticipant(p.character_id)} className="text-cyber-green/30 hover:text-red-400">
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>
          <div className="text-[9px] text-cyber-green/20 mb-1">添加角色:</div>
          <div className="flex flex-wrap gap-1">
            {allChars
              .filter(c => !participants.find(p => p.character_id === c.character_id))
              .slice(0, 6)
              .map(c => (
                <button
                  key={c.character_id}
                  onClick={() => handleAddParticipant(c)}
                  className="flex items-center gap-1 text-[10px] border border-cyber-green/10 rounded-full px-2 py-0.5 text-cyber-green/40 hover:border-cyber-green/30 hover:text-cyber-green/70 transition-colors"
                >
                  <Plus size={10} /> {c.name}
                </button>
              ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {error && (
          <div className="text-center text-red-400/60 text-xs p-2 bg-red-500/5 rounded border border-red-500/10">
            {error}
            <button onClick={() => setError(null)} className="ml-2 underline">关闭</button>
          </div>
        )}
        {messages.map((msg, i) => {
          const isUser = msg.role === 'user';
          const charInfo = msg.charId ? getCharById(msg.charId) : null;
          return (
            <div key={i} className={`flex gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
              {isUser ? (
                <div className="w-7 h-7 rounded-full border border-cyber-green/15 bg-cyber-green/5 flex items-center justify-center text-cyber-green/50 shrink-0 mt-0.5">
                  <User size={12} />
                </div>
              ) : (
                <div className="w-7 h-7 rounded-full overflow-hidden border shrink-0 mt-0.5" style={{ borderColor: 'rgba(124,58,237,0.3)' }}>
                  {charInfo?.avatar_url ? (
                    <img src={charInfo.avatar_url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-purple-800/20 text-purple-300/50 text-[9px] font-bold">
                      {charInfo?.name?.charAt(0) || '?'}
                    </div>
                  )}
                </div>
              )}
              <div className={`max-w-[72%] ${isUser ? 'items-end' : 'items-start'}`}>
                {/* Character name for non-user */}
                {!isUser && msg.charName && (
                  <div className="text-[9px] text-cyber-green/30 mb-0.5 ml-1">
                    {msg.charName}
                  </div>
                )}
                <div
                  className={`px-3 py-2 rounded-lg text-sm leading-relaxed whitespace-pre-wrap break-words ${
                    isUser
                      ? 'bg-cyber-green/10 text-cyber-green/90 border border-cyber-green/15 rounded-br-sm'
                      : 'bg-[#12121a] text-zinc-300 border border-white/5 rounded-bl-sm'
                  }`}
                >
                  {msg.content}
                </div>
                {msg.action && (
                  <div className="text-[9px] text-cyber-green/25 mt-0.5 italic ml-1">*{msg.action}*</div>
                )}
              </div>
            </div>
          );
        })}
        {sending && (
          <div className="flex gap-2">
            <div className="w-7 h-7 rounded-full border border-purple-500/20 bg-purple-500/5 flex items-center justify-center shrink-0 mt-0.5">
              <Loader2 className="animate-spin text-cyber-green/40" size={12} />
            </div>
            <div className="bg-[#12121a] border border-white/5 rounded-lg rounded-bl-sm px-3 py-2">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-cyber-green/40 rounded-full animate-pulse" />
                <span className="w-1.5 h-1.5 bg-cyber-green/40 rounded-full animate-pulse" style={{ animationDelay: '0.2s' }} />
                <span className="w-1.5 h-1.5 bg-cyber-green/40 rounded-full animate-pulse" style={{ animationDelay: '0.4s' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Participant avatars strip */}
      <div className="px-4 py-1.5 flex items-center gap-1.5 border-t border-cyber-green/5 overflow-x-auto shrink-0">
        {participants.map(p => (
          <div key={p.character_id} className="flex flex-col items-center gap-0.5 shrink-0" title={p.name}>
            <div className="w-7 h-7 rounded-full overflow-hidden border border-cyber-green/15 bg-[#0d0d14]">
              {p.avatar_url ? (
                <img src={p.avatar_url} alt="" className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-cyber-green/30 text-[8px] font-bold">
                  {p.name?.charAt(0)}
                </div>
              )}
            </div>
            <span className="text-[8px] text-cyber-green/30 truncate max-w-[40px]">{p.name}</span>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="px-4 py-2 border-t border-cyber-green/10 bg-[#0d0d14]/80 shrink-0">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={discussionMode ? '输入消息（讨论模式）...' : '输入消息...'}
            disabled={sending}
            className="flex-1 bg-[#0d0d14] border border-cyber-green/15 rounded-lg px-3 py-2 text-sm text-zinc-300 placeholder:text-cyber-green/20 focus:outline-none focus:border-cyber-green/40 transition-colors disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || sending}
            className="px-3 py-2 bg-cyber-green/10 hover:bg-cyber-green/20 border border-cyber-green/20 rounded-lg text-cyber-green disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

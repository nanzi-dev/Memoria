import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useUser } from '../context/UserContext';
import { dialogue, characterAdmin } from '../api/memoria';
import { Send, ArrowLeft, Heart, Zap, AlertTriangle, Loader2, User, X } from 'lucide-react';

const MOOD_LABELS = {
  happy: '😊 开心',
  neutral: '😐 平静',
  sad: '😢 悲伤',
  angry: '😠 愤怒',
  surprised: '😲 惊讶',
  fearful: '😨 恐惧',
  disgusted: '😖 厌恶',
};

export default function SingleChat() {
  const { characterId } = useParams();
  const navigate = useNavigate();
  const { user } = useUser();
  const PLAYER_ID = user?.user_id || (() => {
    const key = 'memoria-player-id';
    let id = sessionStorage.getItem(key);
    if (!id) {
      id = 'player-' + Math.random().toString(36).slice(2, 8);
      sessionStorage.setItem(key, id);
    }
    return id;
  })();
  const PLAYER_NAME = user?.username || '旅行者';
  const [character, setCharacter] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [affinity, setAffinity] = useState(0);
  const [mood, setMood] = useState('neutral');
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showEvents, setShowEvents] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!characterId) return;
    setLoading(true);
    let sid = null;
    (async () => {
      try {
        const detail = await characterAdmin.get(characterId);
        const cardData = detail.card_data || {};
        setCharacter({
          character_id: characterId,
          name: cardData.meta?.name || detail.display_name || characterId,
          display_name: cardData.meta?.display_name || detail.display_name || characterId,
          avatar_url: detail.avatar_url || null,
          identity: cardData.identity || {},
        });

        const session = await dialogue.startSession(characterId, PLAYER_ID, PLAYER_NAME);
        sid = session.session_id;
        setSessionId(sid);
        if (session.recovered && session.messages?.length) {
          setMessages(session.messages.map(m => ({
            role: m.role,
            content: m.content,
            action: m.action || '',
            affinity_delta: m.affinity_delta || 0,
          })));
        } else if (session.opening_line) {
          setMessages([{ role: 'assistant', content: session.opening_line, action: session.action || '' }]);
        }
        setAffinity(session.current_affinity || 0);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
    return () => {
      if (sid) dialogue.endSession(sid).catch(() => {});
    };
  }, [characterId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (!loading) inputRef.current?.focus();
  }, [loading]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || !sessionId || sending) return;
    setInput('');
    setSending(true);
    const userMsg = { role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    try {
      const res = await dialogue.sendMessage(sessionId, text);
      const botMsg = {
        role: 'assistant',
        content: res.dialogue,
        action: res.action || '',
        affinity_delta: res.affinity_delta || 0,
      };
      setMessages(prev => [...prev, botMsg]);
      setAffinity(res.current_affinity ?? affinity);
      setMood(res.current_mood || 'neutral');
      if (res.triggered_events?.length) {
        setEvents(prev => [
          ...prev,
          ...res.triggered_events.map(e => ({ ...e, id: Date.now() + Math.random() })),
        ]);
      }
      if (res.event_notification) {
        setEvents(prev => [...prev, { id: Date.now() + Math.random(), description: res.event_notification }]);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }, [input, sessionId, sending, affinity]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0b0b0c] flex items-center justify-center">
        <div className="flex items-center gap-3 text-cyber-green/50">
          <Loader2 className="animate-spin" size={24} />
          <span className="font-mono text-sm">正在连接角色...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0b0b0c] flex flex-col font-mono">
      <header className="flex items-center gap-4 px-6 py-3 border-b border-cyber-green/10 bg-[#0d0d14]/80 backdrop-blur shrink-0">
        <button
          onClick={() => navigate('/')}
          className="text-cyber-green/50 hover:text-cyber-green transition-colors p-1"
        >
          <ArrowLeft size={20} />
        </button>
        <div className="w-9 h-9 rounded-full overflow-hidden border border-cyber-green/20 bg-[#0d0d14] shrink-0">
          {character?.avatar_url ? (
            <img src={character.avatar_url} alt="" className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-cyber-green/30 text-sm font-bold">
              {character?.name?.charAt(0) || '?'}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-bold text-cyber-green truncate">{character?.name || characterId}</h1>
          {character?.identity?.core_identity_summary && (
            <p className="text-[10px] text-cyber-green/40 truncate">{character.identity.core_identity_summary}</p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center gap-1.5" title="好感度">
            <Heart size={14} className={affinity > 30 ? 'text-red-400' : affinity < -30 ? 'text-blue-400' : 'text-cyber-green/30'} />
            <span className="text-xs text-cyber-green/60">{affinity}</span>
          </div>
          <div className="flex items-center gap-1.5" title="情绪">
            <Zap size={14} className="text-yellow-400/70" />
            <span className="text-xs text-cyber-green/60">{MOOD_LABELS[mood] || mood}</span>
          </div>
          {events.length > 0 && (
            <button onClick={() => setShowEvents(!showEvents)} className="relative" title="事件通知">
              <AlertTriangle size={14} className="text-amber-400/80" />
              <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-red-500 rounded-full text-[8px] flex items-center justify-center text-white font-bold">
                {events.length}
              </span>
            </button>
          )}
          <Link to="/room" className="text-[10px] text-cyber-green/40 hover:text-cyber-green border border-cyber-green/20 rounded px-2 py-0.5 transition-colors">
            群聊
          </Link>
        </div>
      </header>

      {/* Event notification panel */}
      {showEvents && events.length > 0 && (
        <div className="mx-6 mt-2 p-3 border border-amber-500/20 bg-amber-500/5 rounded-lg">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-amber-400/80">事件通知</span>
            <button onClick={() => { setShowEvents(false); setEvents([]); }} className="text-amber-400/40 hover:text-amber-400">
              <X size={12} />
            </button>
          </div>
          <div className="space-y-1 max-h-28 overflow-y-auto">
            {events.map(e => (
              <div key={e.id} className="text-[10px] text-amber-300/70">
                {e.event_name || e.name || '事件'} — {e.description || ''}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {error && (
          <div className="text-center text-red-400/60 text-xs mb-4 p-2 bg-red-500/5 rounded border border-red-500/10">
            错误: {error}
            <button onClick={() => setError(null)} className="ml-2 underline">关闭</button>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div
              className="w-8 h-8 rounded-full overflow-hidden border shrink-0 mt-0.5"
              style={{ borderColor: msg.role === 'user' ? 'rgba(167,239,158,0.2)' : 'rgba(124,58,237,0.3)' }}
            >
              {msg.role === 'user' ? (
                <div className="w-full h-full flex items-center justify-center bg-cyber-green/5 text-cyber-green/50">
                  <User size={14} />
                </div>
              ) : character?.avatar_url ? (
                <img src={character.avatar_url} alt="" className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-purple-800/20 text-purple-300/60 text-xs font-bold">
                  {character?.name?.charAt(0) || 'C'}
                </div>
              )}
            </div>
            <div className={`max-w-[70%] ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              <div
                className={`px-3 py-2 rounded-lg text-sm leading-relaxed whitespace-pre-wrap break-words ${
                  msg.role === 'user'
                    ? 'bg-cyber-green/10 text-cyber-green/90 border border-cyber-green/15 rounded-br-sm'
                    : 'bg-[#12121a] text-zinc-300 border border-white/5 rounded-bl-sm'
                }`}
              >
                {msg.content}
              </div>
              {msg.action && (
                <div className="text-[10px] text-cyber-green/30 mt-0.5 italic ml-1">*{msg.action}*</div>
              )}
              {msg.affinity_delta !== 0 && msg.affinity_delta != null && (
                <div className={`text-[10px] mt-0.5 ml-1 ${msg.affinity_delta > 0 ? 'text-red-400/50' : 'text-blue-400/50'}`}>
                  好感 {msg.affinity_delta > 0 ? '+' : ''}{msg.affinity_delta}
                </div>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex gap-3">
            <div
              className="w-8 h-8 rounded-full overflow-hidden border shrink-0 mt-0.5"
              style={{ borderColor: 'rgba(124,58,237,0.3)' }}
            >
              {character?.avatar_url ? (
                <img src={character.avatar_url} alt="" className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-purple-800/20 text-purple-300/60 text-xs font-bold">
                  {character?.name?.charAt(0) || 'C'}
                </div>
              )}
            </div>
            <div className="bg-[#12121a] border border-white/5 rounded-lg rounded-bl-sm px-4 py-2.5">
              <Loader2 className="animate-spin text-cyber-green/40" size={16} />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-3 border-t border-cyber-green/10 bg-[#0d0d14]/80 backdrop-blur shrink-0">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder="输入消息..."
            disabled={sending}
            className="flex-1 bg-[#0d0d14] border border-cyber-green/15 rounded-lg px-3 py-2 text-sm text-zinc-300 placeholder:text-cyber-green/20 resize-none focus:outline-none focus:border-cyber-green/40 transition-colors disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || sending}
            className="px-3 py-2 bg-cyber-green/10 hover:bg-cyber-green/20 border border-cyber-green/20 rounded-lg text-cyber-green disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            <Send size={16} />
          </button>
        </div>
        <div className="text-[9px] text-cyber-green/15 mt-1.5 text-center">
          Enter 发送 · Shift+Enter 换行
        </div>
      </div>
    </div>
  );
}

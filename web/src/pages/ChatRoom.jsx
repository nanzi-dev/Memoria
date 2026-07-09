import { useState, useEffect, useRef, useCallback } from 'react';

import { useSearchParams, useNavigate } from 'react-router-dom';

import { useUser } from '../context/UserContext';

import { dialogue, multiDialogue, characterAdmin } from '../api/memoria';

import {

  Send, ArrowLeft, Heart, Zap, AlertTriangle, Loader2, User, X, Plus, Users,

  Radio, Search, Cpu, Activity, TrendingUp, ChevronRight, MessageSquare

} from 'lucide-react';



// ═══════════════════════════════════════════════

// Constants

// ═══════════════════════════════════════════════

const MOOD_LABELS = {

  happy: '开心', neutral: '平静', sad: '悲伤', angry: '愤怒',

  surprised: '惊讶', fearful: '恐惧', disgusted: '厌恶',

};

const MOOD_EMOJI = { happy: '😊', neutral: '😐', sad: '😢', angry: '😠', surprised: '😲', fearful: '😨', disgusted: '😖' };



const MOOD_BORDER = { happy: 'border-emerald-400/60', neutral: 'border-slate-500/40', sad: 'border-blue-400/60', angry: 'border-red-400/60', surprised: 'border-yellow-400/60', fearful: 'border-purple-400/60', disgusted: 'border-orange-400/60' };

const MOOD_GLOW = { happy: 'shadow-[0_0_12px_rgba(52,211,153,0.3)]', neutral: '', sad: 'shadow-[0_0_12px_rgba(96,165,250,0.3)]', angry: 'shadow-[0_0_12px_rgba(248,113,113,0.3)]' };



const STRATEGIES = [

  { value: 'hybrid', label: '智能混合' }, { value: 'round_robin', label: '轮流发言' },

  { value: 'smart', label: '情境感知' }, { value: 'trigger', label: '事件触发' },

];



// ═══════════════════════════════════════════════

// Scanning line animation (for AI thinking)

// ═══════════════════════════════════════════════

function ScanLine() {

  return (

    <div className="absolute inset-0 overflow-hidden pointer-events-none rounded-lg" aria-hidden="true">

      <div className="absolute inset-x-0 h-[2px] bg-gradient-to-r from-transparent via-cyber-green/40 to-transparent animate-scan" />

    </div>

  );

}



// ═══════════════════════════════════════════════

// ChatRoom — Main Container

// ═══════════════════════════════════════════════

export default function ChatRoom() {

  const [searchParams] = useSearchParams();

  const navigate = useNavigate();

  const { user } = useUser();



  const characterIdParam = searchParams.get('character');



  const PLAYER_ID = user?.user_id || (() => {

    const key = 'memoria-player-id';

    let id = sessionStorage.getItem(key);

    if (!id) { id = 'player-' + Math.random().toString(36).slice(2, 8); sessionStorage.setItem(key, id); }

    return id;

  })();

  const PLAYER_NAME = user?.username || '旅行者';



  // ── View state ──

  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'contacts'

  const [view, setView] = useState('list'); // 'list' | 'single-loading' | 'single' | 'group-setup' | 'group'



  // ── Shared state ──

  const [allChars, setAllChars] = useState([]);

  const [chatItems, setChatItems] = useState([]); // session-based chat list

  const [searchQuery, setSearchQuery] = useState('');

  const [error, setError] = useState(null);



  // ── History loading ──

  const [historyOffset, setHistoryOffset] = useState(0);

  const [hasMoreHistory, setHasMoreHistory] = useState(true);

  const [loadingHistory, setLoadingHistory] = useState(false);



  // ── Single chat state ──

  const [character, setCharacter] = useState(null);

  const [singleSessionId, setSingleSessionId] = useState(null);

  const [affinity, setAffinity] = useState(0);

  const [trust, setTrust] = useState(0);

  const [mood, setMood] = useState('neutral');

  const [events, setEvents] = useState([]);



  // ── Group chat state ──

  const [participants, setParticipants] = useState([]);

  const [multiSessionId, setMultiSessionId] = useState(null);

  const [discussionMode, setDiscussionMode] = useState(false);

  const [maxResponses, setMaxResponses] = useState(3);

  const [strategy, setStrategy] = useState('hybrid');



  // ── Chat state ──

  const [messages, setMessages] = useState([]);

  const [input, setInput] = useState('');

  const [sending, setSending] = useState(false);

  const [sendingMulti, setSendingMulti] = useState(false);

  const bottomRef = useRef(null);

  const inputRef = useRef(null);



  // ── Load all characters on mount ──

  useEffect(() => {

    (async () => {

      // Load all characters for contacts + group setup

      try {

        const list = await characterAdmin.list(false);

        const enriched = [];

        for (const c of list) {

          try {

            const detail = await characterAdmin.get(c.character_id);

            const cd = detail.card_data || {};

            enriched.push({

              character_id: c.character_id,

              name: cd.meta?.name || cd.identity?.display_name || c.display_name || c.character_id,

              display_name: cd.meta?.display_name || c.character_id,

              avatar_url: detail.avatar_url || cd.avatar_url || null,

              is_active: c.is_active,

              core_identity: cd.identity?.core_identity_summary || '',

              traits: cd.personality?.traits || [],

              gender: cd.identity?.gender || null,

              age: cd.identity?.age || null,

              race: cd.identity?.race || null,

            });

          } catch {

            enriched.push({ character_id: c.character_id, name: c.display_name || c.character_id, avatar_url: null, is_active: c.is_active });

          }

        }

        enriched.sort((a, b) => (b.is_active ? 1 : 0) - (a.is_active ? 1 : 0));

        setAllChars(enriched);

      } catch (e) { setError(e.message); }

    })();

    loadSessions();

  }, []);



  // ── Load player sessions for chat list ──

  async function loadSessions() {

    try {

      const sessions = await dialogue.listPlayerSessions(PLAYER_ID);

      const items = [];

      for (const s of sessions) {

        if (s.is_multi_character) {

          items.push({ type: 'group', session_id: s.session_id, created_at: s.created_at, last_message: s.last_message, message_count: s.message_count });

        } else {

          try {

            const detail = await characterAdmin.get(s.character_id);

            const cd = detail.card_data || {};

            items.push({

              type: 'single',

              session_id: s.session_id,

              character_id: s.character_id,

              last_message: s.last_message,

              message_count: s.message_count,

              created_at: s.created_at,

              name: cd.meta?.name || cd.identity?.display_name || s.character_id,

              avatar_url: detail.avatar_url || cd.avatar_url || null,

              core_identity: cd.identity?.core_identity_summary || '',

            });

          } catch {

            items.push({ type: 'single', session_id: s.session_id, character_id: s.character_id, last_message: s.last_message, message_count: s.message_count, created_at: s.created_at, name: s.character_id, avatar_url: null });

          }

        }

      }

      setChatItems(items);

    } catch {}

  }



  // ── Auto-scroll ──

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  useEffect(() => { if (view === 'single' || view === 'group') inputRef.current?.focus(); }, [view]);



  // ── Direct single chat from URL param ──

  useEffect(() => {

    if (!characterIdParam || allChars.length === 0) return;

    const c = allChars.find(ch => ch.character_id === characterIdParam);

    if (c) enterSingleChat(c);

  }, [characterIdParam, allChars]);



  // ── Navigation helpers ──

  const goToList = useCallback(() => {

    if (singleSessionId) dialogue.endSession(singleSessionId).catch(() => {});

    if (multiSessionId) multiDialogue.endSession(multiSessionId).catch(() => {});

    setMessages([]); setCharacter(null); setSingleSessionId(null);

    setMultiSessionId(null); setParticipants([]); setAffinity(0); setTrust(0);

    setMood('neutral'); setEvents([]); setView('list'); setError(null);

    setHistoryOffset(0); setHasMoreHistory(true); setLoadingHistory(false);

    loadSessions(); // reload chat list

  }, [singleSessionId, multiSessionId]);



  const enterSingleChat = useCallback(async (char) => {

    setError(null);

    setView('single-loading');

    setCharacter(char);

    try {

      const detail = await characterAdmin.get(char.character_id);

      const cd = detail.card_data || {};

      setCharacter(prev => ({

        ...prev,

        identity: cd.identity || {},

        personality: cd.personality || {},

        traits: cd.personality?.traits || [],

        status_labels: cd.identity?.status_labels || [cd.personality?.core_personality_summary || ''],

      }));

      const session = await dialogue.startSession(char.character_id, PLAYER_ID, PLAYER_NAME);

      setSingleSessionId(session.session_id);

      if (session.opening_line) {

        setMessages([{ role: 'assistant', content: session.opening_line, action: session.action || '' }]);

      }

      setAffinity(session.current_affinity || 0);

      setHistoryOffset(0); setHasMoreHistory(true);

      setView('single');

    } catch (e) { setError(e.message); setView('list'); }

  }, [PLAYER_ID, PLAYER_NAME]);



  const enterGroupSetup = useCallback(() => { setMessages([]); setParticipants([]); setView('group-setup'); }, []);



  // ── Load more history on scroll up ──

  const loadMoreHistory = useCallback(async () => {

    if (loadingHistory || !hasMoreHistory) return;

    if (view === 'single' && character) {

      setLoadingHistory(true);

      try {

        const newOffset = historyOffset + 20;

        const hist = await dialogue.getHistory(character.character_id, PLAYER_ID, newOffset, 20);

        if (hist?.messages && hist.messages.length > 0) {

          setMessages(prev => [...hist.messages.map(m => ({

            role: m.role, content: m.content, action: m.action || '', affinity_delta: m.affinity_delta || 0,

          })), ...prev]);

          setHistoryOffset(newOffset);

          setHasMoreHistory(hist.messages.length >= 20);

        } else {

          setHasMoreHistory(false);

        }

      } catch {} finally { setLoadingHistory(false); }

    }

  }, [historyOffset, PLAYER_ID, view, character]);

  const loadMoreRef = useRef(loadMoreHistory);
  useEffect(() => { loadMoreRef.current = loadMoreHistory; }, [loadMoreHistory]);



  // ── Group: toggle participant ──

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



  const startGroupChat = async () => {

    if (participants.length < 2) { setError('至少选择2个角色'); return; }

    setError(null); setView('single-loading');

    try {

      const freqs = {}; participants.forEach(p => { freqs[p.character_id] = p.frequency; });

      const res = await multiDialogue.startSession(PLAYER_ID, PLAYER_NAME, participants.map(p => p.character_id), strategy, freqs);

      setMultiSessionId(res.session_id);

      if (res.opening?.dialogue) {

        setMessages([{ role: 'assistant', charId: res.opening.character_id, charName: res.opening.character_name || '未知', content: res.opening.dialogue, action: res.opening.action || '' }]);

      }

      setView('group');

    } catch (e) { setError(e.message); setView('group-setup'); }

  };



  // ── Send message ──

  const sendMessage = useCallback(async () => {

    const text = input.trim();

    if (!text || sending || sendingMulti) return;

    setInput(''); setSending(true); setSendingMulti(true);

    setMessages(prev => [...prev, { role: 'user', content: text }]);

    try {

      if (view === 'single') {

        const res = await dialogue.sendMessage(singleSessionId, text);

        setMessages(prev => [...prev, { role: 'assistant', content: res.dialogue, action: res.action || '', affinity_delta: res.affinity_delta || 0 }]);

        setAffinity(res.current_affinity ?? affinity); setMood(res.current_mood || 'neutral');

        if (res.triggered_events?.length || res.event_notification) {

          setEvents(prev => [

            ...prev,

            ...(res.triggered_events || []).map(e => ({ ...e, id: Date.now() + Math.random() })),

            ...(res.event_notification ? [{ id: Date.now() + Math.random() + 1, description: res.event_notification }] : []),

          ]);

        }

      } else if (view === 'group') {

        let res;

        if (discussionMode) {

          res = await multiDialogue.discussMessage(multiSessionId, text, maxResponses, strategy);

          setMessages(prev => [...prev, ...res.responses.map(r => ({

            role: 'assistant', charId: r.character_id, charName: r.character_name || '未知',

            content: r.dialogue, action: r.action || '', affinity_delta: r.affinity_delta || 0,

          }))]);

        } else {

          res = await multiDialogue.sendMessage(multiSessionId, text, strategy);

          setMessages(prev => [...prev, { role: 'assistant', charId: res.character_id, charName: res.character_name || '未知', content: res.dialogue, action: res.action || '', affinity_delta: res.affinity_delta || 0 }]);

        }

      }

    } catch (e) { setError(e.message); }

    finally { setSending(false); setSendingMulti(false); }

  }, [input, sending, sendingMulti, view, singleSessionId, multiSessionId, discussionMode, maxResponses, strategy, affinity]);



  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } };



  // ── Helpers ──

  const getCharById = (id) => participants.find(p => p.character_id === id) || allChars.find(c => c.character_id === id);

  const filteredChars = allChars.filter(c => !searchQuery || c.name.toLowerCase().includes(searchQuery.toLowerCase()));

  const activeChars = filteredChars.filter(c => c.is_active);

  const inactiveChars = filteredChars.filter(c => !c.is_active);



  // ═══════════════════════════════════════════════

  // View: Loading

  // ═══════════════════════════════════════════════

  if (view === 'single-loading') {

    return (

      <div className="min-h-screen bg-[#0b0b0c] flex items-center justify-center font-mono">

        <div className="flex flex-col items-center gap-4">

          <div className="relative w-16 h-16 rounded-full border-2 border-cyber-green/20 flex items-center justify-center overflow-hidden">

            {character?.avatar_url ? (

              <img src={character.avatar_url} alt="" className="w-full h-full object-cover opacity-50" />

            ) : (

              <User size={24} className="text-cyber-green/20" />

            )}

            <ScanLine />

          </div>

          <Loader2 className="animate-spin text-cyber-green/40" size={20} />

          <span className="text-xs text-cyber-green/40">正在连接 {character?.name || '角色'}...</span>

        </div>

      </div>

    );

  }



  // ═══════════════════════════════════════════════

  // View: List (Chat tab / Contacts)
  // ═══════════════════════════════════════════════
  if (view === 'list') {
    return (
      <div className="min-h-screen bg-[#0b0b0c] flex flex-col font-mono">
        <header className="flex items-center gap-3 px-4 py-2.5 border-b border-white/5 bg-[#0d0d14]/80 backdrop-blur-md shrink-0">
          <button onClick={() => navigate('/')} className="text-cyber-green/30 hover:text-cyber-green/50 p-1"><ArrowLeft size={18} /></button>
          <div className="flex items-center gap-2">
            <Activity size={14} className="text-cyber-green/40" />
            <span className="text-xs font-bold text-cyber-green/60 uppercase tracking-[0.15em]">Memoria</span>
            <span className="w-1.5 h-1.5 rounded-full bg-cyber-green/50 animate-pulse ml-1" />
          </div>
          <div className="flex-1 hidden sm:flex items-center justify-center max-w-md mx-auto">
            <div className="relative w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-cyber-green/20" />
              <input type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="搜索对话..." className="w-full bg-[#0b0b0c] border border-white/5 rounded-full pl-9 pr-4 py-2 text-sm text-zinc-300 placeholder:text-cyber-green/15 focus:outline-none focus:border-cyber-green/30 transition-colors" />
            </div>
          </div>
          <button onClick={enterGroupSetup} className="text-xs px-3 py-1.5 rounded-full border border-cyber-green/15 text-cyber-green/35 hover:text-cyber-green/60 hover:border-cyber-green/30 transition-all flex items-center gap-1.5 shrink-0"><Plus size={14} />群聊</button>
        </header>

        <div className="flex items-center gap-1 px-4 py-2 border-b border-white/[0.03] bg-[#0d0d14]/40">
          <button onClick={() => { setActiveTab('chat'); setSearchQuery(''); }} className={`text-xs px-4 py-1.5 rounded-full border transition-all ${activeTab === 'chat' ? 'border-cyber-green/30 bg-cyber-green/10 text-cyber-green' : 'border-transparent text-cyber-green/30 hover:text-cyber-green/50'}`}>对话</button>
          <button onClick={() => { setActiveTab('contacts'); setSearchQuery(''); }} className={`text-xs px-4 py-1.5 rounded-full border transition-all ${activeTab === 'contacts' ? 'border-cyber-green/30 bg-cyber-green/10 text-cyber-green' : 'border-transparent text-cyber-green/30 hover:text-cyber-green/50'}`}>联系人</button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {activeTab === 'chat' && ((() => {
            if (chatItems.length === 0) {
              return (
                <div className="flex flex-col items-center justify-center h-full text-center p-8 space-y-4">
                  <div className="w-16 h-16 rounded-full border-2 border-dashed border-cyber-green/10 flex items-center justify-center">
                    <MessageSquare size={24} className="text-cyber-green/15" />
                  </div>
                  <p className="text-sm text-cyber-green/20 font-mono">暂无对话记录</p>
                  <p className="text-[11px] text-cyber-green/10">切换至联系人标签开始新对话</p>
                </div>
              );
            }
            return (
              <div className="divide-y divide-white/[0.03]">
                {chatItems.filter(item => {
                  if (!searchQuery) return true;
                  const name = item.type === 'single' ? item.name : '';
                  const msg = item.last_message || '';
                  return name.toLowerCase().includes(searchQuery.toLowerCase()) || msg.toLowerCase().includes(searchQuery.toLowerCase());
                }).map((item, i) => {
                  const timeStr = item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN', { month:'short', day:'numeric' }) : '';
                  if (item.type === 'group') {
                    return (
                      <div key={item.session_id || i} onClick={async () => {
                        setMultiSessionId(item.session_id);
                        setView('group');
                        try { const info = await multiDialogue.getSessionInfo(item.session_id); setParticipants(info.participants?.map(p => ({ character_id: p.character_id, name: p.name, avatar_url: p.avatar_url, frequency: p.speak_frequency || 1.0 })) || []); } catch {}
                        try { const hist = await multiDialogue.getHistory(item.session_id); if (hist?.messages) setMessages(hist.messages); } catch {}
                      }} className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-all cursor-pointer group relative">
                        <div className="flex -space-x-2 shrink-0">
                          {[0,1,2].map(j => (
                            <div key={j} className="w-10 h-10 rounded-full overflow-hidden border-2 border-[#0d0d14] bg-[#0b0b0c] ring-1 ring-cyber-green/10">
                              <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[11px] font-bold">{j===0?'群':j===1?'聊':'?'}</div>
                            </div>
                          ))}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5"><span className="text-sm text-zinc-300 font-medium truncate">群聊</span></div>
                          <div className="text-[11px] text-cyber-green/20 truncate mt-0.5">{item.last_message || '点击进入群聊'}</div>
                        </div>
                        <div className="flex flex-col items-end gap-1 shrink-0"><span className="text-[11px] text-cyber-green/15">{timeStr}</span></div>
                        <div className="absolute inset-0 bg-cyber-green/[0.02] opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none rounded" />
                      </div>
                    );
                  }
                  return (
                    <div key={item.session_id || i} onClick={() => enterSingleChat(item)} className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-all cursor-pointer group relative">
                      <div className="w-10 h-10 rounded-full overflow-hidden border-2 border-slate-700/30 bg-[#0b0b0c] shrink-0 group-hover:border-cyber-green/40 transition-colors">
                        {item.avatar_url ? <img src={item.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-sm font-bold">{item.name?.charAt(0)}</div>}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5"><span className="text-sm text-zinc-300 font-medium truncate">{item.name}</span></div>
                        <div className="text-[11px] text-cyber-green/20 truncate mt-0.5">{item.last_message || '点击继续对话'}</div>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className="text-[11px] text-cyber-green/15">{timeStr}</span>
                        {item.message_count > 0 && <span className="w-5 h-5 rounded-full bg-cyber-green/10 flex items-center justify-center text-[10px] text-cyber-green/40 font-bold">{item.message_count > 99 ? '99+' : item.message_count}</span>}
                      </div>
                      <div className="absolute inset-0 bg-cyber-green/[0.02] opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none rounded" />
                    </div>
                  );
                })}
              </div>
            );
          })())}
          {activeTab === 'contacts' && (
            <div className="p-3 space-y-0.5">
              {allChars.filter(c => c.is_active).map(char => (
                <div key={char.character_id} onClick={() => enterSingleChat(char)} className="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-white/[0.02] transition-all cursor-pointer group">
                  <div className="w-10 h-10 rounded-full overflow-hidden border-2 border-slate-700/30 bg-[#0b0b0c] shrink-0 group-hover:border-cyber-green/40 transition-colors">
                    {char.avatar_url ? <img src={char.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-sm font-bold">{char.name?.charAt(0)}</div>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-zinc-300">{char.name}</div>
                    {char.core_identity && <div className="text-[11px] text-cyber-green/20 truncate mt-0.5">{char.core_identity}</div>}
                  </div>
                  <ChevronRight size={14} className="text-cyber-green/15 shrink-0" />
                </div>
              ))}
              {allChars.filter(c => !c.is_active).length > 0 && (
                <div className="pt-3 mt-2 border-t border-white/[0.03]">
                  <div className="text-[10px] text-cyber-green/12 uppercase px-2 mb-1">已禁用</div>
                  {allChars.filter(c => !c.is_active).map(char => (
                    <div key={char.character_id} onClick={() => enterSingleChat(char)} className="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-white/[0.02] transition-all cursor-pointer group opacity-50">
                      <div className="w-10 h-10 rounded-full overflow-hidden border-2 border-slate-700/30 bg-[#0b0b0c] shrink-0">{char.avatar_url ? <img src={char.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/10 text-sm font-bold">{char.name?.charAt(0)}</div>}</div>
                      <div className="flex-1 min-w-0"><div className="text-sm text-zinc-500">{char.name}</div></div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  // View: Group Setup

  // ═══════════════════════════════════════════════

  if (view === 'group-setup') {

    return (

      <div className="min-h-screen bg-[#0b0b0c] flex flex-col font-mono">

        <header className="flex items-center gap-4 px-6 py-3 border-b border-white/5 bg-[#0d0d14]/80 backdrop-blur-md shrink-0">

          <button onClick={goToList} className="text-cyber-green/30 hover:text-cyber-green/50 p-1"><ArrowLeft size={18} /></button>

          <h1 className="text-xs font-bold text-cyber-green/70 uppercase tracking-wider flex items-center gap-2"><Users size={14} />创建群聊</h1>

        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6 max-w-2xl mx-auto w-full space-y-5">

          {error && (

            <div className="flex items-start gap-2 text-[13px] text-red-400/80 bg-red-500/5 border border-red-500/10 rounded-lg px-3 py-2.5">

              <AlertTriangle size={14} className="shrink-0 mt-0.5" /><span>{error}<button onClick={()=>setError(null)} className="ml-2 underline">关闭</button></span>

            </div>

          )}

          {/* Strategy */}

          <div>

            <label className="text-[12px] text-cyber-green/40 uppercase tracking-wider mb-2 block">发言策略</label>

            <div className="flex flex-wrap gap-1.5">

              {STRATEGIES.map(s => (

                <button key={s.value} onClick={()=>setStrategy(s.value)} className={`text-xs px-3 py-1.5 rounded border transition-all ${strategy===s.value ? 'border-cyber-green/40 bg-cyber-green/10 text-cyber-green' : 'border-white/5 text-cyber-green/30 hover:border-cyber-green/20'}`}>{s.label}</button>

              ))}

            </div>

          </div>

          {/* Discussion mode */}

          <div className="flex items-center gap-3">

            <label className="flex items-center gap-2 cursor-pointer">

              <input type="checkbox" checked={discussionMode} onChange={e=>setDiscussionMode(e.target.checked)} className="sr-only peer" />

              <div className="w-8 h-4 rounded-full bg-white/5 border border-white/10 peer-checked:bg-cyber-green/20 peer-checked:border-cyber-green/40 transition-colors relative after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:rounded-full after:bg-cyber-green/40 transition-transform peer-checked:after:translate-x-4" />

              <span className="text-xs text-cyber-green/50">讨论模式</span>

            </label>

            {discussionMode && <select value={maxResponses} onChange={e=>setMaxResponses(Number(e.target.value))} className="text-xs bg-[#0d0d14] border border-white/10 rounded px-2 py-1 text-cyber-green/40">{[1,2,3,4,5].map(n=><option key={n} value={n}>最多{n}人</option>)}</select>}

          </div>

          {/* Character selection */}

          <div>

            <label className="text-[12px] text-cyber-green/40 uppercase tracking-wider mb-2 block">选择角色 ({participants.length}/5)</label>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">

              {allChars.filter(c=>c.is_active).map(char=>{

                const sel = participants.find(p=>p.character_id===char.character_id);

                return (

                  <div key={char.character_id} onClick={()=>toggleParticipant(char)} className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-all ${sel ? 'border-cyber-green/40 bg-cyber-green/5' : 'border-white/5 bg-[#0d0d14] hover:border-cyber-green/15'}`}>

                    <div className="w-8 h-8 rounded-full overflow-hidden border border-white/10 bg-[#0d0d14] shrink-0">

                      {char.avatar_url ? <img src={char.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-xs font-bold">{char.name?.charAt(0)}</div>}

                    </div>

                    <span className="text-xs text-cyber-green/60 truncate flex-1">{char.name}</span>

                    {sel && <div className="text-[12px] flex items-center gap-1"><input type="range" min="0" max="2" step="0.1" value={sel.frequency} onClick={e=>e.stopPropagation()} onChange={e=>{e.stopPropagation(); updateFrequency(char.character_id, parseFloat(e.target.value));}} className="w-10 h-1 accent-cyber-green" /><span className="text-cyber-green/30 w-4 text-right">{sel.frequency.toFixed(1)}</span></div>}

                  </div>

                );

              })}

            </div>

          </div>

          {participants.length>0 && <div className="flex flex-wrap gap-1.5">{participants.map(p=><div key={p.character_id} className="flex items-center gap-1 text-[12px] bg-cyber-green/5 border border-cyber-green/15 rounded-full px-2 py-0.5 text-cyber-green/50">{p.name}<button onClick={()=>toggleParticipant(p)} className="text-cyber-green/20 hover:text-red-400 ml-0.5"><X size={10}/></button></div>)}</div>}

          <button onClick={startGroupChat} disabled={participants.length<2} className="w-full py-2.5 bg-cyber-green/10 hover:bg-cyber-green/20 border border-cyber-green/20 rounded-lg text-sm font-bold text-cyber-green disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"><Users size={16} />开始群聊 ({participants.length}人)</button>

        </div>

      </div>

    );

  }



  // ═══════════════════════════════════════════════

  // View: Single Chat

  // ═══════════════════════════════════════════════

  if (view === 'single') {

    return renderSingleChat();

  }



  // ═══════════════════════════════════════════════

  // View: Group Chat

  // ═══════════════════════════════════════════════

  if (view === 'group') {

    return renderGroupChat();

  }



  return null;



  // ═══════════════════════════════════════════════

  // Single Chat Render

  // ═══════════════════════════════════════════════

  function renderSingleChat() {

    const moodEmoji = MOOD_EMOJI[mood] || '😐';

    const moodBorder = MOOD_BORDER[mood] || 'border-slate-500/40';

    const moodGlow = MOOD_GLOW[mood] || '';

    const affinityPct = Math.round((affinity + 100) / 2);



    return (

      <div className="min-h-screen bg-[#0b0b0c] font-mono">

        {/* Top bar */}

        <header className="flex items-center gap-3 px-4 py-2.5 border-b border-white/5 bg-[#0d0d14]/80 backdrop-blur-md shrink-0">

          <button onClick={goToList} className="text-cyber-green/30 hover:text-cyber-green/50 p-1"><ArrowLeft size={18} /></button>

          <div className={`w-8 h-8 rounded-full overflow-hidden border-2 shrink-0 ${moodBorder} ${moodGlow} transition-all duration-500`}>

            {character?.avatar_url ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-xs font-bold">{character?.name?.charAt(0)}</div>}

          </div>

          <div className="flex-1 min-w-0">

            <h1 className="text-xs font-bold text-zinc-300 truncate">{character?.name}</h1>

            <div className="flex items-center gap-1.5 text-[13px] text-cyber-green/30">

              <span className="w-1.5 h-1.5 rounded-full bg-cyber-green/50 animate-pulse" />

              {sending ? '正在思考...' : '在线'}

            </div>

          </div>

          <div className="flex items-center gap-3 shrink-0">

            <div className="hidden sm:flex items-center gap-1" title="好感度">

              <Heart size={12} className={affinity>30 ? 'text-red-400' : affinity<-30 ? 'text-blue-400' : 'text-cyber-green/20'} />

              <span className="text-[12px] text-cyber-green/40">{affinity}</span>

            </div>

            <div className="hidden sm:flex items-center gap-1" title="情绪">

              <span className="text-sm">{moodEmoji}</span>

              <span className="text-[12px] text-cyber-green/40">{MOOD_LABELS[mood]}</span>

            </div>

            {events.length > 0 && (

              <button onClick={() => setEvents([])} className="relative" title="事件通知">

                <AlertTriangle size={12} className="text-amber-400/70" />

                <span className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full text-[13px] flex items-center justify-center text-white font-bold">{events.length}</span>

              </button>

            )}

          </div>

        </header>



        {/* Two-panel body */}

        <div className="flex h-[calc(100vh-57px)]">

          {/* Left: Character Panel (desktop) */}

          <aside className="hidden lg:flex w-[300px] flex-col border-r border-white/5 bg-[#0d0d14]/60 backdrop-blur-md overflow-y-auto shrink-0">

            <div className="p-5 space-y-5">

              {/* Avatar */}

              <div className="flex flex-col items-center gap-3">

                <div className={`w-20 h-20 rounded-full overflow-hidden border-2 ${moodBorder} ${moodGlow} transition-all duration-500`}>

                  {character?.avatar_url ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20"><User size={32} /></div>}

                </div>

                <div>

                  <h2 className="text-sm font-bold text-zinc-200 text-center">{character?.name}</h2>

                  {character?.identity?.core_identity_summary && (

                    <p className="text-[12px] text-cyber-green/30 text-center mt-0.5">{character.identity.core_identity_summary}</p>

                  )}

                </div>

                {/* Status tags */}

                {character?.status_labels?.length > 0 && (

                  <div className="flex flex-wrap gap-1 justify-center">

                    {character.status_labels.slice(0, 3).map((t,i) => <span key={i} className="text-[13px] px-2 py-0.5 rounded-full bg-cyber-green/5 border border-cyber-green/10 text-cyber-green/40">{t}</span>)}

                  </div>

                )}

              </div>



              {/* RPG Stats */}

              <div className="space-y-4 bg-[#0b0b0c]/60 rounded-xl p-4 border border-white/5">

                <h3 className="text-[13px] text-cyber-green/30 uppercase tracking-[0.2em] flex items-center gap-1.5">

                  <Activity size={10} />角色状态

                </h3>



                {/* Affinity */}

                <div>

                  <div className="flex items-center justify-between mb-1">

                    <span className="text-[12px] text-cyber-green/40 flex items-center gap-1"><Heart size={12} />好感度</span>

                    <span className="text-[12px] text-cyber-green/60">{affinity}</span>

                  </div>

                  <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">

                    <div className="h-full bg-gradient-to-r from-cyber-green/30 to-cyber-green/60 rounded-full transition-all duration-700" style={{ width: `${affinityPct}%` }} />

                  </div>

                  <div className="flex justify-between text-[12px] text-cyber-green/15 mt-0.5"><span>-100</span><span>0</span><span>+100</span></div>

                </div>



                {/* Trust */}

                <div>

                  <div className="flex items-center justify-between mb-1">

                    <span className="text-[12px] text-cyber-green/40 flex items-center gap-1"><TrendingUp size={10} />信任度</span>

                    <span className="text-[12px] text-cyber-green/60 flex items-center gap-1">{trust}</span>

                  </div>

                  <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">

                    <div className="h-full bg-gradient-to-r from-blue-400/30 to-blue-400/60 rounded-full transition-all duration-700" style={{ width: `${trust}%` }} />

                  </div>

                </div>



                {/* Mood */}

                <div className="flex items-center justify-between">

                  <span className="text-[12px] text-cyber-green/40 flex items-center gap-1"><Zap size={12} />当前情绪</span>

                  <span className="text-[12px] text-cyber-green/60 flex items-center gap-1">

                    <span className="text-base">{moodEmoji}</span>

                    {MOOD_LABELS[mood]}

                  </span>

                </div>

              </div>



              {/* Events */}

              {events.length > 0 && (

                <div className="bg-amber-500/[0.03] border border-amber-500/10 rounded-xl p-4">

                  <h3 className="text-[13px] text-amber-400/40 uppercase tracking-[0.2em] mb-2 flex items-center gap-1.5"><AlertTriangle size={10} />事件通知</h3>

                  <div className="space-y-1.5 max-h-32 overflow-y-auto">

                    {events.map(e => <div key={e.id} className="text-[12px] text-amber-300/50">{e.event_name || e.name || '事件'} — {e.description || ''}</div>)}

                  </div>

                  <button onClick={()=>setEvents([])} className="text-[13px] text-amber-400/30 hover:text-amber-400/60 mt-2">清除全部</button>

                </div>

              )}

            </div>

          </aside>



          {/* Right: Chat area */}

          {renderChatArea('single')}

        </div>

      </div>

    );

  }



  // ═══════════════════════════════════════════════

  // Group Chat Render

  // ═══════════════════════════════════════════════

  function renderGroupChat() {

    return (

      <div className="min-h-screen bg-[#0b0b0c] font-mono">

        {/* Top bar */}

        <header className="flex items-center gap-3 px-4 py-2.5 border-b border-white/5 bg-[#0d0d14]/80 backdrop-blur-md shrink-0">

          <button onClick={goToList} className="text-cyber-green/30 hover:text-cyber-green/50 p-1"><ArrowLeft size={18} /></button>

          <div className="flex -space-x-2">

            {participants.slice(0,3).map(p => (

              <div key={p.character_id} className="w-9 h-9 rounded-full overflow-hidden border-2 border-[#0d0d14] bg-[#0b0b0c]">

                {p.avatar_url ? <img src={p.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{p.name?.charAt(0)}</div>}

              </div>

            ))}

          </div>

          <div className="flex-1 min-w-0">

            <h1 className="text-xs font-bold text-zinc-300 truncate">群聊 · {participants.length}人</h1>

            <div className="flex items-center gap-1.5 text-[13px] text-cyber-green/30">

              <span className="w-1.5 h-1.5 rounded-full bg-cyber-green/50 animate-pulse" />

              {sendingMulti ? '角色思考中...' : '在线'}

            </div>

          </div>

          <button onClick={() => setDiscussionMode(!discussionMode)} className={`hidden sm:flex text-[12px] px-2 py-0.5 rounded border transition-colors ${discussionMode ? 'border-purple-400/30 bg-purple-400/10 text-purple-300' : 'border-white/10 text-cyber-green/30'}`}>

            <Radio size={12} className="inline mr-1" />讨论:{discussionMode?'ON':'OFF'}

          </button>

          {discussionMode && (

            <select value={maxResponses} onChange={e=>setMaxResponses(Number(e.target.value))} className="text-[12px] bg-[#0d0d14] border border-white/10 rounded px-1.5 py-0.5 text-cyber-green/30 hidden sm:block">

              {[1,2,3,4,5].map(n=><option key={n} value={n}>{n}人</option>)}

            </select>

          )}

        </header>



        {/* Two-panel body */}

        <div className="flex h-[calc(100vh-57px)]">

          {/* Left: Member Panel */}

          <aside className="hidden lg:flex w-[280px] flex-col border-r border-white/5 bg-[#0d0d14]/60 backdrop-blur-md overflow-y-auto shrink-0">

            <div className="p-4 space-y-3">

              <h3 className="text-[13px] text-cyber-green/30 uppercase tracking-[0.2em] flex items-center gap-1.5"><Users size={10} />群成员 ({participants.length})</h3>

              {participants.map(p => (

                <div key={p.character_id} className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-white/[0.02] transition-colors">

                  <div className="w-9 h-9 rounded-full overflow-hidden border-2 border-white/10 shrink-0">

                    {p.avatar_url ? <img src={p.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{p.name?.charAt(0)}</div>}

                  </div>

                  <div className="flex-1 min-w-0">

                    <div className="text-[13px] text-zinc-300 truncate">{p.name}</div>

                    <div className="flex items-center gap-1 text-[13px] text-cyber-green/20">

                      <span className="w-1 h-1 rounded-full bg-cyber-green/30 animate-pulse" />

                      在线

                    </div>

                  </div>

                  <div className="text-[13px] text-cyber-green/15">{(p.frequency*100).toFixed(0)}%</div>

                </div>

              ))}

            </div>

          </aside>



          {/* Right: Chat area */}

          {renderChatArea('group')}

        </div>

      </div>

    );

  }



  // ═══════════════════════════════════════════════

  // Shared Chat Area

  // ═══════════════════════════════════════════════

  function renderChatArea(mode) {

    return (

      <div className="flex-1 flex flex-col min-w-0">

        {/* Mobile: compact character info */}

        {mode === 'single' && (

          <div className="lg:hidden flex items-center gap-2 px-4 py-2 border-b border-white/5 bg-[#0d0d14]/40">

            <div className={`w-7 h-7 rounded-full overflow-hidden border-2 ${MOOD_BORDER[mood]} shrink-0`}>

              {character?.avatar_url ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{character?.name?.charAt(0)}</div>}

            </div>

            <div className="flex-1 flex items-center gap-3 text-[12px]">

              <span className="text-cyber-green/30 flex items-center gap-1"><Heart size={12} className={affinity>30?'text-red-400':''}/>{affinity}</span>

              <span className="text-cyber-green/30">{MOOD_EMOJI[mood]} {MOOD_LABELS[mood]}</span>

              {/* Affinity bar mobile */}

              <div className="flex-1 max-w-[80px]">

                <div className="h-1 bg-white/5 rounded-full overflow-hidden">

                  <div className="h-full bg-cyber-green/40 rounded-full transition-all" style={{width:`${Math.round((affinity+100)/2)}%`}} />

                </div>

              </div>

            </div>

          </div>

        )}



        {/* Messages */}

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3" onScroll={(e) => {

          if (e.target.scrollTop < 60 && !loadingHistory && hasMoreHistory) loadMoreHistory();

        }}>

          {/* Loading indicator for history */}

          {loadingHistory && (

            <div className="flex justify-center py-2">

              <Loader2 className="animate-spin text-cyber-green/25" size={16} />

            </div>

          )}

          {hasMoreHistory && !loadingHistory && (

            <div className="text-center text-[10px] text-cyber-green/12 py-1">上滑加载更多</div>

          )}

          {error && (

            <div className="text-center text-red-400/50 text-xs p-2 bg-red-500/5 rounded-lg border border-red-500/10">

              {error}<button onClick={()=>setError(null)} className="ml-2 underline">关闭</button>

            </div>

          )}

          {messages.map((msg, i) => {

            const isUser = msg.role === 'user';

            const charInfo = msg.charId ? getCharById(msg.charId) : null;

            return (

              <div key={i} className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}>

                <div className={`w-10 h-10 rounded-full overflow-hidden border-2 shrink-0 mt-0.5 ${isUser ? 'border-cyber-green/10 bg-cyber-green/[0.03] flex items-center justify-center' : 'border-purple-500/15'}`}>

                  {isUser ? (

                    user?.avatar_url ? (

                      <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />

                    ) : user ? (

                      <div className="w-full h-full flex items-center justify-center text-cyber-green/40 text-[13px] font-bold">{user.username?.charAt(0)?.toUpperCase()}</div>

                    ) : (

                      <User size={18} className="text-cyber-green/30" />

                    )

                  ) : charInfo?.avatar_url || mode==='single' && character?.avatar_url ? (

                    <img src={charInfo?.avatar_url || character?.avatar_url} alt="" className="w-full h-full object-cover" />

                  ) : (

                    <div className="w-full h-full flex items-center justify-center bg-purple-800/10 text-purple-300/30 text-[13px] font-bold">

                      {charInfo?.name?.charAt(0) || character?.name?.charAt(0) || '?'}

                    </div>

                  )}

                </div>

                <div className={`max-w-[72%] ${isUser ? 'items-end' : 'items-start'}`}>

                  {!isUser && (msg.charName || mode==='single') && (

                    <div className="text-[13px] text-cyber-green/20 mb-0.5 ml-1">

                      {mode==='single' ? character?.name : msg.charName}

                    </div>

                  )}

                  <div className={`px-3 py-2 rounded-xl text-sm leading-relaxed whitespace-pre-wrap break-words backdrop-blur-sm ${

                    isUser

                      ? 'bg-cyber-green/10 border border-cyber-green/15 rounded-br-sm text-cyber-green/85'

                      : 'bg-white/[0.03] border border-white/[0.06] rounded-bl-sm text-zinc-300'

                  }`}>

                    {msg.content}

                    {/* Scan line on AI messages when sending */}

                    {!isUser && sendingMulti && i === messages.length - 1 && <ScanLine />}

                  </div>

                  {msg.action && (

                    <div className="text-[13px] text-cyber-green/15 mt-0.5 italic ml-1">*{msg.action}*</div>

                  )}

                  {msg.affinity_delta !== 0 && msg.affinity_delta != null && (

                    <div className={`text-[12px] mt-0.5 ml-1 ${msg.affinity_delta>0 ? 'text-red-400/40' : 'text-blue-400/40'}`}>

                      好感 {msg.affinity_delta>0?'+':''}{msg.affinity_delta}

                    </div>

                  )}

                </div>

              </div>

            );

          })}

          {sending && (

            <div className="flex gap-2.5">

              <div className="w-8 h-8 rounded-full overflow-hidden border-2 border-purple-500/10 bg-purple-500/[0.02] flex items-center justify-center shrink-0 mt-0.5 relative">

                <Loader2 className="animate-spin text-cyber-green/25" size={14} />

                <ScanLine />

              </div>

              <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl rounded-bl-sm px-4 py-2.5 relative">

                <div className="flex items-center gap-1.5">

                  <Cpu size={12} className="text-cyber-green/25 animate-pulse" />

                  <span className="text-[13px] text-cyber-green/25">角色思考中</span>

                  <span className="flex gap-1 ml-1">

                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" />

                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" style={{animationDelay:'0.15s'}} />

                    <span className="w-1 h-1 bg-cyber-green/30 rounded-full animate-bounce" style={{animationDelay:'0.3s'}} />

                  </span>

                </div>

                <ScanLine />

              </div>

            </div>

          )}

          <div ref={bottomRef} />

        </div>



        {/* Participant strip (group) */}

        {mode === 'group' && (

          <div className="px-4 py-1.5 flex items-center gap-1.5 border-t border-white/[0.03] overflow-x-auto shrink-0">

            {participants.map(p => (

              <div key={p.character_id} className="flex flex-col items-center gap-0.5 shrink-0" title={p.name}>

                <div className="w-7 h-7 rounded-full overflow-hidden border border-white/5 bg-[#0d0d14]">

                  {p.avatar_url ? <img src={p.avatar_url} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-cyber-green/20 text-[12px] font-bold">{p.name?.charAt(0)}</div>}

                </div>

                <span className="text-[12px] text-cyber-green/15 truncate max-w-[40px]">{p.name}</span>

              </div>

            ))}

          </div>

        )}



        {/* Input */}

        <div className="px-4 py-2.5 border-t border-white/5 bg-[#0d0d14]/60 backdrop-blur-md shrink-0">

          <div className="flex gap-2">

            <textarea

              ref={inputRef}

              value={input}

              onChange={e => setInput(e.target.value)}

              onKeyDown={handleKeyDown}

              rows={1}

              placeholder="输入消息..."

              disabled={sending || sendingMulti}

              className="flex-1 bg-[#0b0b0c] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-zinc-300 placeholder:text-cyber-green/10 resize-none focus:outline-none focus:border-cyber-green/30 transition-colors disabled:opacity-40"

            />

            <button

              onClick={sendMessage}

              disabled={!input.trim() || sending || sendingMulti}

              className="px-4 py-2.5 bg-cyber-green/10 hover:bg-cyber-green/[0.18] active:scale-95 border border-cyber-green/20 rounded-xl text-cyber-green disabled:opacity-20 disabled:cursor-not-allowed disabled:active:scale-100 transition-all shrink-0 min-w-[44px]"

            >

              <Send size={16} />

            </button>

          </div>

          <div className="text-[12px] text-cyber-green/10 mt-1.5 text-center">Enter 发送 · Shift+Enter 换行</div>

        </div>

      </div>

    );

  }

}

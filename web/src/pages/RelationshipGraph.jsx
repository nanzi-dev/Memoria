import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import * as d3 from 'd3';
import { relationshipAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import { useUser } from '../context/UserContext';
import SideRays from '../components/SideRays';
import { characterEditorPath } from '../utils/navigationState';
import { createTimeoutController } from '../utils/timeoutController';
import {
  ArrowLeft, Loader2, RefreshCw, ZoomIn, ZoomOut, Maximize2,
  Users, Plus, Trash2, X, Link2
} from 'lucide-react';

const CYBER_GREEN = '#A7EF9E';
const PLAYER_CYAN = '#67E8F9';
const CYBER_SURFACE = '#120F17';

const GRAPH_RAYS_PROPS = {
  speed: 2.2,
  rayColor1: '#FFD166',
  rayColor2: '#9AD7FF',
  intensity: 4.2,
  spread: 2.65,
  origin: 'top-right',
  tilt: -12,
  saturation: 1.55,
  blend: 0.58,
  falloff: 1.08,
  opacity: 1,
};

const RELATION_TYPE_STORAGE_KEY = 'memoria.relationshipTypes';
const RELATION_TYPE_COLORS = [
  '#A7EF9E', '#EF4444', '#F59E0B', '#F97316', '#7C3AED',
  '#F472B6', '#94A3B8', '#38BDF8', '#22C55E', '#EAB308',
  '#FB7185', '#A78BFA',
];

const DEFAULT_RELATION_TYPES = [
  { value: 'friend', label: '朋友', color: '#A7EF9E' },
  { value: 'enemy', label: '敌人', color: '#EF4444' },
  { value: 'family', label: '家人', color: '#F59E0B' },
  { value: 'rival', label: '对手', color: '#F97316' },
  { value: 'mentor', label: '导师', color: '#7C3AED' },
  { value: 'love', label: '恋人', color: '#F472B6' },
  { value: 'neutral', label: '中立', color: '#94A3B8' },
];

function hashRelationType(value = '') {
  return Array.from(String(value)).reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
}

function relationTypeColor(value = '') {
  return RELATION_TYPE_COLORS[hashRelationType(value) % RELATION_TYPE_COLORS.length] || '#94A3B8';
}

function normalizeRelationTypeName(value) {
  return String(value || '').trim();
}

function sanitizeMarkerId(type) {
  return `arrow-${String(type || 'relation').replace(/[^a-zA-Z0-9_-]/g, '_')}-${hashRelationType(type)}`;
}

function loadRelationTypes() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RELATION_TYPE_STORAGE_KEY) || 'null');
    if (Array.isArray(parsed)) {
      return parsed
        .map((item) => ({
          value: normalizeRelationTypeName(item.value || item.label),
          label: normalizeRelationTypeName(item.label || item.value),
          color: item.color || relationTypeColor(item.value || item.label),
        }))
        .filter(item => item.value && item.label);
    }
  } catch (e) {}
  return DEFAULT_RELATION_TYPES;
}

function mergeRelationTypes(baseTypes, edges = []) {
  const map = new Map();
  baseTypes.forEach((type) => {
    if (type?.value) map.set(type.value, type);
  });
  edges.forEach((edge) => {
    const value = normalizeRelationTypeName(edge.relationship_type);
    if (value && !map.has(value)) {
      map.set(value, { value, label: value, color: relationTypeColor(value) });
    }
  });
  return Array.from(map.values());
}

function getRelationColor(type, relationTypes) {
  return relationTypes.find(t => t.value === type)?.color || relationTypeColor(type);
}

const NODE_R = 36;

function getAffinityMagnitude(affinity = 0) {
  const value = Math.abs(Number(affinity) || 0);
  return Math.min(100, Math.max(0, value));
}

function getLinkWidth(edge) {
  return 1.6 + (getAffinityMagnitude(edge.affinity) / 100) * 4.2;
}

function getLinkHoverWidth(edge) {
  return getLinkWidth(edge) + 1.4;
}

function RelationTypePicker({
  value,
  onChange,
  relationTypes,
  usedTypeValues,
  onAddType,
  onRemoveType,
}) {
  const [newType, setNewType] = useState('');

  const handleAdd = () => {
    const label = normalizeRelationTypeName(newType);
    if (!label) return;
    const nextType = onAddType(label);
    onChange(nextType.value);
    setNewType('');
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {relationTypes.map(rt => {
          const isUsed = usedTypeValues.has(rt.value);
          return (
            <div
              key={rt.value}
              className="group inline-flex min-h-11 overflow-hidden rounded-lg border font-mono transition-all"
              style={{
                backgroundColor: value === rt.value ? rt.color + '22' : 'transparent',
                borderColor: rt.color,
                color: value === rt.value ? rt.color : 'rgba(255,255,255,0.4)',
              }}
            >
              <button
                type="button"
                onClick={() => onChange(rt.value)}
                aria-pressed={value === rt.value}
                className="min-h-11 px-2.5 text-[10px] transition-colors hover:bg-white/[0.04]"
              >
                {rt.label}
              </button>
              <button
                type="button"
                disabled={isUsed}
                aria-label={`删除关系类型 ${rt.label}`}
                title={isUsed ? '已有关系正在使用，先修改或删除对应关系' : '删除类型'}
                onClick={(e) => {
                  const next = relationTypes.find(item => item.value !== rt.value)?.value || '';
                  if (value === rt.value) onChange(next);
                  onRemoveType(rt.value);
                }}
                className="flex min-h-11 w-9 items-center justify-center border-l border-white/10 opacity-40 transition-colors hover:bg-white/10 hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-20"
              >
                <X size={12} />
              </button>
            </div>
          );
        })}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={newType}
          onChange={e => setNewType(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault();
              handleAdd();
            }
          }}
          placeholder="新增类型，如：同门、债主、守护者"
          className="min-h-11 min-w-0 flex-1 rounded-lg border border-cyber-green/20 bg-cyber-bg px-3 py-2 text-xs font-mono text-cyber-green placeholder:text-cyber-green/20 transition-all focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10"
        />
        <button
          type="button"
          onClick={handleAdd}
          className="inline-flex min-h-11 items-center gap-1 rounded-lg border border-cyber-green/25 bg-cyber-green/10 px-3 text-xs font-bold text-cyber-green transition-all hover:bg-cyber-green/20 active:scale-[0.98]"
        >
          <Plus size={13} /> 新增
        </button>
      </div>
    </div>
  );
}

// ── 添加关系弹窗 ──
function AddRelationModal({ characters, relationTypes, usedTypeValues, onAddType, onRemoveType, onAdd, onClose, adding }) {
  const [charA, setCharA] = useState('');
  const [charB, setCharB] = useState('');
  const [type, setType] = useState(relationTypes[0]?.value || '');
  const [affinity, setAffinity] = useState(50);
  const [desc, setDesc] = useState('');
  const isPlayerRelation = [charA, charB].some(
    characterId => characters.find(character => character.character_id === characterId)?.node_type === 'player'
  );

  useEffect(() => {
    if (!type && relationTypes[0]?.value) setType(relationTypes[0].value);
  }, [relationTypes, type]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!charA || !charB || charA === charB || !type) return;
    onAdd({ character_id_a: charA, character_id_b: charB, relationship_type: type, affinity, description: desc || null });
  };

  const opts = characters.map(c => (
    <option key={c.character_id} value={c.character_id}>
      {c.node_type === 'player' ? '[玩家] ' : ''}{c.display_name || c.name}
    </option>
  ));

  return createPortal(
    <div className="fixed inset-0 z-[1000] flex min-h-screen items-center justify-center overflow-y-auto p-4 font-mono" onClick={onClose}>
      <div className="fixed inset-0 bg-[#05070a]/90 backdrop-blur-md backdrop-saturate-75" />
      <div
        className="relative w-full max-w-md overflow-hidden rounded-lg border border-cyber-green/20 bg-[#0d0d14]/95 shadow-[0_0_70px_rgba(167,239,158,0.08)] animate-fade-up"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-relation-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="absolute inset-0 pointer-events-none opacity-[0.04]" style={{
          backgroundImage: 'linear-gradient(#A7EF9E 1px, transparent 1px), linear-gradient(90deg, #A7EF9E 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }} />
        <div className="relative flex items-center justify-between border-b border-white/[0.04] px-5 py-4">
          <div>
            <h2 id="add-relation-title" className="font-display text-sm text-cyber-green tracking-widest flex items-center gap-2">
              <Link2 size={16} /> NEW RELATIONSHIP
            </h2>
            <p className="mt-1 text-[10px] text-cyber-green/30">建立两个角色之间的图谱连接</p>
          </div>
          <button onClick={onClose} className="flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/30 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green/70" aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="relative space-y-4 px-5 py-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">角色 A</label>
              <select value={charA} onChange={e => setCharA(e.target.value)}
                className="min-h-11 w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 transition-all">
                <option value="">选择...</option>
                {opts}
              </select>
            </div>
            <div>
              <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">角色 B</label>
              <select value={charB} onChange={e => setCharB(e.target.value)}
                className="min-h-11 w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 transition-all">
                <option value="">选择...</option>
                {opts}
              </select>
            </div>
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">关系类型</label>
            <RelationTypePicker
              value={type}
              onChange={setType}
              relationTypes={relationTypes}
              usedTypeValues={usedTypeValues}
              onAddType={onAddType}
              onRemoveType={onRemoveType}
            />
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">
              {isPlayerRelation ? '好感度' : '亲密度'}: {affinity}
            </label>
            <input type="range" min="-100" max="100" value={affinity}
              onChange={e => setAffinity(Number(e.target.value))}
              className="w-full accent-cyber-green" />
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">描述（可选）</label>
            <input type="text" value={desc} onChange={e => setDesc(e.target.value)}
              placeholder="如：青梅竹马、宿敌..."
              className="min-h-11 w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 placeholder:text-cyber-green/20 transition-all" />
          </div>
          <button type="submit" disabled={adding || !charA || !charB || charA === charB || !type}
            className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/10 py-2.5 text-sm font-bold text-cyber-green transition-all hover:bg-cyber-green/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-30 disabled:active:scale-100">
            {adding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {adding ? '创建中...' : '创建关系'}
          </button>
        </form>
      </div>
    </div>,
    document.body
  );
}

// ── 编辑/删除关系弹窗 ──
function EditRelationModal({ edge, relationTypes, usedTypeValues, onAddType, onRemoveType, onUpdate, onDelete, onClose, saving }) {
  const [type, setType] = useState(edge.relationship_type);
  const [affinity, setAffinity] = useState(edge.affinity);
  const [desc, setDesc] = useState(edge.description || '');

  const sourceName = edge.source?.display_name || edge.source?.name || edge.source;
  const targetName = edge.target?.display_name || edge.target?.name || edge.target;
  const isPlayerRelation = edge.source?.node_type === 'player' || edge.target?.node_type === 'player';

  return createPortal(
    <div className="fixed inset-0 z-[1000] flex min-h-screen items-center justify-center overflow-y-auto p-4 font-mono" onClick={onClose}>
      <div className="fixed inset-0 bg-[#05070a]/90 backdrop-blur-md backdrop-saturate-75" />
      <div
        className="relative w-full max-w-md overflow-hidden rounded-lg border border-cyber-green/20 bg-[#0d0d14]/95 shadow-[0_0_70px_rgba(167,239,158,0.08)] animate-fade-up"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-relation-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="absolute inset-0 pointer-events-none opacity-[0.04]" style={{
          backgroundImage: 'linear-gradient(#A7EF9E 1px, transparent 1px), linear-gradient(90deg, #A7EF9E 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }} />
        <div className="relative flex items-center justify-between border-b border-white/[0.04] px-5 py-4">
          <div>
            <h2 id="edit-relation-title" className="font-display text-sm text-cyber-green tracking-widest flex items-center gap-2">
              <Link2 size={16} /> EDIT RELATIONSHIP
            </h2>
            <p className="mt-1 text-[10px] text-cyber-green/30">调整图谱连接属性</p>
          </div>
          <button onClick={onClose} className="flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/30 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green/70" aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <div className="relative space-y-4 px-5 py-5">
          <p className="rounded-lg border border-cyber-green/10 bg-cyber-green/[0.03] px-3 py-2 text-xs text-cyber-green/55">
            {sourceName} ↔ {targetName}
          </p>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">关系类型</label>
            <RelationTypePicker
              value={type}
              onChange={setType}
              relationTypes={relationTypes}
              usedTypeValues={usedTypeValues}
              onAddType={onAddType}
              onRemoveType={onRemoveType}
            />
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">
              {isPlayerRelation ? '好感度' : '亲密度'}: {affinity}
            </label>
            <input type="range" min="-100" max="100" value={affinity}
              onChange={e => setAffinity(Number(e.target.value))}
              className="w-full accent-cyber-green" />
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">描述</label>
            <input type="text" value={desc} onChange={e => setDesc(e.target.value)}
              className="min-h-11 w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 transition-all" />
          </div>
          <div className="flex gap-3">
            <button onClick={() => onUpdate(edge, { relationship_type: type, affinity, description: desc || null })}
              disabled={saving || !type}
              className="min-h-11 flex-1 rounded-lg border border-cyber-green/30 bg-cyber-green/10 py-2 text-sm font-bold text-cyber-green transition-all hover:bg-cyber-green/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-30 disabled:active:scale-100">
              {saving ? '保存中...' : '保存修改'}
            </button>
            <button onClick={() => onDelete(edge)}
              disabled={saving}
              className="flex min-h-11 items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-bold text-red-400 transition-all hover:bg-red-500/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-30 disabled:active:scale-100">
              <Trash2 size={14} /> 删除
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default function RelationshipGraph() {
  const navigate = useNavigate();
  const dialog = useDialog();
  const { user, loading: userLoading } = useUser();
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const simulationRef = useRef(null);
  const zoomRef = useRef(null);
  const loadRequestRef = useRef(0);
  const centerTimeoutRef = useRef(null);
  const toastTimeoutRef = useRef(null);
  if (!centerTimeoutRef.current) centerTimeoutRef.current = createTimeoutController();
  if (!toastTimeoutRef.current) toastTimeoutRef.current = createTimeoutController();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [network, setNetwork] = useState({ nodes: [], edges: [] });
  const [characters, setCharacters] = useState([]);
  const [graphSize, setGraphSize] = useState({ width: 0, height: 0 });
  const [relationTypes, setRelationTypes] = useState(loadRelationTypes);

  const [showAddModal, setShowAddModal] = useState(false);
  const [editEdge, setEditEdge] = useState(null);
  const [activeRelationType, setActiveRelationType] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    localStorage.setItem(RELATION_TYPE_STORAGE_KEY, JSON.stringify(relationTypes));
  }, [relationTypes]);

  useEffect(() => () => {
    centerTimeoutRef.current.cancel();
    toastTimeoutRef.current.cancel();
  }, []);

  const loadData = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    if (userLoading) {
      setLoading(true);
      return;
    }
    if (!user) {
      setCharacters([]);
      setNetwork({ nodes: [], edges: [] });
      setError('未提供认证信息');
      setLoading(false);
      return;
    }

    try {
      setLoading(true); setError(null);
      const netData = await relationshipAdmin.network();
      if (loadRequestRef.current !== requestId) return;
      const nodes = (netData.nodes || []).map(node => ({
        character_id: node.character_id,
        node_type: node.node_type || 'character',
        name: node.name || node.character_id,
        display_name: node.name || node.character_id,
        avatar_url: node.avatar_url || null,
        is_active: node.is_active ?? true,
      }));
      setCharacters(nodes);
      setNetwork({ nodes, edges: netData.edges || [] });
      setRelationTypes(prev => mergeRelationTypes(prev, netData.edges));
    } catch (e) {
      if (loadRequestRef.current !== requestId) return;
      setError(e.message);
    } finally {
      if (loadRequestRef.current === requestId) setLoading(false);
    }
  }, [userLoading, user?.user_id]);

  useEffect(() => {
    loadData();
    return () => { loadRequestRef.current += 1; };
  }, [loadData]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const updateSize = () => {
      const rect = container.getBoundingClientRect();
      const width = Math.round(rect.width);
      const height = Math.round(rect.height);
      if (!width || !height) return;
      setGraphSize(current => (
        current.width === width && current.height === height
          ? current
          : { width, height }
      ));
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // ── D3 渲染 ──
  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;
    const svg = d3.select(svgRef.current);
    const container = containerRef.current;
    const W = graphSize.width || container.clientWidth;
    const H = graphSize.height || container.clientHeight;
    if (!W || !H) return;

    if (simulationRef.current) {
      simulationRef.current.stop();
      simulationRef.current = null;
    }

    svg.on('.zoom', null).on('click', null);
    svg.selectAll('*').remove();
    svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', W).attr('height', H);

    if (!network.nodes.length) return;

    const defs = svg.append('defs');

    // 箭头标记
    const markerTypes = Array.from(new Set([
      ...relationTypes.map(rt => rt.value),
      ...network.edges.map(edge => edge.relationship_type),
    ])).filter(Boolean);
    markerTypes.forEach(type => {
      defs.append('marker').attr('id', sanitizeMarkerId(type))
        .attr('viewBox', '0 -5 10 10').attr('refX', 30).attr('refY', 0).attr('orient', 'auto')
        .attr('markerWidth', 5).attr('markerHeight', 5)
        .append('path').attr('d', 'M 0,-4 L 8,0 L 0,4').attr('fill', getRelationColor(type, relationTypes)).attr('opacity', 0.82);
    });

    // 发光滤镜
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', 3).attr('result', 'blur');
    filter.append('feMerge').selectAll('feMergeNode').data(['blur', 'SourceGraphic'])
      .join('feMergeNode').attr('in', d => d);

    // 缩放
    const g = svg.append('g');
    const zoom = d3.zoom().scaleExtent([0.15, 5]).on('zoom', e => g.attr('transform', e.transform));
    svg.call(zoom);
    zoomRef.current = zoom;

    // 节点数据
    const nodes = network.nodes.map(n => ({ ...n }));
    const links = network.edges.map(e => ({
      source: nodes.find(n => n.character_id === e.source),
      target: nodes.find(n => n.character_id === e.target),
      relationship_type: e.relationship_type,
      affinity: e.affinity,
      description: e.description,
    })).filter(l => l.source && l.target);

    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.character_id).distance(200).strength(0.3))
      .force('charge', d3.forceManyBody().strength(-800))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(NODE_R + 24))
      .force('x', d3.forceX(W / 2).strength(0.02))
      .force('y', d3.forceY(H / 2).strength(0.02));
    simulationRef.current = simulation;

    const getEdgePath = d => {
      const sx = d.source.x, sy = d.source.y;
      const tx = d.target.x, ty = d.target.y;
      const dr = Math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2);
      return `M${sx},${sy}A${dr * 0.8},${dr * 0.8} 0 0,1 ${tx},${ty}`;
    };

    // ── 边：可见曲线 + 流动高光 + 透明命中区域 ──
    const linkGroup = g.append('g').attr('class', 'links');
    const linkBase = linkGroup.append('g').attr('class', 'link-base').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('stroke', d => getRelationColor(d.relationship_type, relationTypes))
      .attr('stroke-opacity', 0.48)
      .attr('stroke-width', getLinkWidth)
      .attr('stroke-linecap', 'round')
      .attr('stroke-linejoin', 'round')
      .attr('marker-end', d => `url(#${sanitizeMarkerId(d.relationship_type)})`)
      .attr('pointer-events', 'none');

    const linkFlow = linkGroup.append('g').attr('class', 'link-flow').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('stroke', d => getRelationColor(d.relationship_type, relationTypes))
      .attr('stroke-opacity', 0.72)
      .attr('stroke-width', d => Math.max(1, getLinkWidth(d) * 0.42))
      .attr('stroke-linecap', 'round')
      .attr('stroke-dasharray', '2 12')
      .attr('stroke-dashoffset', 0)
      .attr('filter', 'url(#glow)')
      .attr('pointer-events', 'none');

    const linkHit = linkGroup.append('g').attr('class', 'link-hit').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('stroke', 'transparent')
      .attr('stroke-width', d => Math.max(18, getLinkWidth(d) + 14))
      .attr('stroke-linecap', 'round')
      .attr('pointer-events', 'stroke')
      .style('cursor', 'pointer');

    let flowStopped = false;
    const animateFlow = () => {
      if (flowStopped) return;
      linkFlow
        .attr('stroke-dashoffset', 0)
        .transition()
        .duration(1200)
        .ease(d3.easeLinear)
        .attr('stroke-dashoffset', -28)
        .on('end', () => {
          if (!flowStopped) animateFlow();
        });
    };

    animateFlow();

    // 边交互
    linkHit.on('mouseenter', function(event, d) {
      setActiveRelationType(d.relationship_type || null);
      linkBase
        .attr('stroke-opacity', l => l === d ? 0.8 : 0.1)
        .attr('stroke-width', l => l === d ? getLinkHoverWidth(l) : getLinkWidth(l));
      linkFlow
        .attr('stroke-opacity', l => l === d ? 0.95 : 0.04)
        .attr('stroke-width', l => l === d ? Math.max(1.6, getLinkHoverWidth(l) * 0.48) : Math.max(1, getLinkWidth(l) * 0.32));
    }).on('mouseleave', function() {
      setActiveRelationType(null);
      linkBase.attr('stroke-opacity', 0.48).attr('stroke-width', getLinkWidth);
      linkFlow
        .attr('stroke-opacity', 0.72)
        .attr('stroke-width', d => Math.max(1, getLinkWidth(d) * 0.42));
    }).on('click', (event, d) => {
      event.stopPropagation();
      setEditEdge(d);
    });

    // ── 节点 ──
    const nodeGroup = g.append('g').attr('class', 'nodes');
    const node = nodeGroup.selectAll('g').data(nodes).join('g')
      .attr('opacity', 0)
      .attr('cursor', 'pointer')
      .call(d3.drag()
        .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }))
      .on('dblclick', (event, d) => {
        event.stopPropagation();
        navigate(d.node_type === 'player' ? '/persona' : characterEditorPath(d.character_id));
      });

    node.transition().delay((d, i) => Math.min(i, 16) * 45).duration(360).ease(d3.easeCubicOut).attr('opacity', 1);

    // 光晕
    node.append('circle').attr('r', NODE_R + 10).attr('fill', d => d.node_type === 'player' ? PLAYER_CYAN : CYBER_GREEN)
      .attr('opacity', 0).attr('class', 'node-halo').attr('filter', 'url(#glow)');

    // 头像裁剪定义（在 defs 中定义，避免重复id冲突）
    nodes.forEach(function(d) {
      const clipId = 'clip-' + d.character_id.replace(/[^a-zA-Z0-9]/g, '_');
      if (defs.select('#' + clipId).empty()) {
        defs.append('clipPath').attr('id', clipId)
          .append('circle').attr('r', NODE_R - 2);
      }
    });

    // 节点：头像或首字母
    node.each(function(d) {
      const g = d3.select(this);
      const clipId = 'clip-' + d.character_id.replace(/[^a-zA-Z0-9]/g, '_');
      // 圆形底色
      g.append('circle').attr('r', NODE_R - 2).attr('fill', CYBER_SURFACE).attr('pointer-events', 'none');
      if (d.avatar_url) {
        g.append('image')
          .attr('href', d.avatar_url)
          .attr('x', -(NODE_R - 2)).attr('y', -(NODE_R - 2))
          .attr('width', (NODE_R - 2) * 2).attr('height', (NODE_R - 2) * 2)
          .attr('clip-path', 'url(#' + clipId + ')')
          .attr('preserveAspectRatio', 'xMidYMid slice')
          .attr('pointer-events', 'none');
      } else {
        g.append('text')
          .text((d.name || d.display_name || d.character_id).charAt(0))
          .attr('text-anchor', 'middle').attr('dy', '0.35em')
          .attr('fill', d.node_type === 'player' ? PLAYER_CYAN : CYBER_GREEN).attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
          .attr('font-size', '18px').attr('font-weight', 'bold')
          .attr('pointer-events', 'none');
      }
    });

    // 主体圆（描边）
    node.append('circle').attr('r', NODE_R)
      .attr('fill', 'none')
      .attr('stroke', d => d.node_type === 'player' ? PLAYER_CYAN : (d.is_active ? CYBER_GREEN : '#EF4444'))
      .attr('stroke-width', d => d.is_active ? 2.4 : 2.8)
      .attr('stroke-opacity', 0.9);

    // 装饰虚线环
    node.append('circle').attr('r', NODE_R - 4).attr('fill', 'none')
      .attr('stroke', d => d.node_type === 'player' ? PLAYER_CYAN : CYBER_GREEN).attr('stroke-opacity', 0.26).attr('stroke-width', 1)
      .attr('stroke-dasharray', '3 6');

    const playerBadge = node.filter(d => d.node_type === 'player');
    playerBadge.append('rect')
      .attr('x', -19).attr('y', -NODE_R - 19)
      .attr('width', 38).attr('height', 16).attr('rx', 4)
      .attr('fill', '#071417').attr('stroke', PLAYER_CYAN).attr('stroke-opacity', 0.55);
    playerBadge.append('text')
      .text('玩家')
      .attr('text-anchor', 'middle').attr('dy', -NODE_R - 8)
      .attr('fill', PLAYER_CYAN).attr('font-size', '9px').attr('font-weight', '700')
      .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
      .attr('pointer-events', 'none');

    // 名称
    node.append('text')
      .text(d => d.name || d.display_name || d.character_id)
      .attr('text-anchor', 'middle').attr('dy', NODE_R + 18)
      .attr('fill', d => d.node_type === 'player' ? PLAYER_CYAN : CYBER_GREEN).attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
      .attr('font-size', '14px').attr('font-weight', '500')
      .attr('opacity', 0.92).attr('pointer-events', 'none');

    // 悬停高亮
    node.on('mouseenter', (event, d) => {
      node.select('.node-halo').attr('opacity', n => n.character_id === d.character_id ? 0.25 : 0);
      linkBase
        .attr('stroke-opacity', l => (l.source.character_id === d.character_id || l.target.character_id === d.character_id) ? 0.8 : 0.04)
        .attr('stroke-width', l => (l.source.character_id === d.character_id || l.target.character_id === d.character_id)
          ? getLinkHoverWidth(l) : Math.max(0.8, getLinkWidth(l) * 0.55));
      linkFlow
        .attr('stroke-opacity', l => (l.source.character_id === d.character_id || l.target.character_id === d.character_id) ? 0.95 : 0.03)
        .attr('stroke-width', l => (l.source.character_id === d.character_id || l.target.character_id === d.character_id)
          ? Math.max(1.6, getLinkHoverWidth(l) * 0.48) : Math.max(0.8, getLinkWidth(l) * 0.24));
    });
    node.on('mouseleave', () => {
      node.select('.node-halo').attr('opacity', 0);
      linkBase.attr('stroke-opacity', 0.48).attr('stroke-width', getLinkWidth);
      linkFlow
        .attr('stroke-opacity', 0.72)
        .attr('stroke-width', d => Math.max(1, getLinkWidth(d) * 0.42));
    });

    svg.on('click', () => { setEditEdge(null); });

    // tick
    simulation.on('tick', () => {
      linkBase.attr('d', getEdgePath);
      linkFlow.attr('d', getEdgePath);
      linkHit.attr('d', getEdgePath);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // 初始居中
    centerTimeoutRef.current.schedule(() => {
      const bounds = g.node()?.getBBox();
      if (bounds && bounds.width > 0) {
        const scale = Math.min(W * 0.8 / bounds.width, H * 0.8 / bounds.height, 1.2);
        const tx = (W - bounds.width * scale) / 2 - bounds.x * scale;
        const ty = (H - bounds.height * scale) / 2 - bounds.y * scale;
        svg.transition().duration(800).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
      }
    }, 1200);

    return () => {
      flowStopped = true;
      linkFlow.interrupt();
      setActiveRelationType(null);
      simulation.stop();
      centerTimeoutRef.current.cancel();
    };
  }, [graphSize.height, graphSize.width, network, navigate, relationTypes]);

  // ── 操作 ──
  const showToast = (msg) => {
    setToast(msg);
    toastTimeoutRef.current.schedule(() => setToast(null), 2500);
  };

  const handleAdd = async (data) => {
    setSaving(true);
    try {
      await relationshipAdmin.save(data);
      showToast('关系创建成功');
      setShowAddModal(false);
      await loadData();
    } catch (e) { showToast('创建失败: ' + e.message); }
    finally { setSaving(false); }
  };

  const handleUpdate = async (edge, data) => {
    setSaving(true);
    try {
      await relationshipAdmin.update(edge.source.character_id, edge.target.character_id, data);
      showToast('关系已更新');
      setEditEdge(null);
      await loadData();
    } catch (e) { showToast('更新失败: ' + e.message); }
    finally { setSaving(false); }
  };

  const handleDelete = async (edge) => {
    const sn = edge.source?.display_name || edge.source?.name;
    const tn = edge.target?.display_name || edge.target?.name;
    const isPlayerRelation = edge.source?.node_type === 'player' || edge.target?.node_type === 'player';
    const ok = await dialog.confirm({
      title: '删除关系',
      message: isPlayerRelation
        ? `确定删除「${sn}」与「${tn}」之间的关系吗？运行时好感度将重置为 0，信任与心情状态保留。`
        : `确定删除「${sn}」与「${tn}」之间的关系吗？`,
      variant: 'danger',
      confirmText: '删除',
    });
    if (!ok) return;
    setSaving(true);
    try {
      await relationshipAdmin.remove(edge.source.character_id, edge.target.character_id);
      showToast('关系已删除');
      setEditEdge(null);
      await loadData();
    } catch (e) { showToast('删除失败: ' + e.message); }
    finally { setSaving(false); }
  };

  const handleAddRelationType = (label) => {
    const cleanLabel = normalizeRelationTypeName(label);
    const existing = relationTypes.find(
      type => type.value === cleanLabel || type.label === cleanLabel
    );
    if (existing) return existing;

    const nextType = {
      value: cleanLabel,
      label: cleanLabel,
      color: relationTypeColor(cleanLabel),
    };
    setRelationTypes(types => [...types, nextType]);
    return nextType;
  };

  const handleRemoveRelationType = (value) => {
    setRelationTypes(types => types.filter(type => type.value !== value));
  };

  const zoomIn = () => {
    const svg = d3.select(svgRef.current);
    svg.transition().duration(300).call(zoomRef.current.scaleBy, 1.4);
  };
  const zoomOut = () => {
    const svg = d3.select(svgRef.current);
    svg.transition().duration(300).call(zoomRef.current.scaleBy, 0.7);
  };
  const zoomReset = () => {
    const svg = d3.select(svgRef.current);
    svg.transition().duration(500).call(zoomRef.current.transform, d3.zoomIdentity);
  };

  // ── Render ──
  const modalOpen = showAddModal || !!editEdge;
  const usedTypeValues = new Set(network.edges.map(edge => edge.relationship_type).filter(Boolean));
  const isAuthError = !!error && /认证|未登录|401|token/i.test(error);

  return (
    <div className="min-h-dvh memoria-page memoria-app-page flex flex-col select-none">
      {toast && createPortal(
        <div
          role="status"
          className="pointer-events-none fixed left-1/2 top-5 z-[1100] -translate-x-1/2 rounded-lg border border-cyber-green/30 bg-[#07100a]/95 px-4 py-2 font-mono text-xs text-cyber-green shadow-[0_0_28px_rgba(167,239,158,0.16)] backdrop-blur-md animate-fade-up"
        >
          {toast}
        </div>,
        document.body
      )}
      {showAddModal && (
        <AddRelationModal
          characters={characters}
          relationTypes={relationTypes}
          usedTypeValues={usedTypeValues}
          onAddType={handleAddRelationType}
          onRemoveType={handleRemoveRelationType}
          onAdd={handleAdd}
          onClose={() => setShowAddModal(false)}
          adding={saving}
        />
      )}
      {editEdge && (
        <EditRelationModal
          edge={editEdge}
          relationTypes={relationTypes}
          usedTypeValues={usedTypeValues}
          onAddType={handleAddRelationType}
          onRemoveType={handleRemoveRelationType}
          onUpdate={handleUpdate}
          onDelete={handleDelete}
          onClose={() => setEditEdge(null)}
          saving={saving}
        />
      )}

      {/* Header */}
      <div className="memoria-app-header sticky top-0 z-20 border-b">
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-3 py-2.5 sm:px-5 sm:py-3">
          <button onClick={() => navigate('/')}
            aria-label="返回首页"
            title="返回首页"
            className="flex h-11 w-11 items-center justify-center gap-1.5 rounded-lg text-cyber-green/50 transition-all hover:bg-cyber-green/5 hover:text-cyber-green sm:w-auto sm:px-2 sm:font-mono sm:text-sm">
            <ArrowLeft size={16} /> <span className="hidden sm:inline">Back</span>
          </button>
          <h1 className="flex min-w-0 items-center justify-center gap-1.5 whitespace-nowrap font-display text-[11px] tracking-[0.08em] text-cyber-green sm:gap-2 sm:text-base sm:tracking-[0.2em]">
            <Users size={18} className="hidden shrink-0 sm:block" /> RELATIONSHIP GRAPH
          </h1>
          <div className="flex items-center gap-1.5 sm:gap-2">
            <span className="text-[10px] font-mono text-cyber-green/30 hidden sm:inline">
              {characters.length} 角色 · {network.edges.length} 边
            </span>
            <button onClick={() => setShowAddModal(true)}
              disabled={!user || loading}
              aria-label="添加关系"
              title="添加关系"
              className="flex h-11 w-11 items-center justify-center gap-1 rounded-lg border border-cyber-green/25 bg-cyber-green/10 font-mono text-xs text-cyber-green transition-all hover:bg-cyber-green/20 hover:shadow-[0_0_22px_rgba(167,239,158,0.12)] active:scale-95 disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-cyber-green/10 disabled:hover:shadow-none disabled:active:scale-100 sm:w-auto sm:px-3">
              <Plus size={14} /> <span className="hidden sm:inline">添加关系</span>
            </button>
            <button onClick={loadData} disabled={loading}
              className="flex h-11 w-11 items-center justify-center rounded-lg border border-cyber-green/15 font-mono text-xs text-cyber-green/40 transition-all hover:bg-cyber-green/5 hover:text-cyber-green disabled:opacity-30"
              aria-label="刷新关系图"
              title="刷新关系图">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 relative">
        {!modalOpen && <SideRays {...GRAPH_RAYS_PROPS} className="side-rays-graph" />}
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-cyber-bg/80 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="animate-spin text-cyber-green" size={30} />
              <span className="font-mono text-xs text-cyber-green/50">加载关系网络...</span>
            </div>
          </div>
        )}
        {error && (
          <div className="absolute inset-x-4 top-4 z-10 flex justify-center">
            <div className="flex w-full max-w-xl flex-col gap-3 rounded-lg border border-red-400/18 bg-red-400/[0.055] px-4 py-3 text-center shadow-[0_0_32px_rgba(248,113,113,0.08)] backdrop-blur-sm animate-fade-up sm:flex-row sm:items-center sm:justify-between sm:text-left">
              <p className="text-sm font-mono text-red-200/80">{error}</p>
              <button
                onClick={isAuthError ? () => navigate('/') : loadData}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-red-300/20 px-3 text-xs font-mono text-red-200/80 transition-all hover:bg-red-400/10"
              >
                {isAuthError ? '返回首页登录' : '重试'}
              </button>
            </div>
          </div>
        )}
        {!loading && !error && network.nodes.length === 0 && (
          <div className="absolute inset-0 z-10 flex items-center justify-center">
            <div className="memoria-glass animate-fade-up text-center rounded-lg px-8 py-7">
              <Users size={56} className="mx-auto text-cyber-green/10 mb-5" />
              <p className="font-mono text-sm text-cyber-green/30 mb-2">暂无关系数据</p>
              <p className="font-mono text-[11px] text-cyber-green/15 mb-6">创建至少两个角色后，可在此构建关系图谱</p>
              <button onClick={() => setShowAddModal(true)}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-cyber-green/25 bg-cyber-green/10 px-4 py-2 font-mono text-xs text-cyber-green/70 transition-all hover:bg-cyber-green/20 active:scale-95">
                <Plus size={14} /> 添加第一条关系
              </button>
            </div>
          </div>
        )}
        <div ref={containerRef} className="absolute inset-0 z-[1]">
          <svg ref={svgRef} className="w-full h-full" />
        </div>

        {/* 浮动控件 */}
        {!loading && network.nodes.length > 0 && (
          <>
            <div className="absolute bottom-3 right-3 z-10 flex flex-col gap-1.5 animate-fade-up sm:bottom-6 sm:right-6">
              <button onClick={zoomIn} className="memoria-glass flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 active:scale-95 transition-all" title="放大" aria-label="放大关系图">
                <ZoomIn size={16} />
              </button>
              <button onClick={zoomOut} className="memoria-glass flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 active:scale-95 transition-all" title="缩小" aria-label="缩小关系图">
                <ZoomOut size={16} />
              </button>
              <button onClick={zoomReset} className="memoria-glass flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 active:scale-95 transition-all" title="重置" aria-label="重置关系图缩放">
                <Maximize2 size={16} />
              </button>
            </div>
            <div className="absolute bottom-3 left-3 right-[4.5rem] z-10 animate-fade-up sm:bottom-6 sm:left-6 sm:right-24 lg:right-auto lg:w-[min(48rem,calc(100%-7.5rem))]">
              <div className="memoria-glass max-h-40 overflow-y-auto overscroll-contain rounded-lg p-2 font-mono text-[10px] sm:max-h-32 sm:p-2.5">
                <div className="grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-1">
                {relationTypes.map(rt => {
                  const active = activeRelationType === rt.value;
                  const dimmed = activeRelationType && !active;
                  return (
                    <div
                      key={rt.value}
                      className={[
                        'flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1.5 transition-all duration-200',
                        active
                          ? 'border-cyber-green/45 bg-cyber-green/10 text-cyber-green shadow-[0_0_18px_rgba(167,239,158,0.16)] scale-[1.03]'
                          : 'border-transparent text-cyber-green/50',
                        dimmed ? 'opacity-35' : 'opacity-100',
                      ].join(' ')}
                      style={active ? { borderColor: `${rt.color}99`, boxShadow: `0 0 18px ${rt.color}2b` } : undefined}
                    >
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full transition-all duration-200"
                        style={{ backgroundColor: rt.color, boxShadow: active ? `0 0 12px ${rt.color}` : 'none' }}
                      />
                      <span className="truncate" title={rt.label}>{rt.label}</span>
                    </div>
                  );
                })}
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {!loading && network.nodes.length > 0 && (
        <div className="text-center py-2 border-t border-cyber-green/5 bg-[#0d0d14]/40 backdrop-blur-sm">
          <span className="text-[10px] font-mono text-cyber-green/15">
            拖拽节点 · 滚轮缩放 · 悬停高亮 · 点击边编辑 · 双击编辑节点
          </span>
        </div>
      )}
    </div>
  );
}

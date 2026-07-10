import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import * as d3 from 'd3';
import { characterAdmin, relationshipAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import SideRays from '../components/SideRays';
import {
  ArrowLeft, Loader2, RefreshCw, ZoomIn, ZoomOut, Maximize2,
  Users, Plus, Trash2, X, Link2, Heart, Zap
} from 'lucide-react';

const CYBER_GREEN = '#A7EF9E';
const CYBER_BG = '#0b0b0c';
const CYBER_SURFACE = '#120F17';
const CYBER_DARK = '#0a0a0e';

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

const RELATION_TYPES = [
  { value: 'friend', label: '朋友', color: '#A7EF9E' },
  { value: 'enemy', label: '敌人', color: '#EF4444' },
  { value: 'family', label: '家人', color: '#F59E0B' },
  { value: 'rival', label: '对手', color: '#F97316' },
  { value: 'mentor', label: '导师', color: '#7C3AED' },
  { value: 'love', label: '恋人', color: '#F472B6' },
  { value: 'neutral', label: '中立', color: '#94A3B8' },
];

const RELATION_COLORS = Object.fromEntries(RELATION_TYPES.map(t => [t.value, t.color]));
function getRelationColor(type) { return RELATION_COLORS[type] || '#94A3B8'; }
function getRelationLabel(type) { return RELATION_TYPES.find(t => t.value === type)?.label || type; }

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

// ── 添加关系弹窗 ──
function AddRelationModal({ characters, onAdd, onClose, adding }) {
  const [charA, setCharA] = useState('');
  const [charB, setCharB] = useState('');
  const [type, setType] = useState('friend');
  const [affinity, setAffinity] = useState(50);
  const [desc, setDesc] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!charA || !charB || charA === charB) return;
    onAdd({ character_id_a: charA, character_id_b: charB, relationship_type: type, affinity, description: desc || null });
  };

  const opts = characters.map(c => (
    <option key={c.character_id} value={c.character_id}>{c.display_name || c.name}</option>
  ));

  return createPortal(
    <div className="fixed inset-0 z-[1000] flex min-h-screen items-center justify-center overflow-y-auto p-4 font-mono" onClick={onClose}>
      <div className="fixed inset-0 bg-[#05070a]/90 backdrop-blur-md backdrop-saturate-75" />
      <div
        className="relative w-full max-w-md overflow-hidden rounded-xl border border-cyber-green/20 bg-[#0d0d14]/95 shadow-[0_0_70px_rgba(167,239,158,0.08)] animate-fade-up"
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
          <button onClick={onClose} className="rounded-full p-1 text-cyber-green/30 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green/70" aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="relative space-y-4 px-5 py-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">角色 A</label>
              <select value={charA} onChange={e => setCharA(e.target.value)}
                className="w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 transition-all">
                <option value="">选择...</option>
                {opts}
              </select>
            </div>
            <div>
              <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">角色 B</label>
              <select value={charB} onChange={e => setCharB(e.target.value)}
                className="w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 transition-all">
                <option value="">选择...</option>
                {opts}
              </select>
            </div>
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">关系类型</label>
            <div className="flex flex-wrap gap-1.5">
              {RELATION_TYPES.map(rt => (
                <button key={rt.value} type="button"
                  onClick={() => setType(rt.value)}
                  className="px-2.5 py-1.5 rounded-lg text-[10px] font-mono border transition-all active:scale-[0.98]"
                  style={{
                    backgroundColor: type === rt.value ? rt.color + '22' : 'transparent',
                    borderColor: rt.color,
                    color: type === rt.value ? rt.color : 'rgba(255,255,255,0.4)',
                  }}
                >
                  {rt.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">
              亲密度: {affinity}
            </label>
            <input type="range" min="-100" max="100" value={affinity}
              onChange={e => setAffinity(Number(e.target.value))}
              className="w-full accent-cyber-green" />
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">描述（可选）</label>
            <input type="text" value={desc} onChange={e => setDesc(e.target.value)}
              placeholder="如：青梅竹马、宿敌..."
              className="w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 placeholder:text-cyber-green/20 transition-all" />
          </div>
          <button type="submit" disabled={adding || !charA || !charB || charA === charB}
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
function EditRelationModal({ edge, onUpdate, onDelete, onClose, saving }) {
  const [type, setType] = useState(edge.relationship_type);
  const [affinity, setAffinity] = useState(edge.affinity);
  const [desc, setDesc] = useState(edge.description || '');

  const sourceName = edge.source?.display_name || edge.source?.name || edge.source;
  const targetName = edge.target?.display_name || edge.target?.name || edge.target;

  return createPortal(
    <div className="fixed inset-0 z-[1000] flex min-h-screen items-center justify-center overflow-y-auto p-4 font-mono" onClick={onClose}>
      <div className="fixed inset-0 bg-[#05070a]/90 backdrop-blur-md backdrop-saturate-75" />
      <div
        className="relative w-full max-w-md overflow-hidden rounded-xl border border-cyber-green/20 bg-[#0d0d14]/95 shadow-[0_0_70px_rgba(167,239,158,0.08)] animate-fade-up"
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
          <button onClick={onClose} className="rounded-full p-1 text-cyber-green/30 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green/70" aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <div className="relative space-y-4 px-5 py-5">
          <p className="rounded-lg border border-cyber-green/10 bg-cyber-green/[0.03] px-3 py-2 text-xs text-cyber-green/55">
            {sourceName} ↔ {targetName}
          </p>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">关系类型</label>
            <div className="flex flex-wrap gap-1.5">
              {RELATION_TYPES.map(rt => (
                <button key={rt.value} type="button"
                  onClick={() => setType(rt.value)}
                  className="px-2.5 py-1.5 rounded-lg text-[10px] font-mono border transition-all active:scale-[0.98]"
                  style={{
                    backgroundColor: type === rt.value ? rt.color + '22' : 'transparent',
                    borderColor: rt.color,
                    color: type === rt.value ? rt.color : 'rgba(255,255,255,0.4)',
                  }}
                >
                  {rt.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">
              亲密度: {affinity}
            </label>
            <input type="range" min="-100" max="100" value={affinity}
              onChange={e => setAffinity(Number(e.target.value))}
              className="w-full accent-cyber-green" />
          </div>
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">描述</label>
            <input type="text" value={desc} onChange={e => setDesc(e.target.value)}
              className="w-full bg-cyber-bg border border-cyber-green/20 rounded-lg px-3 py-2.5 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none focus:ring-2 focus:ring-cyber-green/10 transition-all" />
          </div>
          <div className="flex gap-3">
            <button onClick={() => onUpdate(edge, { relationship_type: type, affinity, description: desc || null })}
              disabled={saving}
              className="min-h-[42px] flex-1 rounded-lg border border-cyber-green/30 bg-cyber-green/10 py-2 text-sm font-bold text-cyber-green transition-all hover:bg-cyber-green/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-30 disabled:active:scale-100">
              {saving ? '保存中...' : '保存修改'}
            </button>
            <button onClick={() => onDelete(edge)}
              disabled={saving}
              className="flex min-h-[42px] items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-bold text-red-400 transition-all hover:bg-red-500/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-30 disabled:active:scale-100">
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
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const simulationRef = useRef(null);
  const zoomRef = useRef(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [network, setNetwork] = useState({ nodes: [], edges: [] });
  const [characters, setCharacters] = useState([]);

  const [showAddModal, setShowAddModal] = useState(false);
  const [editEdge, setEditEdge] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true); setError(null);
      const charList = await characterAdmin.list(false);
      const netData = await relationshipAdmin.network();
      const map = {};
      for (const c of charList) {
        map[c.character_id] = {
          character_id: c.character_id, avatar_url: c.avatar_url || null,
          name: c.name || c.display_name || c.character_id,
          display_name: c.name || c.display_name || c.character_id,
          is_active: !!c.is_active,
        };
      }
      const enrichedNodes = netData.nodes.map(n => ({
        ...n,
        name: map[n.character_id]?.name || n.name || n.character_id,
        display_name: map[n.character_id]?.name || map[n.character_id]?.display_name || n.name || n.character_id,
        avatar_url: map[n.character_id]?.avatar_url || null,
        is_active: map[n.character_id]?.is_active ?? true,
      }));
      setCharacters(Object.values(map));
      setNetwork({ nodes: enrichedNodes, edges: netData.edges });
    } catch (e) {
      setError(e.message);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ── D3 渲染 ──
  useEffect(() => {
    if (!network.nodes.length || !svgRef.current || !containerRef.current) return;
    if (simulationRef.current) simulationRef.current.stop();

    const svg = d3.select(svgRef.current);
    const container = containerRef.current;
    const W = container.clientWidth;
    const H = container.clientHeight;
    svg.selectAll('*').remove();
    svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', W).attr('height', H);

    const defs = svg.append('defs');

    // 箭头标记
    RELATION_TYPES.forEach(rt => {
      defs.append('marker').attr('id', 'arrow-' + rt.value)
        .attr('viewBox', '0 -5 10 10').attr('refX', 30).attr('refY', 0).attr('orient', 'auto')
        .attr('markerWidth', 5).attr('markerHeight', 5)
        .append('path').attr('d', 'M 0,-4 L 8,0 L 0,4').attr('fill', rt.color).attr('opacity', 0.82);
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
      .attr('stroke', d => getRelationColor(d.relationship_type))
      .attr('stroke-opacity', 0.48)
      .attr('stroke-width', getLinkWidth)
      .attr('stroke-linecap', 'round')
      .attr('stroke-linejoin', 'round')
      .attr('marker-end', d => `url(#arrow-${d.relationship_type})`)
      .attr('pointer-events', 'none');

    const linkFlow = linkGroup.append('g').attr('class', 'link-flow').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('stroke', d => getRelationColor(d.relationship_type))
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

    // 边标签
    const edgeLabelGroup = g.append('g').attr('class', 'edge-labels');
    const edgeLabelBg = edgeLabelGroup.selectAll('rect').data(links).join('rect')
      .attr('fill', CYBER_DARK).attr('rx', 3).attr('opacity', 0)
      .attr('pointer-events', 'none');
    const edgeLabelText = edgeLabelGroup.selectAll('text').data(links).join('text')
      .text(d => getRelationLabel(d.relationship_type))
      .attr('font-family', 'JetBrains Mono, monospace').attr('font-size', '9px')
      .attr('fill', d => getRelationColor(d.relationship_type))
      .attr('text-anchor', 'middle').attr('dy', '-6').attr('opacity', 0)
      .attr('pointer-events', 'none');

    // 边交互
    linkHit.on('mouseenter', function(event, d) {
      linkBase
        .attr('stroke-opacity', l => l === d ? 0.8 : 0.1)
        .attr('stroke-width', l => l === d ? getLinkHoverWidth(l) : getLinkWidth(l));
      linkFlow
        .attr('stroke-opacity', l => l === d ? 0.95 : 0.04)
        .attr('stroke-width', l => l === d ? Math.max(1.6, getLinkHoverWidth(l) * 0.48) : Math.max(1, getLinkWidth(l) * 0.32));
      edgeLabelBg.attr('opacity', l => l === d ? 0.9 : 0);
      edgeLabelText.attr('opacity', l => l === d ? 1 : 0);
    }).on('mouseleave', function() {
      linkBase.attr('stroke-opacity', 0.48).attr('stroke-width', getLinkWidth);
      linkFlow
        .attr('stroke-opacity', 0.72)
        .attr('stroke-width', d => Math.max(1, getLinkWidth(d) * 0.42));
      edgeLabelBg.attr('opacity', 0);
      edgeLabelText.attr('opacity', 0);
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
        navigate(`/editor/${d.character_id}`);
      });

    node.transition().delay((d, i) => Math.min(i, 16) * 45).duration(360).ease(d3.easeCubicOut).attr('opacity', 1);

    // 光晕
    node.append('circle').attr('r', NODE_R + 10).attr('fill', CYBER_GREEN)
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
          .attr('fill', CYBER_GREEN).attr('font-family', 'ZCOOL XiaoWei, Noto Serif SC, serif')
          .attr('font-size', '18px').attr('font-weight', 'bold')
          .attr('pointer-events', 'none');
      }
    });

    // 主体圆（描边）
    node.append('circle').attr('r', NODE_R)
      .attr('fill', 'none')
      .attr('stroke', d => d.is_active ? CYBER_GREEN : '#EF4444')
      .attr('stroke-width', d => d.is_active ? 2.4 : 2.8)
      .attr('stroke-opacity', 0.9);

    // 装饰虚线环
    node.append('circle').attr('r', NODE_R - 4).attr('fill', 'none')
      .attr('stroke', CYBER_GREEN).attr('stroke-opacity', 0.26).attr('stroke-width', 1)
      .attr('stroke-dasharray', '3 6');

    // 名称
    node.append('text')
      .text(d => d.name || d.display_name || d.character_id)
      .attr('text-anchor', 'middle').attr('dy', NODE_R + 18)
      .attr('fill', CYBER_GREEN).attr('font-family', 'ZCOOL XiaoWei, Noto Serif SC, serif')
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
      edgeLabelBg.each(function(d) {
        const mx = (d.source.x + d.target.x) / 2;
        const my = (d.source.y + d.target.y) / 2;
        const label = getRelationLabel(d.relationship_type);
        const w = label.length * 7 + 8;
        d3.select(this).attr('x', mx - w/2).attr('y', my - 14).attr('width', w).attr('height', 16);
      });
      edgeLabelText.attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // 初始居中
    setTimeout(() => {
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
      simulation.stop();
    };
  }, [network, navigate]);

  // ── 操作 ──
  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2500); };

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
    const ok = await dialog.confirm({
      title: '删除关系',
      message: `确定删除「${sn}」与「${tn}」之间的关系吗？`,
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

  return (
    <div className="min-h-screen memoria-page flex flex-col select-none">
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
        <AddRelationModal characters={characters} onAdd={handleAdd} onClose={() => setShowAddModal(false)} adding={saving} />
      )}
      {editEdge && (
        <EditRelationModal edge={editEdge} onUpdate={handleUpdate} onDelete={handleDelete} onClose={() => setEditEdge(null)} saving={saving} />
      )}

      {/* Header */}
      <div className="sticky top-0 z-20 memoria-glass border-x-0 border-t-0">
        <div className="flex items-center justify-between px-5 py-3">
          <button onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-cyber-green/50 hover:text-cyber-green hover:bg-cyber-green/5 rounded-lg px-2 py-2 transition-all font-mono text-sm">
            <ArrowLeft size={16} /> Back
          </button>
          <h1 className="font-display text-base text-cyber-green tracking-[0.2em] flex items-center gap-2">
            <Users size={18} /> RELATIONSHIP GRAPH
          </h1>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-cyber-green/30 hidden sm:inline">
              {characters.length} 角色 · {network.edges.length} 边
            </span>
            <button onClick={() => setShowAddModal(true)}
              className="flex items-center gap-1 px-3 py-1.5 bg-cyber-green/10 border border-cyber-green/25 text-cyber-green font-mono text-xs rounded-lg hover:bg-cyber-green/20 hover:shadow-[0_0_22px_rgba(167,239,158,0.12)] active:scale-95 transition-all">
              <Plus size={13} /> 添加关系
            </button>
            <button onClick={loadData} disabled={loading}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-mono text-cyber-green/40 hover:text-cyber-green hover:bg-cyber-green/5 border border-cyber-green/15 rounded-lg transition-all disabled:opacity-30">
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
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
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 px-4 py-2 bg-red-900/80 text-red-300 font-mono text-xs rounded-lg border border-red-400/20 animate-fade-up">
            错误: {error}
          </div>
        )}
        {!loading && network.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="memoria-glass animate-fade-up text-center rounded-xl px-8 py-7">
              <Users size={56} className="mx-auto text-cyber-green/10 mb-5" />
              <p className="font-mono text-sm text-cyber-green/30 mb-2">暂无关系数据</p>
              <p className="font-mono text-[11px] text-cyber-green/15 mb-6">创建至少两个角色后，可在此构建关系图谱</p>
              <button onClick={() => setShowAddModal(true)}
                className="px-4 py-2 bg-cyber-green/10 border border-cyber-green/25 text-cyber-green/70 font-mono text-xs rounded-lg hover:bg-cyber-green/20 active:scale-95 transition-all inline-flex items-center gap-1.5">
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
            <div className="absolute bottom-6 right-6 flex flex-col gap-1.5 z-10 animate-fade-up">
              <button onClick={zoomIn} className="memoria-glass p-2.5 rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 active:scale-95 transition-all" title="放大">
                <ZoomIn size={16} />
              </button>
              <button onClick={zoomOut} className="memoria-glass p-2.5 rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 active:scale-95 transition-all" title="缩小">
                <ZoomOut size={16} />
              </button>
              <button onClick={zoomReset} className="memoria-glass p-2.5 rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 active:scale-95 transition-all" title="重置">
                <Maximize2 size={16} />
              </button>
            </div>
            <div className="absolute bottom-6 left-6 z-10 animate-fade-up">
              <div className="memoria-glass rounded-lg px-3 py-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px]">
                {RELATION_TYPES.map(rt => (
                  <div key={rt.value} className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: rt.color }} />
                    <span className="text-cyber-green/50">{rt.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {!loading && network.nodes.length > 0 && (
        <div className="text-center py-2 border-t border-cyber-green/5 bg-[#0d0d14]/40 backdrop-blur-sm">
          <span className="text-[10px] font-mono text-cyber-green/15">
            拖拽节点 · 滚轮缩放 · 悬停高亮 · 点击边编辑 · 双击编辑角色
          </span>
        </div>
      )}
    </div>
  );
}

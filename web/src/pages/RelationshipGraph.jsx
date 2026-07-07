import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import * as d3 from 'd3';
import { characterAdmin, relationshipAdmin } from '../api/memoria';
import {
  ArrowLeft, Loader2, RefreshCw, ZoomIn, ZoomOut, Maximize2,
  Users, Plus, Trash2, X, Link2, Heart, Zap
} from 'lucide-react';

const CYBER_GREEN = '#A7EF9E';
const CYBER_BG = '#0b0b0c';
const CYBER_SURFACE = '#120F17';
const CYBER_DARK = '#0a0a0e';

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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-cyber-surface border border-cyber-green/20 rounded-lg p-6 w-full max-w-md shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-display text-sm text-cyber-green tracking-widest flex items-center gap-2">
            <Link2 size={16} /> NEW RELATIONSHIP
          </h2>
          <button onClick={onClose} className="text-cyber-green/40 hover:text-cyber-green transition-colors">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">角色 A</label>
              <select value={charA} onChange={e => setCharA(e.target.value)}
                className="w-full bg-cyber-bg border border-cyber-green/20 rounded px-3 py-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none">
                <option value="">选择...</option>
                {opts}
              </select>
            </div>
            <div>
              <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">角色 B</label>
              <select value={charB} onChange={e => setCharB(e.target.value)}
                className="w-full bg-cyber-bg border border-cyber-green/20 rounded px-3 py-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none">
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
                  className="px-2.5 py-1 rounded text-[10px] font-mono border transition-all"
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
              className="w-full bg-cyber-bg border border-cyber-green/20 rounded px-3 py-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none placeholder:text-cyber-green/20" />
          </div>
          <button type="submit" disabled={adding || !charA || !charB || charA === charB}
            className="w-full py-2.5 bg-cyber-green/10 border border-cyber-green/30 text-cyber-green font-mono text-sm rounded hover:bg-cyber-green/20 disabled:opacity-30 transition-colors flex items-center justify-center gap-2">
            {adding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {adding ? '创建中...' : '创建关系'}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── 编辑/删除关系弹窗 ──
function EditRelationModal({ edge, onUpdate, onDelete, onClose, saving }) {
  const [type, setType] = useState(edge.relationship_type);
  const [affinity, setAffinity] = useState(edge.affinity);
  const [desc, setDesc] = useState(edge.description || '');

  const sourceName = edge.source?.display_name || edge.source?.name || edge.source;
  const targetName = edge.target?.display_name || edge.target?.name || edge.target;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-cyber-surface border border-cyber-green/20 rounded-lg p-6 w-full max-w-md shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-display text-sm text-cyber-green tracking-widest flex items-center gap-2">
            <Link2 size={16} /> EDIT RELATIONSHIP
          </h2>
          <button onClick={onClose} className="text-cyber-green/40 hover:text-cyber-green transition-colors">
            <X size={18} />
          </button>
        </div>
        <p className="font-mono text-xs text-cyber-green/50 mb-4">
          {sourceName} ↔ {targetName}
        </p>
        <div className="space-y-4">
          <div>
            <label className="text-[10px] font-mono text-cyber-green/50 uppercase block mb-1">关系类型</label>
            <div className="flex flex-wrap gap-1.5">
              {RELATION_TYPES.map(rt => (
                <button key={rt.value} type="button"
                  onClick={() => setType(rt.value)}
                  className="px-2.5 py-1 rounded text-[10px] font-mono border transition-all"
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
              className="w-full bg-cyber-bg border border-cyber-green/20 rounded px-3 py-2 text-xs font-mono text-cyber-green focus:border-cyber-green/50 focus:outline-none" />
          </div>
          <div className="flex gap-3">
            <button onClick={() => onUpdate(edge, { relationship_type: type, affinity, description: desc || null })}
              disabled={saving}
              className="flex-1 py-2 bg-cyber-green/10 border border-cyber-green/30 text-cyber-green font-mono text-sm rounded hover:bg-cyber-green/20 disabled:opacity-30 transition-colors">
              {saving ? '保存中...' : '保存修改'}
            </button>
            <button onClick={() => onDelete(edge)}
              disabled={saving}
              className="px-4 py-2 bg-red-500/10 border border-red-500/30 text-red-400 font-mono text-sm rounded hover:bg-red-500/20 disabled:opacity-30 transition-colors flex items-center gap-1">
              <Trash2 size={14} /> 删除
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function RelationshipGraph() {
  const navigate = useNavigate();
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
      const detailMap = {};
      for (const c of charList) {
        try { const d = await characterAdmin.get(c.character_id); detailMap[c.character_id] = d.avatar_url || null; }
        catch { detailMap[c.character_id] = null; }
      }
      const netData = await relationshipAdmin.network();
      const map = {};
      for (const c of charList) {
        map[c.character_id] = {
          character_id: c.character_id, avatar_url: detailMap[c.character_id] || null,
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

    // 背景：径向渐变 + 粒子星空
    const defs = svg.append('defs');
    const bgGrad = defs.append('radialGradient').attr('id', 'bgGrad');
    bgGrad.append('stop').attr('offset', '0%').attr('stop-color', '#1a1a2e');
    bgGrad.append('stop').attr('offset', '50%').attr('stop-color', '#0d0d1a');
    bgGrad.append('stop').attr('offset', '100%').attr('stop-color', '#050510');
    svg.append('rect').attr('width', W).attr('height', H).attr('fill', 'url(#bgGrad)');

    // 随机星空粒子
    const stars = [];
    const prng = d3.randomUniform(0);
    for (let i = 0; i < 200; i++) {
      stars.push({ x: prng() * W, y: prng() * H, r: prng() * 1.5 + 0.3, o: prng() * 0.6 + 0.1 });
    }
    svg.append('g').selectAll('circle').data(stars).join('circle')
      .attr('cx', d => d.x).attr('cy', d => d.y).attr('r', d => d.r)
      .attr('fill', '#A7EF9E').attr('opacity', d => d.o)
      .attr('class', 'star-particle');

    // 微妙网格叠加
    defs.append('pattern').attr('id', 'grid').attr('width', 50).attr('height', 50).attr('patternUnits', 'userSpaceOnUse')
      .append('path').attr('d', 'M 50 0 L 0 0 0 50').attr('fill', 'none').attr('stroke', CYBER_GREEN).attr('stroke-opacity', 0.02).attr('stroke-width', 0.5);
    svg.append('rect').attr('width', W).attr('height', H).attr('fill', 'url(#grid)');

    // 箭头标记
    RELATION_TYPES.forEach(rt => {
      defs.append('marker').attr('id', 'arrow-' + rt.value)
        .attr('viewBox', '0 -5 10 10').attr('refX', 30).attr('refY', 0).attr('orient', 'auto')
        .attr('markerWidth', 5).attr('markerHeight', 5)
        .append('path').attr('d', 'M 0,-4 L 8,0 L 0,4').attr('fill', rt.color).attr('opacity', 0.6);
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

    // ── 边：曲线 ──
    const linkGroup = g.append('g').attr('class', 'links');
    const linkPath = linkGroup.selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('stroke', d => getRelationColor(d.relationship_type))
      .attr('stroke-opacity', 0.3)
      .attr('stroke-width', d => Math.max(1.5, Math.abs(d.affinity) / 30))
      .attr('marker-end', d => `url(#arrow-${d.relationship_type})`)
      .style('cursor', 'pointer');

    // 边标签
    const edgeLabelGroup = g.append('g').attr('class', 'edge-labels');
    const edgeLabelBg = edgeLabelGroup.selectAll('rect').data(links).join('rect')
      .attr('fill', CYBER_DARK).attr('rx', 3).attr('opacity', 0);
    const edgeLabelText = edgeLabelGroup.selectAll('text').data(links).join('text')
      .text(d => getRelationLabel(d.relationship_type))
      .attr('font-family', 'JetBrains Mono, monospace').attr('font-size', '9px')
      .attr('fill', d => getRelationColor(d.relationship_type))
      .attr('text-anchor', 'middle').attr('dy', '-6').attr('opacity', 0);

    // 边交互
    linkPath.on('mouseenter', function(event, d) {
      d3.select(this).attr('stroke-opacity', 0.8).attr('stroke-width', Math.max(3, Math.abs(d.affinity) / 20));
      edgeLabelBg.attr('opacity', l => l === d ? 0.9 : 0);
      edgeLabelText.attr('opacity', l => l === d ? 1 : 0);
    }).on('mouseleave', function(event, d) {
      d3.select(this).attr('stroke-opacity', 0.3).attr('stroke-width', Math.max(1.5, Math.abs(d.affinity) / 30));
      edgeLabelBg.attr('opacity', 0);
      edgeLabelText.attr('opacity', 0);
    }).on('click', (event, d) => {
      event.stopPropagation();
      setEditEdge(d);
    });

    // ── 节点 ──
    const nodeGroup = g.append('g').attr('class', 'nodes');
    const node = nodeGroup.selectAll('g').data(nodes).join('g')
      .attr('cursor', 'pointer')
      .call(d3.drag()
        .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }))
      .on('dblclick', (event, d) => {
        event.stopPropagation();
        navigate(`/editor/${d.character_id}`);
      });

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
      }
      // 始终显示名字首字母作为fallback文字
      g.append('text')
        .text((d.name || d.display_name || d.character_id).charAt(0))
        .attr('text-anchor', 'middle').attr('dy', '0.35em')
        .attr('fill', CYBER_GREEN).attr('font-family', 'Orbitron, sans-serif')
        .attr('font-size', '18px').attr('font-weight', 'bold')
        .attr('pointer-events', 'none');
    });

    // 主体圆（描边）
    node.append('circle').attr('r', NODE_R)
      .attr('fill', 'none')
      .attr('stroke', d => d.is_active ? CYBER_GREEN : '#EF4444')
      .attr('stroke-width', d => d.is_active ? 2 : 2.5)
      .attr('stroke-opacity', 0.7);

    // 装饰虚线环
    node.append('circle').attr('r', NODE_R - 4).attr('fill', 'none')
      .attr('stroke', CYBER_GREEN).attr('stroke-opacity', 0.15).attr('stroke-width', 1)
      .attr('stroke-dasharray', '3 6');

    // 名称
    node.append('text')
      .text(d => d.name || d.display_name || d.character_id)
      .attr('text-anchor', 'middle').attr('dy', NODE_R + 18)
      .attr('fill', CYBER_GREEN).attr('font-family', 'JetBrains Mono, monospace')
      .attr('font-size', '11px').attr('font-weight', '500')
      .attr('opacity', 0.75).attr('pointer-events', 'none');

    // 悬停高亮
    node.on('mouseenter', (event, d) => {
      node.select('.node-halo').attr('opacity', n => n.character_id === d.character_id ? 0.25 : 0);
      linkPath
        .attr('stroke-opacity', l => (l.source.character_id === d.character_id || l.target.character_id === d.character_id) ? 0.8 : 0.04)
        .attr('stroke-width', l => (l.source.character_id === d.character_id || l.target.character_id === d.character_id)
          ? Math.max(3, Math.abs(l.affinity) / 20) : 0.5);
    });
    node.on('mouseleave', () => {
      node.select('.node-halo').attr('opacity', 0);
      linkPath.attr('stroke-opacity', 0.3).attr('stroke-width', d => Math.max(1.5, Math.abs(d.affinity) / 30));
    });

    svg.on('click', () => { setEditEdge(null); });

    // tick
    simulation.on('tick', () => {
      linkPath.attr('d', d => {
        const sx = d.source.x, sy = d.source.y;
        const tx = d.target.x, ty = d.target.y;
        const dr = Math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2);
        return `M${sx},${sy}A${dr * 0.8},${dr * 0.8} 0 0,1 ${tx},${ty}`;
      });
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

    return () => { simulation.stop(); };
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
    if (!window.confirm('确定删除 "' + sn + '" 与 "' + tn + '" 之间的关系？')) return;
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
  return (
    <div className="min-h-screen bg-cyber-bg flex flex-col select-none">
      {toast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[60] px-4 py-2 bg-cyber-green/20 border border-cyber-green/30 text-cyber-green font-mono text-xs rounded shadow-lg">
          {toast}
        </div>
      )}

      {showAddModal && (
        <AddRelationModal characters={characters} onAdd={handleAdd} onClose={() => setShowAddModal(false)} adding={saving} />
      )}
      {editEdge && (
        <EditRelationModal edge={editEdge} onUpdate={handleUpdate} onDelete={handleDelete} onClose={() => setEditEdge(null)} saving={saving} />
      )}

      {/* Header */}
      <div className="sticky top-0 z-20 bg-cyber-surface/95 backdrop-blur border-b border-cyber-green/20">
        <div className="flex items-center justify-between px-5 py-3">
          <button onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-cyber-green/50 hover:text-cyber-green transition-colors font-mono text-sm">
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
              className="flex items-center gap-1 px-3 py-1.5 bg-cyber-green/10 border border-cyber-green/25 text-cyber-green font-mono text-xs rounded hover:bg-cyber-green/20 transition-colors">
              <Plus size={13} /> 添加关系
            </button>
            <button onClick={loadData} disabled={loading}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-mono text-cyber-green/40 hover:text-cyber-green border border-cyber-green/15 rounded transition-colors">
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 relative">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-cyber-bg/80">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="animate-spin text-cyber-green" size={30} />
              <span className="font-mono text-xs text-cyber-green/50">加载关系网络...</span>
            </div>
          </div>
        )}
        {error && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 px-4 py-2 bg-red-900/80 text-red-300 font-mono text-xs rounded">
            错误: {error}
          </div>
        )}
        {!loading && network.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <Users size={56} className="mx-auto text-cyber-green/10 mb-5" />
              <p className="font-mono text-sm text-cyber-green/30 mb-2">暂无关系数据</p>
              <p className="font-mono text-[11px] text-cyber-green/15 mb-6">创建至少两个角色后，可在此构建关系图谱</p>
              <button onClick={() => setShowAddModal(true)}
                className="px-4 py-2 bg-cyber-green/10 border border-cyber-green/25 text-cyber-green/60 font-mono text-xs rounded hover:bg-cyber-green/20 transition-colors inline-flex items-center gap-1.5">
                <Plus size={14} /> 添加第一条关系
              </button>
            </div>
          </div>
        )}
        <div ref={containerRef} className="absolute inset-0">
          <svg ref={svgRef} className="w-full h-full" />
        </div>

        {/* 浮动控件 */}
        {!loading && network.nodes.length > 0 && (
          <>
            <div className="absolute bottom-6 right-6 flex flex-col gap-1.5 z-10">
              <button onClick={zoomIn} className="p-2.5 bg-cyber-surface border border-cyber-green/15 rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 transition-colors" title="放大">
                <ZoomIn size={16} />
              </button>
              <button onClick={zoomOut} className="p-2.5 bg-cyber-surface border border-cyber-green/15 rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 transition-colors" title="缩小">
                <ZoomOut size={16} />
              </button>
              <button onClick={zoomReset} className="p-2.5 bg-cyber-surface border border-cyber-green/15 rounded-lg text-cyber-green/50 hover:text-cyber-green hover:border-cyber-green/30 transition-colors" title="重置">
                <Maximize2 size={16} />
              </button>
            </div>
            <div className="absolute bottom-6 left-6 z-10">
              <div className="bg-cyber-surface/90 border border-cyber-green/10 rounded-lg px-3 py-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px]">
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
        <div className="text-center py-2 border-t border-cyber-green/5">
          <span className="text-[10px] font-mono text-cyber-green/15">
            拖拽节点 · 滚轮缩放 · 悬停高亮 · 点击边编辑 · 双击编辑角色
          </span>
        </div>
      )}
    </div>
  );
}

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate } from 'react-router-dom';
import * as d3 from 'd3';
import { useArchiveShell } from '@/archive/ArchiveShell';
import { useArchiveTheme } from '@/archive/ArchiveThemeProvider';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { relationshipAdmin } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import { useUser } from '../context/UserContext';
import { characterEditorPath } from '../utils/navigationState';
import { createTimeoutController } from '../utils/timeoutController';
import {
  Link2,
  Loader2,
  Maximize2,
  Plus,
  RefreshCw,
  Trash2,
  Users,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

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

function readArchiveGraphColors(element) {
  const scope = element?.closest('.archive-scope') || document.documentElement;
  const styles = window.getComputedStyle(scope);
  const destructive = styles.getPropertyValue('--destructive').trim();
  const fallback = styles.color || 'currentColor';
  return {
    character: styles.getPropertyValue('--archive-graph-character').trim() || fallback,
    player: styles.getPropertyValue('--archive-graph-player').trim() || fallback,
    surface: styles.getPropertyValue('--archive-graph-surface').trim() || 'transparent',
    inactive: destructive ? `hsl(${destructive})` : fallback,
  };
}

function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
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
  idPrefix,
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
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap gap-2">
        {relationTypes.map(rt => {
          const isUsed = usedTypeValues.has(rt.value);
          const selected = value === rt.value;
          return (
            <div
              key={rt.value}
              className="group inline-flex min-h-11 max-w-full overflow-hidden rounded-md border bg-background/70 transition-colors duration-200"
              style={{ borderColor: rt.color }}
            >
              <Button
                type="button"
                onClick={() => onChange(rt.value)}
                aria-pressed={selected}
                variant="ghost"
                className="h-11 min-h-11 min-w-0 rounded-none px-3 font-archive-mono text-xs"
                style={selected ? { color: rt.color } : undefined}
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: rt.color }}
                  aria-hidden="true"
                />
                <span className="truncate">{rt.label}</span>
              </Button>
              <Button
                type="button"
                disabled={isUsed}
                aria-label={`删除关系类型 ${rt.label}`}
                title={isUsed ? '已有关系正在使用，先修改或删除对应关系' : '删除类型'}
                onClick={(e) => {
                  const next = relationTypes.find(item => item.value !== rt.value)?.value || '';
                  if (value === rt.value) onChange(next);
                  onRemoveType(rt.value);
                }}
                variant="ghost"
                size="icon"
                className="h-11 min-h-11 rounded-none border-l border-border text-muted-foreground hover:text-destructive"
              >
                <X aria-hidden="true" />
              </Button>
            </div>
          );
        })}
      </div>
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
        <label htmlFor={`${idPrefix}-new-type`} className="sr-only">新增关系类型</label>
        <Input
          id={`${idPrefix}-new-type`}
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
          className="min-w-0 flex-1 font-archive-mono text-xs"
        />
        <Button
          type="button"
          onClick={handleAdd}
          size="lg"
          variant="secondary"
          className="shrink-0"
        >
          <Plus aria-hidden="true" /> 新增
        </Button>
      </div>
    </div>
  );
}

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

  return (
    <Dialog open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader className="pr-12">
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="h-5 w-5 text-primary" aria-hidden="true" />
            添加关系
          </DialogTitle>
          <DialogDescription>
            在两个档案节点之间建立连接，并记录关系类型、亲密度和描述。
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="min-w-0 space-y-5">
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">
            <div className="min-w-0 space-y-2">
              <label htmlFor="relation-character-a" className="text-sm font-medium text-foreground">角色 A</label>
              <Select value={charA} onValueChange={setCharA}>
                <SelectTrigger id="relation-character-a">
                  <SelectValue placeholder="选择角色" />
                </SelectTrigger>
                <SelectContent>
                  {characters.map(character => (
                    <SelectItem
                      key={character.character_id}
                      value={character.character_id}
                      className="min-h-11"
                    >
                      {character.node_type === 'player' ? '[玩家] ' : ''}
                      {character.display_name || character.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-0 space-y-2">
              <label htmlFor="relation-character-b" className="text-sm font-medium text-foreground">角色 B</label>
              <Select value={charB} onValueChange={setCharB}>
                <SelectTrigger id="relation-character-b">
                  <SelectValue placeholder="选择角色" />
                </SelectTrigger>
                <SelectContent>
                  {characters.map(character => (
                    <SelectItem
                      key={character.character_id}
                      value={character.character_id}
                      className="min-h-11"
                    >
                      {character.node_type === 'player' ? '[玩家] ' : ''}
                      {character.display_name || character.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="min-w-0 space-y-2">
            <span className="text-sm font-medium text-foreground">关系类型</span>
            <RelationTypePicker
              idPrefix="add-relation"
              value={type}
              onChange={setType}
              relationTypes={relationTypes}
              usedTypeValues={usedTypeValues}
              onAddType={onAddType}
              onRemoveType={onRemoveType}
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="add-relation-affinity" className="flex items-center justify-between gap-3 text-sm font-medium text-foreground">
              <span>{isPlayerRelation ? '好感度' : '亲密度'}</span>
              <span className="font-archive-mono tabular-nums text-primary">{affinity}</span>
            </label>
            <Input
              id="add-relation-affinity"
              type="range"
              min="-100"
              max="100"
              value={affinity}
              onChange={e => setAffinity(Number(e.target.value))}
              className="cursor-pointer accent-primary"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="add-relation-description" className="text-sm font-medium text-foreground">描述（可选）</label>
            <Input
              id="add-relation-description"
              type="text"
              value={desc}
              onChange={e => setDesc(e.target.value)}
              placeholder="如：青梅竹马、宿敌..."
            />
          </div>

          <DialogFooter>
            <Button type="button" size="lg" variant="outline" onClick={onClose}>取消</Button>
            <Button
              type="submit"
              size="lg"
              disabled={adding || !charA || !charB || charA === charB || !type}
            >
              {adding ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Plus aria-hidden="true" />}
              {adding ? '创建中...' : '创建关系'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditRelationModal({ edge, relationTypes, usedTypeValues, onAddType, onRemoveType, onUpdate, onDelete, onClose, saving }) {
  const [type, setType] = useState(edge.relationship_type);
  const [affinity, setAffinity] = useState(edge.affinity);
  const [desc, setDesc] = useState(edge.description || '');

  const sourceName = edge.source?.display_name || edge.source?.name || edge.source;
  const targetName = edge.target?.display_name || edge.target?.name || edge.target;
  const isPlayerRelation = edge.source?.node_type === 'player' || edge.target?.node_type === 'player';

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!type) return;
    onUpdate(edge, { relationship_type: type, affinity, description: desc || null });
  };

  return (
    <Dialog open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader className="pr-12">
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="h-5 w-5 text-primary" aria-hidden="true" />
            编辑关系
          </DialogTitle>
          <DialogDescription>
            调整连接属性，或从关系档案图中删除这条记录。
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="min-w-0 space-y-5">
          <p className="break-words rounded-md border border-border bg-muted/45 px-3 py-3 text-sm text-foreground">
            {sourceName} <span className="px-1 text-primary" aria-hidden="true">↔</span> {targetName}
          </p>

          <div className="min-w-0 space-y-2">
            <span className="text-sm font-medium text-foreground">关系类型</span>
            <RelationTypePicker
              idPrefix="edit-relation"
              value={type}
              onChange={setType}
              relationTypes={relationTypes}
              usedTypeValues={usedTypeValues}
              onAddType={onAddType}
              onRemoveType={onRemoveType}
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="edit-relation-affinity" className="flex items-center justify-between gap-3 text-sm font-medium text-foreground">
              <span>{isPlayerRelation ? '好感度' : '亲密度'}</span>
              <span className="font-archive-mono tabular-nums text-primary">{affinity}</span>
            </label>
            <Input
              id="edit-relation-affinity"
              type="range"
              min="-100"
              max="100"
              value={affinity}
              onChange={e => setAffinity(Number(e.target.value))}
              className="cursor-pointer accent-primary"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="edit-relation-description" className="text-sm font-medium text-foreground">描述</label>
            <Input
              id="edit-relation-description"
              type="text"
              value={desc}
              onChange={e => setDesc(e.target.value)}
            />
          </div>

          <DialogFooter className="sm:justify-between">
            <Button
              type="button"
              size="lg"
              variant="destructive"
              onClick={() => onDelete(edge)}
              disabled={saving}
            >
              <Trash2 aria-hidden="true" /> 删除
            </Button>
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              <Button type="button" size="lg" variant="outline" onClick={onClose}>取消</Button>
              <Button type="submit" size="lg" disabled={saving || !type}>
                {saving && <Loader2 className="animate-spin" aria-hidden="true" />}
                {saving ? '保存中...' : '保存修改'}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function RelationshipGraph() {
  const navigate = useNavigate();
  const dialog = useDialog();
  const { setPrimaryAction } = useArchiveShell();
  const { theme } = useArchiveTheme();
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

  const primaryAction = useMemo(() => (
    <Button
      type="button"
      size="lg"
      onClick={() => setShowAddModal(true)}
      disabled={!user || loading}
    >
      <Plus aria-hidden="true" />
      添加关系
    </Button>
  ), [loading, user]);

  useEffect(() => {
    setPrimaryAction(primaryAction);
    return () => setPrimaryAction(null);
  }, [primaryAction, setPrimaryAction]);

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
    const graphColors = readArchiveGraphColors(container);
    const reduceMotion = prefersReducedMotion();

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

    if (!reduceMotion) animateFlow();

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

    node.transition()
      .delay((d, i) => reduceMotion ? 0 : Math.min(i, 16) * 45)
      .duration(reduceMotion ? 0 : 240)
      .ease(d3.easeCubicOut)
      .attr('opacity', 1);

    // 光晕
    node.append('circle').attr('r', NODE_R + 10).attr('fill', d => (
      d.node_type === 'player' ? graphColors.player : graphColors.character
    ))
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
      g.append('circle').attr('r', NODE_R - 2).attr('fill', graphColors.surface).attr('pointer-events', 'none');
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
          .attr('fill', d.node_type === 'player' ? graphColors.player : graphColors.character)
          .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
          .attr('font-size', '18px').attr('font-weight', 'bold')
          .attr('pointer-events', 'none');
      }
    });

    // 主体圆（描边）
    node.append('circle').attr('r', NODE_R)
      .attr('fill', 'none')
      .attr('stroke', d => (
        d.node_type === 'player'
          ? graphColors.player
          : (d.is_active ? graphColors.character : graphColors.inactive)
      ))
      .attr('stroke-width', d => d.is_active ? 2.4 : 2.8)
      .attr('stroke-opacity', 0.9);

    // 装饰虚线环
    node.append('circle').attr('r', NODE_R - 4).attr('fill', 'none')
      .attr('stroke', d => d.node_type === 'player' ? graphColors.player : graphColors.character)
      .attr('stroke-opacity', 0.26).attr('stroke-width', 1)
      .attr('stroke-dasharray', '3 6');

    const playerBadge = node.filter(d => d.node_type === 'player');
    playerBadge.append('rect')
      .attr('x', -19).attr('y', -NODE_R - 19)
      .attr('width', 38).attr('height', 16).attr('rx', 4)
      .attr('fill', graphColors.surface).attr('stroke', graphColors.player).attr('stroke-opacity', 0.55);
    playerBadge.append('text')
      .text('玩家')
      .attr('text-anchor', 'middle').attr('dy', -NODE_R - 8)
      .attr('fill', graphColors.player).attr('font-size', '9px').attr('font-weight', '700')
      .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
      .attr('pointer-events', 'none');

    // 名称
    node.append('text')
      .text(d => d.name || d.display_name || d.character_id)
      .attr('text-anchor', 'middle').attr('dy', NODE_R + 18)
      .attr('fill', d => d.node_type === 'player' ? graphColors.player : graphColors.character)
      .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
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
        svg.transition()
          .duration(reduceMotion ? 0 : 260)
          .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
      }
    }, 1200);

    return () => {
      flowStopped = true;
      linkFlow.interrupt();
      setActiveRelationType(null);
      simulation.stop();
      centerTimeoutRef.current.cancel();
    };
  }, [graphSize.height, graphSize.width, network, navigate, relationTypes, theme]);

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
    if (!zoomRef.current) return;
    svg.transition().duration(prefersReducedMotion() ? 0 : 220).call(zoomRef.current.scaleBy, 1.4);
  };
  const zoomOut = () => {
    const svg = d3.select(svgRef.current);
    if (!zoomRef.current) return;
    svg.transition().duration(prefersReducedMotion() ? 0 : 220).call(zoomRef.current.scaleBy, 0.7);
  };
  const zoomReset = () => {
    const svg = d3.select(svgRef.current);
    if (!zoomRef.current) return;
    svg.transition().duration(prefersReducedMotion() ? 0 : 260).call(zoomRef.current.transform, d3.zoomIdentity);
  };

  const usedTypeValues = new Set(network.edges.map(edge => edge.relationship_type).filter(Boolean));
  const isAuthError = !!error && /认证|未登录|401|token/i.test(error);

  return (
    <section className="relative h-[calc(100dvh-4rem)] min-h-[32rem] min-w-0 select-none overflow-hidden bg-[hsl(var(--archive-graph-surface))] text-foreground">
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed left-1/2 top-20 z-[1200] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 rounded-md border border-border bg-popover/95 px-4 py-3 text-center text-sm text-popover-foreground shadow-xl backdrop-blur-md"
        >
          {toast}
        </div>
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

      <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex min-w-0 items-start justify-between gap-3 sm:inset-x-5 sm:top-5">
        <div className="pointer-events-auto min-w-0 rounded-lg border border-border bg-card/88 px-3 py-3 shadow-lg backdrop-blur-md sm:px-4">
          <div className="flex min-w-0 items-center gap-3">
            <Users className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
            <div className="min-w-0">
              <h1 className="truncate font-archive-serif text-base font-semibold text-foreground sm:text-lg">
                关系档案图
              </h1>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-archive-mono text-[10px] text-muted-foreground">
                <span><span className="tabular-nums text-foreground">{characters.length}</span> 个节点</span>
                <span><span className="tabular-nums text-foreground">{network.edges.length}</span> 条关系</span>
              </div>
            </div>
          </div>
        </div>

        <div className="pointer-events-auto flex shrink-0 gap-2">
          <Button
            type="button"
            size="lg"
            className="lg:hidden"
            onClick={() => setShowAddModal(true)}
            disabled={!user || loading}
          >
            <Plus aria-hidden="true" />
            <span className="hidden sm:inline">添加关系</span>
          </Button>
          <Button
            type="button"
            size="icon"
            variant="outline"
            onClick={loadData}
            disabled={loading}
            aria-label="刷新关系图"
            title="刷新关系图"
          >
            <RefreshCw className={loading ? 'animate-spin' : ''} aria-hidden="true" />
          </Button>
        </div>
      </div>

      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 text-muted-foreground" role="status" aria-live="polite">
            <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
            <span className="font-archive-mono text-xs">加载关系网络...</span>
          </div>
        </div>
      )}
      {error && (
        <div className="absolute inset-x-3 top-24 z-30 flex justify-center sm:inset-x-5">
          <div className="flex w-full max-w-xl flex-col gap-3 rounded-lg border border-destructive/35 bg-destructive/10 px-4 py-3 shadow-xl backdrop-blur-md sm:flex-row sm:items-center sm:justify-between">
            <p className="min-w-0 break-words text-sm text-destructive" role="alert">{error}</p>
            <Button
              type="button"
              size="lg"
              variant="outline"
              onClick={isAuthError ? () => navigate('/') : loadData}
              className="shrink-0 border-destructive/35 text-destructive hover:text-destructive"
            >
              {isAuthError ? '返回登录页' : '重试'}
            </Button>
          </div>
        </div>
      )}
      {!loading && !error && network.nodes.length === 0 && (
        <div className="absolute inset-0 z-10 flex items-center justify-center px-4 pt-20">
          <div className="w-full max-w-md rounded-lg border border-border bg-card/90 px-6 py-7 text-center shadow-xl backdrop-blur-md">
            <Users className="mx-auto mb-4 h-12 w-12 text-muted-foreground" aria-hidden="true" />
            <p className="font-archive-serif text-lg font-semibold text-foreground">暂无关系数据</p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              创建至少两个角色后，可在此构建关系图谱。
            </p>
            <Button
              type="button"
              size="lg"
              className="mt-5"
              onClick={() => setShowAddModal(true)}
              disabled={!user}
            >
              <Plus aria-hidden="true" />
              添加第一条关系
            </Button>
          </div>
        </div>
      )}

      <div ref={containerRef} className="absolute inset-0 z-[1] min-w-0">
        <svg
          ref={svgRef}
          className="h-full w-full"
          role="img"
          aria-label="角色与玩家之间的关系档案图"
        />
      </div>

      {!loading && network.nodes.length > 0 && (
        <>
          <div className="absolute bottom-3 right-3 z-20 flex flex-col gap-2 sm:bottom-5 sm:right-5">
            <Button type="button" size="icon" variant="outline" onClick={zoomIn} title="放大" aria-label="放大关系图">
              <ZoomIn aria-hidden="true" />
            </Button>
            <Button type="button" size="icon" variant="outline" onClick={zoomOut} title="缩小" aria-label="缩小关系图">
              <ZoomOut aria-hidden="true" />
            </Button>
            <Button type="button" size="icon" variant="outline" onClick={zoomReset} title="重置" aria-label="重置关系图缩放">
              <Maximize2 aria-hidden="true" />
            </Button>
          </div>

          <div className="absolute bottom-3 left-3 right-[4.5rem] z-20 max-h-36 overflow-y-auto overscroll-contain rounded-lg border border-border bg-card/88 p-2 shadow-lg backdrop-blur-md sm:bottom-5 sm:left-5 sm:right-24 sm:max-h-28 sm:p-3 lg:right-auto lg:w-[min(48rem,calc(100%-7.5rem))]">
            <div className="grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-1 font-archive-mono text-[10px]">
              {relationTypes.map(rt => {
                const active = activeRelationType === rt.value;
                const dimmed = activeRelationType && !active;
                return (
                  <div
                    key={rt.value}
                    className={[
                      'flex min-h-8 min-w-0 items-center gap-2 rounded-md border px-2 py-1.5 transition-colors duration-200',
                      active ? 'bg-accent text-accent-foreground' : 'border-transparent text-muted-foreground',
                      dimmed ? 'opacity-35' : 'opacity-100',
                    ].join(' ')}
                    style={active ? { borderColor: rt.color } : undefined}
                  >
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{ backgroundColor: rt.color }}
                      aria-hidden="true"
                    />
                    <span className="truncate" title={rt.label}>{rt.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

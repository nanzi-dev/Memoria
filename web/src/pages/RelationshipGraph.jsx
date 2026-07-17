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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
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
  Check,
  ChevronDown,
  Focus,
  Link2,
  ListFilter,
  Loader2,
  Maximize2,
  Network,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Users,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

const RELATION_TYPE_STORAGE_KEY = 'memoria.relationshipTypes';
const RELATION_FILTER_ALL = '__all_relationship_types__';
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

function getRelationLabel(type, relationTypes) {
  return relationTypes.find(t => t.value === type)?.label || type || '未分类关系';
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
    wall: styles.getPropertyValue('--archive-graph-wall').trim() || 'transparent',
    paper: styles.getPropertyValue('--archive-graph-paper').trim() || fallback,
    paperMuted: styles.getPropertyValue('--archive-graph-paper-muted').trim() || fallback,
    ink: styles.getPropertyValue('--archive-graph-ink').trim() || fallback,
    pin: styles.getPropertyValue('--archive-graph-pin').trim() || fallback,
    pinHighlight: styles.getPropertyValue('--archive-graph-pin-highlight').trim() || fallback,
    ropeShadow: styles.getPropertyValue('--archive-graph-rope-shadow').trim() || fallback,
    inactive: destructive ? `hsl(${destructive})` : fallback,
  };
}

function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

const DESKTOP_NODE = {
  cardWidth: 104,
  cardHeight: 126,
  imageSize: 88,
  cardTop: -12,
  imageTop: 2,
  labelY: 108,
  pinRadius: 7,
  nameFontSize: 12,
};

const MOBILE_NODE = {
  cardWidth: 88,
  cardHeight: 108,
  imageSize: 74,
  cardTop: -10,
  imageTop: 2,
  labelY: 92,
  pinRadius: 6,
  nameFontSize: 11,
};

const FOCUS_LINKS_PER_NODE = 2;

function getNodeLayout(width) {
  return width < 640 ? MOBILE_NODE : DESKTOP_NODE;
}

function getNodeTilt(characterId, nodeType) {
  if (nodeType === 'player') return 0;
  return ((hashRelationType(characterId) % 7) - 3) * 0.75;
}

function truncateNodeName(value, maxLength = 9) {
  const characters = Array.from(String(value || ''));
  if (characters.length <= maxLength) return characters.join('');
  return `${characters.slice(0, maxLength - 1).join('')}…`;
}

function getAffinityMagnitude(affinity = 0) {
  const value = Math.abs(Number(affinity) || 0);
  return Math.min(100, Math.max(0, value));
}

function getLinkWidth(edge) {
  return 2.4 + (getAffinityMagnitude(edge.affinity) / 100) * 4;
}

function getLinkHoverWidth(edge) {
  return getLinkWidth(edge) + 1.2;
}

function formatAffinity(affinity = 0) {
  const value = Math.round(Number(affinity) || 0);
  return value > 0 ? `+${value}` : String(value);
}

function getRelationshipLabelText(edge, relationTypes) {
  const type = truncateNodeName(
    getRelationLabel(edge.relationship_type, relationTypes),
    9,
  );
  return `${type} · ${formatAffinity(edge.affinity)}`;
}

function getRelationshipLabelWidth(value) {
  const textWidth = Array.from(String(value || '')).reduce((width, character) => (
    width + (/[\u3000-\u9fff]/.test(character) ? 12 : 7)
  ), 0);
  return Math.min(156, Math.max(78, textWidth + 22));
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
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [creating, setCreating] = useState(false);
  const [newType, setNewType] = useState('');
  const searchInputRef = useRef(null);
  const newTypeInputRef = useRef(null);
  const selectedItemRef = useRef(null);
  const selectedType = relationTypes.find(type => type.value === value);
  const selectedLabel = selectedType?.label || value || '选择关系类型';
  const selectedColor = selectedType?.color || relationTypeColor(value);
  const normalizedSearch = normalizeRelationTypeName(search).toLocaleLowerCase();
  const filteredRelationTypes = relationTypes.filter(type => (
    !normalizedSearch
    || `${type.label} ${type.value}`.toLocaleLowerCase().includes(normalizedSearch)
  ));
  const selectedTypeIsUsed = selectedType
    ? usedTypeValues.has(selectedType.value)
    : false;

  const handleOpenChange = (nextOpen) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setSearch('');
      setCreating(false);
      setNewType('');
    }
  };

  const handleAdd = () => {
    const label = normalizeRelationTypeName(newType);
    if (!label) return;
    const nextType = onAddType(label);
    onChange(nextType.value);
    handleOpenChange(false);
  };

  const handleRemoveSelected = () => {
    if (!selectedType || selectedTypeIsUsed) return;
    const nextValue = relationTypes.find(type => type.value !== selectedType.value)?.value || '';
    onRemoveType(selectedType.value);
    onChange(nextValue);
  };

  return (
    <DropdownMenu open={open} onOpenChange={handleOpenChange}>
      <DropdownMenuTrigger asChild>
        <Button
          id={`${idPrefix}-type-trigger`}
          type="button"
          variant="outline"
          aria-label={`关系类型，当前为${selectedLabel}`}
          className="h-auto min-h-14 w-full justify-between whitespace-normal px-3 py-2 text-left"
        >
          <span className="flex min-w-0 items-center gap-3">
            <span
              className="h-3 w-3 shrink-0 rounded-sm border border-foreground/20"
              style={{ backgroundColor: selectedColor }}
              aria-hidden="true"
            />
            <span className="min-w-0">
              <span className="block font-archive-mono text-[10px] font-medium text-muted-foreground">
                当前关系
              </span>
              <span className="block break-words text-sm font-semibold text-foreground">
                {selectedLabel}
              </span>
            </span>
          </span>
          <ChevronDown
            className={`ml-3 shrink-0 text-muted-foreground transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={6}
        className="w-[var(--radix-dropdown-menu-trigger-width)] min-w-80 p-0"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          window.requestAnimationFrame(() => {
            searchInputRef.current?.focus();
            selectedItemRef.current?.scrollIntoView({ block: 'nearest' });
          });
        }}
      >
        <div className="border-b border-border p-2">
          <DropdownMenuLabel className="px-1 pb-2 pt-0">
            搜索关系类型
          </DropdownMenuLabel>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              ref={searchInputRef}
              id={`${idPrefix}-type-search`}
              type="search"
              value={search}
              onChange={event => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Escape') event.stopPropagation();
              }}
              aria-label="搜索关系类型"
              placeholder="输入名称筛选"
              className="pl-9 font-archive-mono text-xs"
            />
          </div>
        </div>

        <div
          id={`${idPrefix}-type-options`}
          className="max-h-64 overflow-y-auto p-1"
          aria-label="关系类型列表"
        >
          {filteredRelationTypes.length > 0 ? (
            <DropdownMenuRadioGroup
              value={value}
              onValueChange={(nextValue) => {
                onChange(nextValue);
                handleOpenChange(false);
              }}
            >
              {filteredRelationTypes.map(type => {
                const selected = value === type.value;
                return (
                  <DropdownMenuRadioItem
                    ref={selected ? selectedItemRef : undefined}
                    key={type.value}
                    value={type.value}
                    className={`min-h-12 gap-3 pr-3 ${selected ? 'bg-accent/70 text-accent-foreground' : ''}`}
                  >
                    <span
                      className="h-3 w-3 shrink-0 rounded-sm border border-foreground/20"
                      style={{ backgroundColor: type.color }}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 break-words font-archive-mono text-xs text-foreground">
                      {type.label}
                    </span>
                    {selected && (
                      <>
                        <Check className="ml-auto text-primary" aria-hidden="true" />
                        <span className="sr-only">当前关系</span>
                      </>
                    )}
                  </DropdownMenuRadioItem>
                );
              })}
            </DropdownMenuRadioGroup>
          ) : (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              没有匹配的关系类型
            </p>
          )}
        </div>

        <DropdownMenuSeparator className="m-0" />
        <div className="p-1">
          {!creating ? (
            <DropdownMenuItem
              onSelect={(event) => {
                event.preventDefault();
                setCreating(true);
                window.requestAnimationFrame(() => newTypeInputRef.current?.focus());
              }}
            >
              <Plus aria-hidden="true" />
              新增关系类型
            </DropdownMenuItem>
          ) : (
            <div className="space-y-2 p-2">
              <label
                htmlFor={`${idPrefix}-new-type`}
                className="block text-xs font-medium text-foreground"
              >
                新类型名称
              </label>
              <div className="flex min-w-0 gap-2">
                <Input
                  ref={newTypeInputRef}
                  id={`${idPrefix}-new-type`}
                  type="text"
                  value={newType}
                  onChange={event => setNewType(event.target.value)}
                  onKeyDown={(event) => {
                    event.stopPropagation();
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      handleAdd();
                    }
                    if (event.key === 'Escape') {
                      setCreating(false);
                      setNewType('');
                      window.requestAnimationFrame(() => searchInputRef.current?.focus());
                    }
                  }}
                  placeholder="如：同门、债主"
                  className="min-w-0 flex-1 font-archive-mono text-xs"
                />
                <Button
                  type="button"
                  onClick={handleAdd}
                  disabled={!normalizeRelationTypeName(newType)}
                  variant="secondary"
                  className="shrink-0 px-3"
                >
                  <Plus aria-hidden="true" />
                  添加
                </Button>
              </div>
            </div>
          )}

          {selectedType && (
            <DropdownMenuItem
              disabled={selectedTypeIsUsed}
              onSelect={handleRemoveSelected}
              className="text-destructive focus:text-destructive"
              aria-label={selectedTypeIsUsed
                ? `关系类型 ${selectedType.label} 正在使用，无法删除`
                : `删除关系类型 ${selectedType.label}`}
            >
              <Trash2 aria-hidden="true" />
              <span className="min-w-0 flex-1 break-words">
                {selectedTypeIsUsed ? '当前类型正在使用，无法删除' : '删除当前类型'}
              </span>
            </DropdownMenuItem>
          )}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function RelationTypeFilter({
  value,
  onChange,
  usedRelationTypes,
  relationTypeCounts,
  totalCount,
}) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [filterSearch, setFilterSearch] = useState('');
  const filterSearchInputRef = useRef(null);
  const selectedFilterItemRef = useRef(null);
  const selectedFilterValue = value || RELATION_FILTER_ALL;
  const selectedType = usedRelationTypes.find(type => type.value === value);
  const selectedLabel = selectedType?.label || value || '全部关系';
  const normalizedFilterSearch = normalizeRelationTypeName(filterSearch).toLocaleLowerCase();
  const filteredUsedRelationTypes = usedRelationTypes.filter(type => (
    !normalizedFilterSearch
    || `${type.label} ${type.value}`.toLocaleLowerCase().includes(normalizedFilterSearch)
  ));

  const handleFilterOpenChange = (nextOpen) => {
    setFilterOpen(nextOpen);
    if (!nextOpen) setFilterSearch('');
  };

  const handleFilterChange = (nextValue) => {
    onChange(nextValue === RELATION_FILTER_ALL ? null : nextValue);
    handleFilterOpenChange(false);
  };

  return (
    <DropdownMenu open={filterOpen} onOpenChange={handleFilterOpenChange}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          size="lg"
          variant="outline"
          className="max-w-52 bg-card/88 shadow-lg backdrop-blur-md"
          aria-label={`筛选关系类型，当前为${selectedLabel}`}
          title={`关系类型：${selectedLabel}`}
        >
          <ListFilter aria-hidden="true" />
          {selectedType && (
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm border border-foreground/20"
              style={{ backgroundColor: selectedType.color }}
              aria-hidden="true"
            />
          )}
          <span className="max-w-28 truncate">{selectedLabel}</span>
          <ChevronDown
            className={`shrink-0 text-muted-foreground transition-transform duration-200 ${filterOpen ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={6}
        className="w-72 p-0"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          window.requestAnimationFrame(() => {
            filterSearchInputRef.current?.focus();
            selectedFilterItemRef.current?.scrollIntoView({ block: 'nearest' });
          });
        }}
      >
        <div className="border-b border-border p-2">
          <DropdownMenuLabel className="px-1 pb-2 pt-0">
            筛选关系类型
          </DropdownMenuLabel>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              ref={filterSearchInputRef}
              id="relationship-filter-search"
              type="search"
              value={filterSearch}
              onChange={event => setFilterSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Escape') event.stopPropagation();
              }}
              aria-label="搜索关系筛选"
              placeholder="输入名称筛选"
              className="pl-9 font-archive-mono text-xs"
            />
          </div>
        </div>

        <DropdownMenuRadioGroup
          value={selectedFilterValue}
          onValueChange={handleFilterChange}
        >
          <div className="border-b border-border p-1">
            <DropdownMenuRadioItem
              ref={selectedFilterValue === RELATION_FILTER_ALL ? selectedFilterItemRef : undefined}
              value={RELATION_FILTER_ALL}
              className={`gap-2 pr-3 ${
                selectedFilterValue === RELATION_FILTER_ALL
                  ? 'bg-accent/70 text-accent-foreground'
                  : ''
              }`}
            >
              <Network className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <span className="min-w-0 flex-1">全部关系</span>
              <span className="font-archive-mono text-xs tabular-nums text-muted-foreground">
                {totalCount}
              </span>
              {selectedFilterValue === RELATION_FILTER_ALL && (
                <Check className="text-primary" aria-hidden="true" />
              )}
            </DropdownMenuRadioItem>
          </div>

          <div
            id="relationship-filter-options"
            className="max-h-64 overflow-y-auto p-1"
            aria-label="关系筛选列表"
          >
            {filteredUsedRelationTypes.length > 0 ? (
              filteredUsedRelationTypes.map(type => {
                const selected = selectedFilterValue === type.value;
                return (
                  <DropdownMenuRadioItem
                    ref={selected ? selectedFilterItemRef : undefined}
                    key={type.value}
                    value={type.value}
                    className={`min-h-12 gap-2 pr-3 ${
                      selected ? 'bg-accent/70 text-accent-foreground' : ''
                    }`}
                  >
                    <span
                      className="h-2.5 w-7 shrink-0 rounded-sm border border-foreground/15 shadow-sm"
                      style={{ backgroundColor: type.color }}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate" title={type.label}>
                      {type.label}
                    </span>
                    <span className="font-archive-mono text-xs tabular-nums text-muted-foreground">
                      {relationTypeCounts.get(type.value) || 0}
                    </span>
                    {selected && <Check className="text-primary" aria-hidden="true" />}
                  </DropdownMenuRadioItem>
                );
              })
            ) : (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                没有匹配的关系类型
              </p>
            )}
          </div>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
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
            <label
              htmlFor="add-relation-type-trigger"
              className="text-sm font-medium text-foreground"
            >
              关系类型
            </label>
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
  const currentTypeLabel = getRelationLabel(type, relationTypes);
  const currentTypeColor = getRelationColor(type, relationTypes);

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
          <div className="flex min-w-0 flex-col gap-3 rounded-md border border-border bg-muted/45 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-w-0 break-words text-sm font-medium text-foreground">
              {sourceName} <span className="px-1 text-primary" aria-hidden="true">↔</span> {targetName}
            </p>
            <div className="flex min-w-0 items-center gap-2 text-sm">
              <span className="shrink-0 font-archive-mono text-[10px] text-muted-foreground">
                当前关系
              </span>
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-sm border border-foreground/20"
                style={{ backgroundColor: currentTypeColor }}
                aria-hidden="true"
              />
              <span className="min-w-0 break-words font-semibold text-foreground">
                {currentTypeLabel}
              </span>
            </div>
          </div>

          <div className="min-w-0 space-y-2">
            <label
              htmlFor="edit-relation-type-trigger"
              className="text-sm font-medium text-foreground"
            >
              关系类型
            </label>
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
  const viewControllerRef = useRef(null);
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
  const [edgeDensity, setEdgeDensity] = useState('priority');
  const [selectedRelationType, setSelectedRelationType] = useState(null);
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

  useEffect(() => {
    if (
      selectedRelationType
      && !network.edges.some(edge => edge.relationship_type === selectedRelationType)
    ) {
      setSelectedRelationType(null);
    }
  }, [network.edges, selectedRelationType]);

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
    const nodeLayout = getNodeLayout(W);
    const nodeCollisionRadius = (
      Math.hypot(nodeLayout.cardWidth, nodeLayout.cardHeight) / 2
    ) + (W < 640 ? 12 : 20);

    const photoShadow = defs.append('filter')
      .attr('id', 'archive-photo-shadow')
      .attr('x', '-30%')
      .attr('y', '-30%')
      .attr('width', '160%')
      .attr('height', '170%');
    photoShadow.append('feDropShadow')
      .attr('dx', 0)
      .attr('dy', 4)
      .attr('stdDeviation', 4)
      .attr('flood-color', graphColors.ropeShadow)
      .attr('flood-opacity', 0.38);

    const photoHoverShadow = defs.append('filter')
      .attr('id', 'archive-photo-shadow-hover')
      .attr('x', '-35%')
      .attr('y', '-35%')
      .attr('width', '170%')
      .attr('height', '180%');
    photoHoverShadow.append('feDropShadow')
      .attr('dx', 0)
      .attr('dy', 6)
      .attr('stdDeviation', 6)
      .attr('flood-color', graphColors.ropeShadow)
      .attr('flood-opacity', 0.52);

    const inactivePhoto = defs.append('filter').attr('id', 'archive-inactive-photo');
    inactivePhoto.append('feColorMatrix')
      .attr('type', 'saturate')
      .attr('values', 0.18);

    // 缩放
    const g = svg.append('g');
    const zoom = d3.zoom().scaleExtent([0.15, 5]).on('zoom', e => g.attr('transform', e.transform));
    svg.call(zoom);
    zoomRef.current = zoom;

    // 节点数据
    const nodes = network.nodes.map(n => ({
      ...n,
      tilt: getNodeTilt(n.character_id, n.node_type),
    }));
    const links = network.edges.map(e => ({
      source: nodes.find(n => n.character_id === e.source),
      target: nodes.find(n => n.character_id === e.target),
      relationship_type: e.relationship_type,
      affinity: e.affinity,
      description: e.description,
    })).filter(l => l.source && l.target);
    const priorityLinks = new Set();
    nodes.forEach((nodeDatum) => {
      links
        .filter(link => (
          link.source.character_id === nodeDatum.character_id
          || link.target.character_id === nodeDatum.character_id
        ))
        .sort((left, right) => {
          const affinityDelta = getAffinityMagnitude(right.affinity) - getAffinityMagnitude(left.affinity);
          if (affinityDelta) return affinityDelta;
          const leftKey = `${left.source.character_id}:${left.target.character_id}:${left.relationship_type}`;
          const rightKey = `${right.source.character_id}:${right.target.character_id}:${right.relationship_type}`;
          return leftKey.localeCompare(rightKey);
        })
        .slice(0, FOCUS_LINKS_PER_NODE)
        .forEach(link => priorityLinks.add(link));
    });

    let currentEdgeDensity = edgeDensity;
    let currentRelationType = selectedRelationType;
    let lockedNode = null;

    const isLinkVisible = link => (
      !currentRelationType || link.relationship_type === currentRelationType
    );
    const isLinkProminent = link => (
      isLinkVisible(link)
      && (
        Boolean(currentRelationType)
        || currentEdgeDensity === 'all'
        || priorityLinks.has(link)
      )
    );
    const getDefaultRopeOpacity = (layer, link) => {
      if (!isLinkVisible(link)) return 0;
      if (currentRelationType) {
        if (layer === 'shadow') return 0.32;
        if (layer === 'fiber') return 0.22;
        return 0.82;
      }
      if (currentEdgeDensity === 'all') {
        if (layer === 'shadow') return 0.24;
        if (layer === 'fiber') return 0.14;
        return 0.62;
      }
      if (isLinkProminent(link)) {
        if (layer === 'shadow') return 0.29;
        if (layer === 'fiber') return 0.2;
        return 0.76;
      }
      if (layer === 'shadow') return 0.025;
      if (layer === 'fiber') return 0.012;
      return 0.075;
    };

    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.character_id).distance(W < 640 ? 190 : 245).strength(0.34))
      .force('charge', d3.forceManyBody().strength(W < 640 ? -720 : -1050))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(nodeCollisionRadius).strength(0.92))
      .force('x', d3.forceX(W / 2).strength(0.02))
      .force('y', d3.forceY(H / 2).strength(0.02));
    simulationRef.current = simulation;

    const getEdgeGeometry = d => {
      const sx = d.source.x, sy = d.source.y;
      const tx = d.target.x, ty = d.target.y;
      const distance = Math.hypot(tx - sx, ty - sy);
      const sag = Math.min(58, 12 + distance * 0.09);
      const verticalBow = Math.abs(tx - sx) < 42 ? Math.min(34, distance * 0.12) : 0;
      const controlX = ((sx + tx) / 2) + verticalBow;
      const controlY = ((sy + ty) / 2) + sag;
      return {
        path: `M${sx},${sy}Q${controlX},${controlY} ${tx},${ty}`,
        labelX: (0.25 * sx) + (0.5 * controlX) + (0.25 * tx),
        labelY: (0.25 * sy) + (0.5 * controlY) + (0.25 * ty),
      };
    };

    // ── 绳线：阴影、实体色、纤维高光和透明命中区域 ──
    const linkGroup = g.append('g').attr('class', 'links');
    const ropeShadow = linkGroup.append('g').attr('class', 'rope-shadows').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('class', 'rope-shadow')
      .attr('stroke', graphColors.ropeShadow)
      .attr('stroke-opacity', d => getDefaultRopeOpacity('shadow', d))
      .attr('stroke-width', d => getLinkWidth(d) + 2)
      .attr('stroke-linecap', 'round')
      .attr('stroke-linejoin', 'round')
      .attr('transform', 'translate(1.5 2)')
      .attr('pointer-events', 'none');

    const ropeBase = linkGroup.append('g').attr('class', 'rope-bases').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('class', 'rope-base')
      .attr('stroke', d => getRelationColor(d.relationship_type, relationTypes))
      .attr('stroke-opacity', d => getDefaultRopeOpacity('base', d))
      .attr('stroke-width', getLinkWidth)
      .attr('stroke-linecap', 'round')
      .attr('stroke-linejoin', 'round')
      .attr('pointer-events', 'none');

    const ropeFiber = linkGroup.append('g').attr('class', 'rope-fibers').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('class', 'rope-fiber')
      .attr('stroke', graphColors.pinHighlight)
      .attr('stroke-opacity', d => getDefaultRopeOpacity('fiber', d))
      .attr('stroke-width', d => Math.max(0.8, getLinkWidth(d) * 0.26))
      .attr('stroke-linecap', 'round')
      .attr('stroke-dasharray', '1 4')
      .attr('pointer-events', 'none');

    const linkHit = linkGroup.append('g').attr('class', 'rope-hits').selectAll('path').data(links).join('path')
      .attr('fill', 'none')
      .attr('class', 'rope-hit')
      .attr('stroke', 'transparent')
      .attr('stroke-width', d => Math.max(22, getLinkWidth(d) + 16))
      .attr('stroke-linecap', 'round')
      .attr('pointer-events', 'stroke')
      .attr('tabindex', 0)
      .attr('focusable', true)
      .attr('role', 'button')
      .attr('aria-label', d => (
        `编辑 ${d.source.display_name || d.source.name} 与 ${d.target.display_name || d.target.name} 的${d.relationship_type || ''}关系`
      ))
      .style('cursor', 'pointer');

    const relationshipLabel = g.append('g')
      .attr('class', 'relationship-labels')
      .selectAll('g')
      .data(links)
      .join('g')
      .attr('class', 'relationship-label')
      .attr('opacity', 0)
      .attr('pointer-events', 'none');

    relationshipLabel.append('rect')
      .attr('x', d => -getRelationshipLabelWidth(getRelationshipLabelText(d, relationTypes)) / 2)
      .attr('y', -12)
      .attr('width', d => getRelationshipLabelWidth(getRelationshipLabelText(d, relationTypes)))
      .attr('height', 24)
      .attr('rx', 2)
      .attr('fill', graphColors.paper)
      .attr('stroke', d => getRelationColor(d.relationship_type, relationTypes))
      .attr('stroke-width', 1.1)
      .attr('stroke-opacity', 0.82);

    relationshipLabel.append('text')
      .text(d => getRelationshipLabelText(d, relationTypes))
      .attr('text-anchor', 'middle')
      .attr('y', 4)
      .attr('fill', graphColors.ink)
      .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
      .attr('font-size', '11px')
      .attr('font-weight', '700');

    relationshipLabel.append('title').text(d => (
      `${getRelationLabel(d.relationship_type, relationTypes)} · ${formatAffinity(d.affinity)}`
    ));

    // ── 方形档案照片节点 ──
    const nodeGroup = g.append('g').attr('class', 'nodes');
    const node = nodeGroup.selectAll('g').data(nodes).join('g')
      .attr('opacity', 0)
      .attr('class', 'archive-photo-node')
      .attr('cursor', 'pointer')
      .attr('tabindex', 0)
      .attr('focusable', true)
      .attr('role', 'button')
      .attr('aria-pressed', 'false')
      .attr('aria-label', d => (
        `${d.node_type === 'player' ? '玩家' : '角色'} ${d.display_name || d.name}，按空格聚焦关系，按回车打开档案`
      ))
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

    // 方形头像裁剪定义
    nodes.forEach(function(d) {
      const clipId = 'clip-' + d.character_id.replace(/[^a-zA-Z0-9]/g, '_');
      if (defs.select('#' + clipId).empty()) {
        defs.append('clipPath').attr('id', clipId)
          .append('rect')
          .attr('x', -nodeLayout.imageSize / 2)
          .attr('y', nodeLayout.imageTop)
          .attr('width', nodeLayout.imageSize)
          .attr('height', nodeLayout.imageSize)
          .attr('rx', 1.5);
      }
    });

    // 照片卡、头像和姓名纸条
    node.each(function(d) {
      const nodeElement = d3.select(this);
      const clipId = 'clip-' + d.character_id.replace(/[^a-zA-Z0-9]/g, '_');
      const accentColor = d.node_type === 'player'
        ? graphColors.player
        : (d.is_active ? graphColors.character : graphColors.inactive);
      nodeElement.append('rect')
        .attr('class', 'node-hit-target')
        .attr('x', -nodeLayout.cardWidth / 2)
        .attr('y', nodeLayout.cardTop)
        .attr('width', nodeLayout.cardWidth)
        .attr('height', nodeLayout.cardHeight)
        .attr('rx', 2)
        .attr('fill', 'transparent')
        .attr('pointer-events', 'all');
      const card = nodeElement.append('g')
        .attr('class', 'photo-card')
        .attr('filter', 'url(#archive-photo-shadow)');

      card.append('rect')
        .attr('class', 'photo-mount')
        .attr('x', -nodeLayout.cardWidth / 2)
        .attr('y', nodeLayout.cardTop)
        .attr('width', nodeLayout.cardWidth)
        .attr('height', nodeLayout.cardHeight)
        .attr('rx', 2)
        .attr('fill', graphColors.paper)
        .attr('stroke', accentColor)
        .attr('stroke-width', d.is_active ? 1.2 : 1.8)
        .attr('stroke-opacity', d.is_active ? 0.72 : 0.9)
        .attr('pointer-events', 'none');

      card.append('rect')
        .attr('x', -nodeLayout.imageSize / 2)
        .attr('y', nodeLayout.imageTop)
        .attr('width', nodeLayout.imageSize)
        .attr('height', nodeLayout.imageSize)
        .attr('rx', 1.5)
        .attr('fill', graphColors.surface)
        .attr('stroke', graphColors.ropeShadow)
        .attr('stroke-width', 0.8)
        .attr('stroke-opacity', 0.4)
        .attr('pointer-events', 'none');

      if (d.avatar_url) {
        card.append('image')
          .attr('href', d.avatar_url)
          .attr('x', -nodeLayout.imageSize / 2)
          .attr('y', nodeLayout.imageTop)
          .attr('width', nodeLayout.imageSize)
          .attr('height', nodeLayout.imageSize)
          .attr('clip-path', 'url(#' + clipId + ')')
          .attr('preserveAspectRatio', 'xMidYMid slice')
          .attr('filter', d.is_active ? null : 'url(#archive-inactive-photo)')
          .attr('opacity', d.is_active ? 1 : 0.56)
          .attr('pointer-events', 'none');
      } else {
        card.append('text')
          .text((d.name || d.display_name || d.character_id).charAt(0))
          .attr('text-anchor', 'middle')
          .attr('y', nodeLayout.imageTop + (nodeLayout.imageSize / 2))
          .attr('dy', '0.35em')
          .attr('fill', accentColor)
          .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
          .attr('font-size', W < 640 ? '24px' : '28px')
          .attr('font-weight', '700')
          .attr('pointer-events', 'none');
      }

      card.append('rect')
        .attr('x', -nodeLayout.imageSize / 2)
        .attr('y', nodeLayout.labelY - 13)
        .attr('width', nodeLayout.imageSize)
        .attr('height', 20)
        .attr('rx', 1)
        .attr('fill', graphColors.paperMuted)
        .attr('opacity', 0.72)
        .attr('pointer-events', 'none');

      card.append('text')
        .text(truncateNodeName(d.name || d.display_name || d.character_id, W < 640 ? 8 : 10))
        .attr('text-anchor', 'middle')
        .attr('y', nodeLayout.labelY)
        .attr('fill', graphColors.ink)
        .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
        .attr('font-size', `${nodeLayout.nameFontSize}px`)
        .attr('font-weight', '600')
        .attr('pointer-events', 'none');

      if (d.node_type === 'player') {
        const badgeWidth = W < 640 ? 27 : 30;
        card.append('rect')
          .attr('x', (nodeLayout.cardWidth / 2) - badgeWidth - 5)
          .attr('y', nodeLayout.cardTop + 6)
          .attr('width', badgeWidth)
          .attr('height', 15)
          .attr('rx', 2)
          .attr('fill', graphColors.paperMuted)
          .attr('stroke', graphColors.player)
          .attr('stroke-width', 0.8)
          .attr('pointer-events', 'none');
        card.append('text')
          .text('玩家')
          .attr('x', (nodeLayout.cardWidth / 2) - (badgeWidth / 2) - 5)
          .attr('y', nodeLayout.cardTop + 17)
          .attr('text-anchor', 'middle')
          .attr('fill', graphColors.player)
          .attr('font-size', '9px')
          .attr('font-weight', '700')
          .attr('font-family', 'Noto Sans SC, Microsoft YaHei, PingFang SC, system-ui, sans-serif')
          .attr('pointer-events', 'none');
      }

      const pinColor = d.node_type === 'player'
        ? graphColors.player
        : (d.is_active ? graphColors.pin : graphColors.inactive);
      const pin = nodeElement.append('g')
        .attr('class', 'pushpin')
        .attr('pointer-events', 'none');
      pin.append('line')
        .attr('x1', 0)
        .attr('y1', 2)
        .attr('x2', 0)
        .attr('y2', 10)
        .attr('stroke', graphColors.ropeShadow)
        .attr('stroke-width', 2)
        .attr('stroke-linecap', 'round')
        .attr('opacity', 0.7);
      pin.append('circle')
        .attr('cx', 1.6)
        .attr('cy', 2)
        .attr('r', nodeLayout.pinRadius + 1.4)
        .attr('fill', graphColors.ropeShadow)
        .attr('opacity', 0.34);
      pin.append('circle')
        .attr('class', 'pin-head')
        .attr('r', nodeLayout.pinRadius)
        .attr('fill', pinColor)
        .attr('stroke', graphColors.pinHighlight)
        .attr('stroke-width', 1.2);
      pin.append('circle')
        .attr('cx', -2)
        .attr('cy', -2)
        .attr('r', Math.max(1.5, nodeLayout.pinRadius * 0.28))
        .attr('fill', graphColors.pinHighlight)
        .attr('opacity', 0.78);

      nodeElement.append('title').text(
        `${d.node_type === 'player' ? '玩家' : '角色'}：${d.display_name || d.name}`
      );
    });

    const isIncidentTo = (link, nodeDatum) => (
      link.source.character_id === nodeDatum.character_id
      || link.target.character_id === nodeDatum.character_id
    );

    const syncLinkInteractivity = () => {
      linkHit
        .attr('pointer-events', link => isLinkVisible(link) ? 'stroke' : 'none')
        .attr('tabindex', link => isLinkVisible(link) ? 0 : -1)
        .attr('focusable', link => isLinkVisible(link) ? 'true' : 'false')
        .attr('aria-hidden', link => isLinkVisible(link) ? null : 'true')
        .style('cursor', link => isLinkVisible(link) ? 'pointer' : 'default')
        .filter(link => !isLinkVisible(link))
        .each(function blurHiddenLink() {
          if (document.activeElement === this) this.blur();
        });
    };

    const resetRopes = () => {
      ropeShadow
        .attr('stroke-opacity', link => getDefaultRopeOpacity('shadow', link))
        .attr('stroke-width', link => getLinkWidth(link) + 2);
      ropeBase
        .attr('stroke-opacity', link => getDefaultRopeOpacity('base', link))
        .attr('stroke-width', getLinkWidth);
      ropeFiber
        .attr('stroke-opacity', link => getDefaultRopeOpacity('fiber', link))
        .attr('stroke-width', link => Math.max(0.8, getLinkWidth(link) * 0.26));
    };

    const restoreDefaultView = () => {
      const connectedNodeIds = new Set();
      if (currentRelationType) {
        links.filter(isLinkVisible).forEach((link) => {
          connectedNodeIds.add(link.source.character_id);
          connectedNodeIds.add(link.target.character_id);
        });
      }
      node
        .attr('opacity', nodeDatum => (
          !currentRelationType || connectedNodeIds.has(nodeDatum.character_id) ? 1 : 0.16
        ))
        .attr('aria-pressed', nodeDatum => (
          lockedNode?.character_id === nodeDatum.character_id ? 'true' : 'false'
        ));
      node.select('.photo-card').attr('filter', 'url(#archive-photo-shadow)');
      node.select('.photo-mount')
        .attr('stroke-opacity', nodeDatum => nodeDatum.is_active ? 0.72 : 0.9)
        .attr('stroke-width', nodeDatum => nodeDatum.is_active ? 1.2 : 1.8);
      relationshipLabel.attr('opacity', 0);
      resetRopes();
      syncLinkInteractivity();
    };

    const applyNodeFocus = (focusedNode) => {
      const incidentLinks = new Set(
        links.filter(link => isLinkVisible(link) && isIncidentTo(link, focusedNode)),
      );
      const connectedNodeIds = new Set([focusedNode.character_id]);
      incidentLinks.forEach((link) => {
        connectedNodeIds.add(link.source.character_id);
        connectedNodeIds.add(link.target.character_id);
      });

      node
        .attr('opacity', nodeDatum => connectedNodeIds.has(nodeDatum.character_id) ? 1 : 0.16)
        .attr('aria-pressed', nodeDatum => (
          lockedNode?.character_id === nodeDatum.character_id ? 'true' : 'false'
        ));
      node.select('.photo-card')
        .attr('filter', nodeDatum => (
          nodeDatum.character_id === focusedNode.character_id
            ? 'url(#archive-photo-shadow-hover)'
            : 'url(#archive-photo-shadow)'
        ));
      node.select('.photo-mount')
        .attr('stroke-opacity', nodeDatum => (
          nodeDatum.character_id === focusedNode.character_id
            ? 1
            : (connectedNodeIds.has(nodeDatum.character_id) ? 0.78 : 0.28)
        ))
        .attr('stroke-width', nodeDatum => (
          nodeDatum.character_id === focusedNode.character_id ? 2.2 : 1.2
        ));
      ropeShadow
        .attr('stroke-opacity', link => (
          !isLinkVisible(link) ? 0 : (incidentLinks.has(link) ? 0.48 : 0.012)
        ))
        .attr('stroke-width', link => (
          incidentLinks.has(link) ? getLinkHoverWidth(link) + 2 : getLinkWidth(link) + 2
        ));
      ropeBase
        .attr('stroke-opacity', link => (
          !isLinkVisible(link) ? 0 : (incidentLinks.has(link) ? 1 : 0.02)
        ))
        .attr('stroke-width', link => (
          incidentLinks.has(link) ? getLinkHoverWidth(link) : getLinkWidth(link)
        ));
      ropeFiber
        .attr('stroke-opacity', link => (
          !isLinkVisible(link) ? 0 : (incidentLinks.has(link) ? 0.36 : 0.004)
        ))
        .attr('stroke-width', link => Math.max(0.8, (
          incidentLinks.has(link) ? getLinkHoverWidth(link) : getLinkWidth(link)
        ) * 0.26));
      relationshipLabel.attr('opacity', link => incidentLinks.has(link) ? 1 : 0);
    };

    const highlightRope = (focusedLink) => {
      const endpointIds = new Set([
        focusedLink.source.character_id,
        focusedLink.target.character_id,
      ]);
      node.attr('opacity', nodeDatum => endpointIds.has(nodeDatum.character_id) ? 1 : 0.16);
      node.select('.photo-card')
        .attr('filter', nodeDatum => (
          endpointIds.has(nodeDatum.character_id)
            ? 'url(#archive-photo-shadow-hover)'
            : 'url(#archive-photo-shadow)'
        ));
      node.select('.photo-mount')
        .attr('stroke-opacity', nodeDatum => endpointIds.has(nodeDatum.character_id) ? 1 : 0.28)
        .attr('stroke-width', nodeDatum => endpointIds.has(nodeDatum.character_id) ? 2 : 1.2);
      ropeShadow
        .attr('stroke-opacity', link => (
          !isLinkVisible(link) ? 0 : (link === focusedLink ? 0.5 : 0.012)
        ))
        .attr('stroke-width', link => (
          link === focusedLink ? getLinkHoverWidth(link) + 2 : getLinkWidth(link) + 2
        ));
      ropeBase
        .attr('stroke-opacity', link => (
          !isLinkVisible(link) ? 0 : (link === focusedLink ? 1 : 0.02)
        ))
        .attr('stroke-width', link => (
          link === focusedLink ? getLinkHoverWidth(link) : getLinkWidth(link)
        ));
      ropeFiber
        .attr('stroke-opacity', link => (
          !isLinkVisible(link) ? 0 : (link === focusedLink ? 0.38 : 0.004)
        ))
        .attr('stroke-width', link => Math.max(0.8, (
          link === focusedLink ? getLinkHoverWidth(link) : getLinkWidth(link)
        ) * 0.26));
      relationshipLabel.attr('opacity', link => link === focusedLink ? 1 : 0);
    };

    const restoreLockedOrDefault = () => {
      if (lockedNode) applyNodeFocus(lockedNode);
      else restoreDefaultView();
    };

    const toggleNodeLock = (nodeDatum) => {
      lockedNode = lockedNode?.character_id === nodeDatum.character_id ? null : nodeDatum;
      restoreLockedOrDefault();
    };

    linkHit
      .on('mouseenter focus', (event, link) => highlightRope(link))
      .on('mouseleave blur', restoreLockedOrDefault)
      .on('click', (event, link) => {
        event.stopPropagation();
        setEditEdge(link);
      })
      .on('keydown', (event, link) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        event.stopPropagation();
        setEditEdge(link);
      });

    node
      .on('mouseenter focus', (event, nodeDatum) => applyNodeFocus(nodeDatum))
      .on('mouseleave blur', restoreLockedOrDefault)
      .on('click', (event, nodeDatum) => {
        if (event.defaultPrevented) return;
        event.stopPropagation();
        toggleNodeLock(nodeDatum);
      })
      .on('keydown', (event, nodeDatum) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          event.stopPropagation();
          navigate(
            nodeDatum.node_type === 'player'
              ? '/persona'
              : characterEditorPath(nodeDatum.character_id),
          );
          return;
        }
        if (event.key === ' ') {
          event.preventDefault();
          event.stopPropagation();
          toggleNodeLock(nodeDatum);
          return;
        }
        if (event.key === 'Escape' && lockedNode) {
          event.preventDefault();
          event.stopPropagation();
          lockedNode = null;
          restoreDefaultView();
        }
      });

    svg.on('click', () => {
      lockedNode = null;
      restoreDefaultView();
      setEditEdge(null);
    });

    const viewController = {
      update({ density, relationType }) {
        currentEdgeDensity = density;
        currentRelationType = relationType;
        if (
          lockedNode
          && !links.some(link => isLinkVisible(link) && isIncidentTo(link, lockedNode))
        ) {
          lockedNode = null;
        }
        restoreLockedOrDefault();
      },
    };
    viewControllerRef.current = viewController;
    restoreDefaultView();

    // tick
    simulation.on('tick', () => {
      links.forEach((link) => {
        link.geometry = getEdgeGeometry(link);
      });
      ropeShadow.attr('d', link => link.geometry.path);
      ropeBase.attr('d', link => link.geometry.path);
      ropeFiber.attr('d', link => link.geometry.path);
      linkHit.attr('d', link => link.geometry.path);
      relationshipLabel.attr(
        'transform',
        link => `translate(${link.geometry.labelX},${link.geometry.labelY})`,
      );
      node.attr('transform', d => `translate(${d.x},${d.y}) rotate(${d.tilt})`);
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
      if (viewControllerRef.current === viewController) viewControllerRef.current = null;
      simulation.stop();
      centerTimeoutRef.current.cancel();
    };
  }, [graphSize.height, graphSize.width, network, navigate, relationTypes, theme]);

  useEffect(() => {
    viewControllerRef.current?.update({
      density: edgeDensity,
      relationType: selectedRelationType,
    });
  }, [edgeDensity, selectedRelationType]);

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
  const usedRelationTypes = relationTypes.filter(type => usedTypeValues.has(type.value));
  const relationTypeCounts = network.edges.reduce((counts, edge) => {
    const type = edge.relationship_type;
    if (type) counts.set(type, (counts.get(type) || 0) + 1);
    return counts;
  }, new Map());
  const isAuthError = !!error && /认证|未登录|401|token/i.test(error);

  return (
    <section className="archive-clue-wall relative h-[calc(100dvh-4rem)] min-h-[32rem] min-w-0 select-none overflow-hidden text-foreground">
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
                关系调查墙
              </h1>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-archive-mono text-[10px] text-muted-foreground">
                <span><span className="tabular-nums text-foreground">{characters.length}</span> 个节点</span>
                <span><span className="tabular-nums text-foreground">{network.edges.length}</span> 条关系</span>
              </div>
            </div>
          </div>
        </div>

        <div className="pointer-events-auto flex shrink-0 items-center gap-2">
          <div
            className="flex items-center rounded-md border border-border bg-card/88 p-1 shadow-lg backdrop-blur-md"
            role="group"
            aria-label="关系显示密度"
          >
            <Button
              type="button"
              size="sm"
              variant={edgeDensity === 'priority' ? 'secondary' : 'ghost'}
              onClick={() => setEdgeDensity('priority')}
              aria-pressed={edgeDensity === 'priority'}
              title={`突出每个角色最强的 ${FOCUS_LINKS_PER_NODE} 条关系`}
            >
              <Focus aria-hidden="true" />
              重点
            </Button>
            <Button
              type="button"
              size="sm"
              variant={edgeDensity === 'all' ? 'secondary' : 'ghost'}
              onClick={() => setEdgeDensity('all')}
              aria-pressed={edgeDensity === 'all'}
              title="提高全部关系的可见度"
            >
              <Network aria-hidden="true" />
              全部
            </Button>
          </div>

          <RelationTypeFilter
            value={selectedRelationType}
            onChange={setSelectedRelationType}
            usedRelationTypes={usedRelationTypes}
            relationTypeCounts={relationTypeCounts}
            totalCount={network.edges.length}
          />

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
          aria-label="由方形角色照片、图钉和彩色绳线组成的关系调查墙"
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
        </>
      )}
    </section>
  );
}

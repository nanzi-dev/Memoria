import {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useDeferredValue,
  useRef,
} from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Plus,
  Power,
  PowerOff,
  Trash2,
  Loader2,
  Search,
  Upload,
  FileText,
  X,
  Database,
  Edit2,
  RefreshCw,
  Link2,
  Eye,
  AlertCircle,
  CheckCircle2,
  Clock,
  PenTool,
  FileUp,
  BookOpen,
  Files,
  Layers3,
  CircleDot,
} from 'lucide-react';
import { knowledgeApi } from '../api/memoria';
import { useDialog } from '../context/DialogContext';
import { useUser } from '../context/UserContext';
import FadeContent from '../components/FadeContent';

const AUTH_ERROR_PATTERN = /认证|未登录|401|token/i;

const DOCUMENT_STATUS_MAP = {
  queued: { label: '队列中', tone: 'info', Icon: Clock },
  processing: { label: '处理中', tone: 'processing', Icon: Loader2 },
  ready: { label: '已就绪', tone: 'success', Icon: CheckCircle2 },
  failed: { label: '失败', tone: 'error', Icon: AlertCircle },
};

function getDocumentCount(base) {
  return Number(base?.document_count ?? base?.documents?.length ?? 0);
}

function hasPendingDocuments(base) {
  return Array.isArray(base?.documents)
    && base.documents.some(doc => doc.status === 'queued' || doc.status === 'processing');
}

function formatByteSize(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function mergeBaseSummary(current, detail) {
  const documents = Array.isArray(detail?.documents) ? detail.documents : null;
  return {
    ...current,
    ...detail,
    document_count: Number(detail?.document_count ?? documents?.length ?? current?.document_count ?? 0),
    ready_document_count: Number(
      detail?.ready_document_count
      ?? documents?.filter(doc => doc.status === 'ready').length
      ?? current?.ready_document_count
      ?? 0
    ),
    bindings: Array.isArray(detail?.bindings) ? detail.bindings : (current?.bindings || []),
  };
}

function useEscapeClose(show, onClose) {
  useEffect(() => {
    if (!show) return undefined;
    const handleKeyDown = event => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [show, onClose]);
}

const STATUS_FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'enabled', label: '已启用' },
  { id: 'disabled', label: '已停用' },
];

function SummaryMetric({ icon: Icon, label, value, tone = 'green' }) {
  const toneClass = tone === 'green'
    ? 'bg-cyber-green/10 text-cyber-green'
    : tone === 'amber'
    ? 'bg-amber-300/10 text-amber-200'
    : tone === 'muted'
    ? 'bg-white/[0.05] text-zinc-400'
    : 'bg-cyber-green/10 text-cyber-green';

  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${toneClass}`}>
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <p className="text-lg font-semibold leading-none text-zinc-100 tabular-nums">{value}</p>
        <p className="mt-1 text-xs text-zinc-500">{label}</p>
      </div>
    </div>
  );
}

export default function KnowledgeManager() {
  const navigate = useNavigate();
  const dialog = useDialog();
  const { user, loading: userLoading } = useUser();

  const [bases, setBases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [busyBaseId, setBusyBaseId] = useState(null);
  const listRequestRef = useRef(0);

  // 选中的知识库详情
  const [selectedBaseId, setSelectedBaseId] = useState(null);
  const [selectedBase, setSelectedBase] = useState(null);
  const [baseLoading, setBaseLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const detailRequestRef = useRef(0);

  // 模态框状态
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showBindingModal, setShowBindingModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showPasteModal, setShowPasteModal] = useState(false);
  const [showPreviewModal, setShowPreviewModal] = useState(false);

  const loadBases = useCallback(async ({ soft = false } = {}) => {
    const requestId = ++listRequestRef.current;
    if (userLoading) {
      if (soft) setRefreshing(true);
      else setLoading(true);
      return;
    }

    if (!user) {
      setBases([]);
      setError('未提供认证信息');
      setLoading(false);
      setRefreshing(false);
      return;
    }

    try {
      if (soft) setRefreshing(true);
      else setLoading(true);
      setError(null);
      const list = await knowledgeApi.listBases();
      if (listRequestRef.current !== requestId) return;
      setBases(Array.isArray(list) ? list : []);
    } catch (e) {
      if (listRequestRef.current !== requestId) return;
      const message = e.message || '知识库列表加载失败';
      setError(message);
      if (AUTH_ERROR_PATTERN.test(message)) setBases([]);
    } finally {
      if (listRequestRef.current === requestId) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [userLoading, user?.user_id]);

  useEffect(() => {
    loadBases();
    return () => { listRequestRef.current += 1; };
  }, [loadBases]);

  // 加载选中知识库的详细信息
  const loadBaseDetail = useCallback(async (baseId, { soft = false } = {}) => {
    if (!baseId) return;
    const requestId = ++detailRequestRef.current;
    if (!soft) {
      setBaseLoading(true);
      setDetailError('');
    }
    try {
      const detail = await knowledgeApi.getBase(baseId);
      if (detailRequestRef.current !== requestId) return;
      setSelectedBase(detail);
      setBases(prev => prev.map(base => (
        base.knowledge_base_id === baseId ? mergeBaseSummary(base, detail) : base
      )));
    } catch (e) {
      if (!soft && detailRequestRef.current === requestId) {
        setDetailError(e.message || '加载知识库详情失败');
      }
    } finally {
      if (detailRequestRef.current === requestId) setBaseLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedBaseId) {
      loadBaseDetail(selectedBaseId);
    } else {
      detailRequestRef.current += 1;
      setSelectedBase(null);
      setDetailError('');
      setBaseLoading(false);
    }
  }, [selectedBaseId, loadBaseDetail]);

  useEffect(() => {
    if (loading) return;
    if (bases.length === 0) {
      setSelectedBaseId(null);
      setSelectedBase(null);
      return;
    }
    if (!selectedBaseId || !bases.some(base => base.knowledge_base_id === selectedBaseId)) {
      setSelectedBaseId(bases[0].knowledge_base_id);
      setSelectedBase(bases[0]);
    }
  }, [bases, loading, selectedBaseId]);

  const shouldPollSelectedBase = selectedBase?.knowledge_base_id === selectedBaseId
    && hasPendingDocuments(selectedBase);

  useEffect(() => {
    if (!selectedBaseId || !shouldPollSelectedBase) return undefined;

    let cancelled = false;
    let timerId;
    const poll = async () => {
      if (document.visibilityState !== 'hidden') {
        await loadBaseDetail(selectedBaseId, { soft: true });
      }
      if (!cancelled) timerId = window.setTimeout(poll, 1500);
    };

    timerId = window.setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, [selectedBaseId, shouldPollSelectedBase, loadBaseDetail]);

  // 切换启停状态
  async function handleToggleBase(base) {
    if (!base) return;
    setBusyBaseId(base.knowledge_base_id);
    setNotice('');
    try {
      await knowledgeApi.setEnabled(base.knowledge_base_id, !base.is_enabled);
      setBases(prev => prev.map(b =>
        b.knowledge_base_id === base.knowledge_base_id ? { ...b, is_enabled: !b.is_enabled } : b
      ));
      setNotice(!base.is_enabled ? '知识库已启用' : '知识库已禁用');
      setTimeout(() => setNotice(''), 1800);
      if (selectedBaseId === base.knowledge_base_id) {
        loadBaseDetail(base.knowledge_base_id);
      }
    } catch (e) {
      setError(e.message || '切换状态失败');
    } finally {
      setBusyBaseId(null);
    }
  }

  // 删除知识库
  async function handleDeleteBase(base) {
    if (!base) return;
    const ok = await dialog.confirm({
      title: '删除知识库',
      message: `确定删除知识库「${base.name}」吗？\n这将删除所有相关文档和向量数据。此操作不可撤销。`,
      variant: 'danger',
      confirmText: '删除',
    });
    if (!ok) return;

    setBusyBaseId(base.knowledge_base_id);
    setNotice('');
    try {
      await knowledgeApi.deleteBase(base.knowledge_base_id);
      setBases(prev => prev.filter(b => b.knowledge_base_id !== base.knowledge_base_id));
      setNotice('知识库已删除');
      setTimeout(() => setNotice(''), 1800);
      if (selectedBaseId === base.knowledge_base_id) {
        setSelectedBaseId(null);
        setSelectedBase(null);
      }
    } catch (e) {
      setError(e.message || '删除知识库失败');
    } finally {
      setBusyBaseId(null);
    }
  }

  // 筛选与统计
  const deferredSearch = useDeferredValue(search);
  const filtered = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();
    return bases.filter(b => {
      if (statusFilter === 'enabled' && !b.is_enabled) return false;
      if (statusFilter === 'disabled' && b.is_enabled) return false;
      if (!q) return true;
      const searchText = [
        b.name,
        b.description,
        b.knowledge_base_id,
      ].filter(Boolean).join(' ').toLowerCase();
      return searchText.includes(q);
    });
  }, [bases, deferredSearch, statusFilter]);

  const totalDocs = bases.reduce((sum, base) => sum + getDocumentCount(base), 0);
  const enabledCount = bases.filter(b => b.is_enabled).length;
  const isAuthError = !!error && AUTH_ERROR_PATTERN.test(error);
  const isAuthBlocked = !user || isAuthError;
  const selectedSummary = bases.find(base => base.knowledge_base_id === selectedBaseId) || null;

  function handleSelectBase(base) {
    setSelectedBase(base);
    setSelectedBaseId(base.knowledge_base_id);
  }

  return (
    <div className="memoria-page memoria-app-page relative min-h-dvh overflow-x-hidden font-character text-zinc-100">
      <a
        href="#knowledge-workspace"
        className="memoria-skip-link"
      >
        跳到知识库工作区
      </a>

      <header className="memoria-app-header sticky top-0 z-30 border-b">
        <div className="mx-auto flex max-w-[1480px] items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => navigate('/')}
              aria-label="返回首页"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] text-zinc-400 transition-colors hover:border-cyber-green/25 hover:bg-cyber-green/[0.06] hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <BookOpen size={17} className="shrink-0 text-cyber-green" />
                <h1 className="truncate text-lg font-semibold text-zinc-100 sm:text-xl">知识库管理</h1>
              </div>
              <p className="mt-0.5 hidden text-xs text-zinc-500 sm:block">整理资料、配置生效范围并检查文档处理状态</p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => loadBases({ soft: true })}
              disabled={isAuthBlocked || loading || refreshing}
              aria-label="刷新知识库"
              title="刷新"
              className="flex h-11 w-11 items-center justify-center rounded-lg border border-white/[0.08] text-zinc-400 transition-colors hover:border-cyber-green/25 hover:bg-cyber-green/[0.06] hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            </button>
            <button
              type="button"
              onClick={() => setShowCreateModal(true)}
              disabled={isAuthBlocked || loading}
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-cyber-green px-3.5 text-sm font-semibold text-[#09100b] transition-colors hover:bg-[#b8f7b0] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#090d11] disabled:cursor-not-allowed disabled:opacity-40 sm:px-4"
            >
              <Plus size={17} />
              <span className="hidden sm:inline">新建知识库</span>
              <span className="sm:hidden">新建</span>
            </button>
          </div>
        </div>
      </header>

      <main id="knowledge-workspace" className="relative z-10 mx-auto max-w-[1480px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        {notice && (
          <div role="status" aria-live="polite" className="fixed right-4 top-20 z-50 flex items-center gap-2 rounded-lg border border-cyber-green/25 bg-[#111a15] px-4 py-3 text-sm text-cyber-green shadow-2xl animate-fade-up sm:right-6">
            <CheckCircle2 size={16} />
            <span>{notice}</span>
          </div>
        )}

        <FadeContent className="mb-5 border-b border-white/[0.07] pb-5">
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
            <SummaryMetric icon={Layers3} label="知识库" value={bases.length} />
            <SummaryMetric icon={CircleDot} label="已启用" value={enabledCount} tone="green" />
            <SummaryMetric icon={Files} label="文档总数" value={totalDocs} tone="amber" />
            <SummaryMetric icon={PowerOff} label="已停用" value={bases.length - enabledCount} tone="muted" />
          </div>
        </FadeContent>

        <div className="grid items-start gap-4 lg:grid-cols-[minmax(290px,360px)_minmax(0,1fr)] lg:gap-5">
          <aside className="memoria-panel overflow-hidden">
            <div className="border-b border-white/[0.07] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-zinc-100">资料库</h2>
                  <p className="mt-1 text-xs text-zinc-500">{filtered.length} 个结果</p>
                </div>
                <Database size={18} className="text-cyber-green/65" />
              </div>

              <label htmlFor="knowledge-search" className="mt-4 block text-xs font-medium text-zinc-400">
                搜索知识库
              </label>
              <div className="relative mt-2">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                <input
                  id="knowledge-search"
                  type="search"
                  value={search}
                  onChange={event => setSearch(event.target.value)}
                  placeholder="名称、描述或 ID"
                  className="min-h-11 w-full rounded-lg border border-cyber-green/12 bg-black/25 pl-9 pr-10 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-600 focus:border-cyber-green/40 focus:ring-2 focus:ring-cyber-green/10"
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch('')}
                    aria-label="清空搜索"
                    title="清空搜索"
                    className="absolute right-0 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-white/[0.05] hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35"
                  >
                    <X size={15} />
                  </button>
                )}
              </div>

              <div className="mt-3 grid grid-cols-3 rounded-lg bg-black/25 p-1" aria-label="按状态筛选">
                {STATUS_FILTERS.map(option => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setStatusFilter(option.id)}
                    aria-pressed={statusFilter === option.id}
                    className={`min-h-11 rounded-md px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 ${
                      statusFilter === option.id
                        ? 'bg-cyber-green/[0.09] text-cyber-green shadow-sm'
                        : 'text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-300'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {error && (
              <div role="alert" className="m-3 rounded-lg border border-red-400/20 bg-red-400/[0.06] p-3">
                <div className="flex items-start gap-2 text-sm leading-5 text-red-100/85">
                  <AlertCircle size={16} className="mt-0.5 shrink-0" />
                  <p>{error}</p>
                </div>
                <button
                  type="button"
                  onClick={isAuthError ? () => navigate('/') : () => loadBases()}
                  className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-300/20 px-3 text-xs font-medium text-red-100/80 transition-colors hover:bg-red-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300/35"
                >
                  {!isAuthError && <RefreshCw size={14} />}
                  {isAuthError ? '返回首页登录' : '重新加载'}
                </button>
              </div>
            )}

            {loading && (
              <div className="space-y-2 p-3" aria-label="正在加载知识库">
                {[0, 1, 2, 3].map(item => (
                  <div key={item} className="h-[88px] animate-pulse rounded-lg bg-white/[0.035]" />
                ))}
              </div>
            )}

            {!loading && !error && filtered.length === 0 && (
              <div className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
                <Database size={30} className="text-zinc-700" />
                <p className="mt-3 text-sm font-medium text-zinc-300">
                  {bases.length === 0 ? '还没有知识库' : '没有匹配的知识库'}
                </p>
                <p className="mt-1 text-xs leading-5 text-zinc-600">
                  {bases.length === 0 ? '创建后即可添加文档与绑定范围' : '尝试调整关键词或状态筛选'}
                </p>
                <button
                  type="button"
                  onClick={bases.length === 0
                    ? () => setShowCreateModal(true)
                    : () => { setSearch(''); setStatusFilter('all'); }}
                  className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg border border-white/[0.09] px-3 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35"
                >
                  {bases.length === 0 ? <Plus size={14} /> : <X size={14} />}
                  {bases.length === 0 ? '创建知识库' : '清除筛选'}
                </button>
              </div>
            )}

            {!loading && filtered.length > 0 && (
              <div className="max-h-[560px] space-y-1.5 overflow-y-auto p-2 lg:max-h-[calc(100dvh-315px)]">
                {filtered.map((base, index) => {
                  const isSelected = selectedBaseId === base.knowledge_base_id;
                  const docCount = getDocumentCount(base);
                  const readyCount = Number(base.ready_document_count ?? 0);

                  return (
                    <FadeContent key={base.knowledge_base_id} delay={Math.min(index, 6) * 0.025}>
                      <button
                        type="button"
                        onClick={() => handleSelectBase(base)}
                        aria-current={isSelected ? 'true' : undefined}
                        className={`group relative w-full rounded-lg border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 ${
                          isSelected
                            ? 'border-cyber-green/25 bg-cyber-green/[0.07]'
                            : 'border-transparent hover:border-white/[0.07] hover:bg-white/[0.035]'
                        } ${base.is_enabled ? '' : 'opacity-65 hover:opacity-90'}`}
                      >
                        <span className={`absolute inset-y-3 left-0 w-0.5 rounded-r-full ${base.is_enabled ? 'bg-cyber-green' : 'bg-zinc-600'}`} />
                        <span className="flex items-start gap-3">
                          <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                            isSelected ? 'bg-cyber-green/10 text-cyber-green' : 'bg-white/[0.045] text-zinc-500'
                          }`}>
                            <Database size={16} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center justify-between gap-2">
                              <span className="truncate text-sm font-semibold text-zinc-100">{base.name}</span>
                              <span className={`shrink-0 text-[11px] font-medium ${base.is_enabled ? 'text-cyber-green/80' : 'text-zinc-500'}`}>
                                {base.is_enabled ? '启用' : '停用'}
                              </span>
                            </span>
                            <span className="mt-1 block truncate text-xs text-zinc-500">
                              {base.description || '暂无描述'}
                            </span>
                            <span className="mt-2 flex items-center gap-3 text-[11px] text-zinc-600">
                              <span>{docCount} 个文档</span>
                              <span>{readyCount} 个可用</span>
                            </span>
                          </span>
                        </span>
                      </button>
                    </FadeContent>
                  );
                })}
              </div>
            )}
          </aside>

          <section className="min-w-0">
            {selectedBaseId ? (
              <FadeContent key={selectedBaseId}>
                <BaseDetailPanel
                  base={selectedBase?.knowledge_base_id === selectedBaseId ? selectedBase : selectedSummary}
                  loading={baseLoading}
                  error={detailError}
                  busy={busyBaseId === selectedBaseId}
                  onRefresh={() => loadBaseDetail(selectedBaseId)}
                  onEdit={() => setShowEditModal(true)}
                  onToggle={() => handleToggleBase(selectedBase || selectedSummary)}
                  onDelete={() => handleDeleteBase(selectedBase || selectedSummary)}
                  onShowBindingModal={() => setShowBindingModal(true)}
                  onShowUploadModal={() => setShowUploadModal(true)}
                  onShowPasteModal={() => setShowPasteModal(true)}
                  onShowPreviewModal={() => setShowPreviewModal(true)}
                />
              </FadeContent>
            ) : (
              <div className="memoria-panel-muted flex min-h-[560px] flex-col items-center justify-center border-dashed px-6 text-center">
                <BookOpen size={36} className="text-zinc-700" />
                <h2 className="mt-4 text-base font-semibold text-zinc-300">选择一个知识库</h2>
                <p className="mt-2 max-w-sm text-sm leading-6 text-zinc-600">选中左侧知识库后，可在这里管理文档、绑定范围和启用状态。</p>
              </div>
            )}
          </section>
        </div>
      </main>

      {/* 创建知识库模态框 */}
      <CreateBaseModal
        show={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSuccess={(newBase) => {
          const createdBase = mergeBaseSummary({}, newBase);
          setBases(prev => [createdBase, ...prev]);
          setSelectedBase(createdBase);
          setSelectedBaseId(createdBase.knowledge_base_id);
          setShowCreateModal(false);
          setNotice('知识库创建成功');
          setTimeout(() => setNotice(''), 1800);
        }}
      />

      {/* 编辑知识库模态框 */}
      <EditBaseModal
        show={showEditModal}
        base={selectedBase}
        onClose={() => setShowEditModal(false)}
        onSuccess={(updated) => {
          setBases(prev => prev.map(b => b.knowledge_base_id === updated.knowledge_base_id ? mergeBaseSummary(b, updated) : b));
          setSelectedBase(updated);
          setShowEditModal(false);
          setNotice('知识库已更新');
          setTimeout(() => setNotice(''), 1800);
        }}
      />

      <BindingModal
        show={showBindingModal}
        base={selectedBase}
        onClose={() => setShowBindingModal(false)}
        onSuccess={async () => {
          setShowBindingModal(false);
          await loadBaseDetail(selectedBaseId);
          setNotice('绑定配置已更新');
          setTimeout(() => setNotice(''), 1800);
        }}
      />

      <UploadDocumentModal
        show={showUploadModal}
        base={selectedBase}
        onClose={() => setShowUploadModal(false)}
        onSuccess={async () => {
          setShowUploadModal(false);
          await loadBaseDetail(selectedBaseId);
          setNotice('文档已加入处理队列');
          setTimeout(() => setNotice(''), 1800);
        }}
      />

      <PasteDocumentModal
        show={showPasteModal}
        base={selectedBase}
        onClose={() => setShowPasteModal(false)}
        onSuccess={async () => {
          setShowPasteModal(false);
          await loadBaseDetail(selectedBaseId);
          setNotice('文本已加入处理队列');
          setTimeout(() => setNotice(''), 1800);
        }}
      />

      <PreviewModal
        show={showPreviewModal}
        base={selectedBase}
        onClose={() => setShowPreviewModal(false)}
      />
    </div>
  );
}

// ═══════════════════════════════════════════════
// 创建知识库模态框
// ═══════════════════════════════════════════════
function CreateBaseModal({ show, onClose, onSuccess }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  useEscapeClose(show, onClose);

  useEffect(() => {
    if (show) {
      setName('');
      setDescription('');
      setError('');
    }
  }, [show]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) {
      setError('请输入知识库名称');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      const newBase = await knowledgeApi.createBase({ name: name.trim(), description: description.trim() || null });
      onSuccess(newBase);
    } catch (err) {
      setError(err.message || '创建失败');
    } finally {
      setSubmitting(false);
    }
  }

  if (!show) return null;

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center p-4 font-mono">
      <div className="absolute inset-0 bg-black/78 backdrop-blur-md" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby="create-base-title" className="relative w-full max-w-md overflow-hidden rounded-lg border border-cyber-green/20 bg-[#0d0d14]/95 shadow-[0_0_70px_rgba(167,239,158,0.08)] animate-fade-up">
        <div className="absolute inset-0 pointer-events-none opacity-[0.04]" style={{
          backgroundImage: 'linear-gradient(#9AD7FF 1px, transparent 1px), linear-gradient(90deg, #9AD7FF 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }} />
        
        <form onSubmit={handleSubmit} className="relative p-5">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 id="create-base-title" className="text-sm font-bold tracking-wider text-zinc-100">创建知识库</h2>
              <p className="mt-1 text-[11px] text-zinc-400/70">新建一个独立的知识库</p>
            </div>
            <button type="button" onClick={onClose} aria-label="关闭创建知识库窗口" className="flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/40 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40">
              <X size={16} />
            </button>
          </div>

          {error && (
            <div role="alert" className="mb-4 rounded-lg border border-red-400/18 bg-red-400/[0.055] px-3 py-2 text-xs text-red-200/80">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label htmlFor="create-base-name" className="block text-[11px] font-bold text-zinc-300 mb-1.5">名称 *</label>
              <input
                id="create-base-name"
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                maxLength={120}
                placeholder="例如：游戏世界观设定"
                className="w-full rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 py-2 text-sm text-cyber-green/85 outline-none transition-all placeholder:text-cyber-green/22 focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10"
                autoFocus
              />
            </div>

            <div>
              <label htmlFor="create-base-description" className="block text-[11px] font-bold text-zinc-300 mb-1.5">描述</label>
              <textarea
                id="create-base-description"
                value={description}
                onChange={e => setDescription(e.target.value)}
                maxLength={2000}
                rows={3}
                placeholder="可选：简要描述该知识库的用途"
                className="w-full rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 py-2 text-sm text-cyber-green/85 outline-none transition-all placeholder:text-cyber-green/22 focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10 resize-none"
              />
            </div>
          </div>

          <div className="mt-5 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="min-h-[44px] rounded-lg border border-cyber-green/12 px-4 py-2 text-sm text-cyber-green/55 transition-all hover:border-cyber-green/25 hover:bg-cyber-green/5 hover:text-cyber-green/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex min-h-[44px] items-center gap-2 rounded-lg border border-cyber-green/35 bg-cyber-green/10 px-4 py-2 text-sm font-bold text-cyber-green transition-all hover:bg-cyber-green/20 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting && <Loader2 size={14} className="animate-spin" />}
              {submitting ? '创建中...' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════
// 编辑知识库模态框
// ═══════════════════════════════════════════════
function EditBaseModal({ show, base, onClose, onSuccess }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  useEscapeClose(show, onClose);

  useEffect(() => {
    if (show && base) {
      setName(base.name || '');
      setDescription(base.description || '');
      setError('');
    }
  }, [show, base]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!base) return;
    if (!name.trim()) {
      setError('请输入知识库名称');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      const updated = await knowledgeApi.updateBase(base.knowledge_base_id, {
        name: name.trim(),
        description: description.trim() || null,
      });
      onSuccess(updated);
    } catch (err) {
      setError(err.message || '更新失败');
    } finally {
      setSubmitting(false);
    }
  }

  if (!show || !base) return null;

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center p-4 font-mono">
      <div className="absolute inset-0 bg-black/78 backdrop-blur-md" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby="edit-base-title" className="relative w-full max-w-md overflow-hidden rounded-lg border border-cyber-green/20 bg-[#0d0d14]/95 shadow-[0_0_70px_rgba(167,239,158,0.08)] animate-fade-up">
        <form onSubmit={handleSubmit} className="relative p-5">
          <div className="flex items-start justify-between mb-4">
            <h2 id="edit-base-title" className="text-sm font-bold tracking-wider text-zinc-100">编辑知识库</h2>
            <button type="button" onClick={onClose} aria-label="关闭编辑知识库窗口" className="flex h-11 w-11 items-center justify-center rounded-lg text-cyber-green/40 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40">
              <X size={16} />
            </button>
          </div>

          {error && (
            <div role="alert" className="mb-4 rounded-lg border border-red-400/18 bg-red-400/[0.055] px-3 py-2 text-xs text-red-200/80">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label htmlFor="edit-base-name" className="block text-[11px] font-bold text-zinc-300 mb-1.5">名称 *</label>
              <input
                id="edit-base-name"
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                maxLength={120}
                className="w-full rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 py-2 text-sm text-cyber-green/85 outline-none transition-all focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10"
              />
            </div>
            <div>
              <label htmlFor="edit-base-description" className="block text-[11px] font-bold text-zinc-300 mb-1.5">描述</label>
              <textarea
                id="edit-base-description"
                value={description}
                onChange={e => setDescription(e.target.value)}
                maxLength={2000}
                rows={3}
                className="w-full rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 py-2 text-sm text-cyber-green/85 outline-none transition-all focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10 resize-none"
              />
            </div>
          </div>

          <div className="mt-5 flex justify-end gap-2">
            <button type="button" onClick={onClose} className="min-h-[44px] rounded-lg border border-cyber-green/12 px-4 py-2 text-sm text-cyber-green/55 transition-all hover:border-cyber-green/25 hover:bg-cyber-green/5 hover:text-cyber-green/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35">
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex min-h-[44px] items-center gap-2 rounded-lg border border-cyber-green/35 bg-cyber-green/10 px-4 py-2 text-sm font-bold text-cyber-green transition-all hover:bg-cyber-green/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting && <Loader2 size={14} className="animate-spin" />}
              {submitting ? '保存中...' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function BaseDetailPanel({
  base,
  loading,
  error,
  busy,
  onRefresh,
  onEdit,
  onToggle,
  onDelete,
  onShowBindingModal,
  onShowUploadModal,
  onShowPasteModal,
  onShowPreviewModal,
}) {
  const dialog = useDialog();
  const [deletingDocId, setDeletingDocId] = useState(null);
  const [retryingDocId, setRetryingDocId] = useState(null);

  async function handleDeleteDocument(doc) {
    const ok = await dialog.confirm({
      title: '删除文档',
      message: `确定删除文档「${doc.original_name}」吗？\n此操作不可撤销。`,
      variant: 'danger',
      confirmText: '删除',
    });
    if (!ok) return;

    setDeletingDocId(doc.document_id);
    try {
      await knowledgeApi.deleteDocument(doc.document_id);
      onRefresh();
    } catch (err) {
      await dialog.alert({ title: '删除失败', message: err.message || '删除文档失败', variant: 'danger' });
    } finally {
      setDeletingDocId(null);
    }
  }

  async function handleRetryDocument(doc) {
    setRetryingDocId(doc.document_id);
    try {
      await knowledgeApi.retryDocument(doc.document_id);
      onRefresh();
    } catch (err) {
      await dialog.alert({ title: '重试失败', message: err.message || '重试处理失败', variant: 'danger' });
    } finally {
      setRetryingDocId(null);
    }
  }

  const documents = Array.isArray(base?.documents) ? base.documents : [];
  const bindings = Array.isArray(base?.bindings) ? base.bindings : [];
  const readyDocumentCount = Number(
    base?.ready_document_count
    ?? documents.filter(doc => doc.status === 'ready').length
  );

  return (
    <section aria-labelledby="base-detail-title" className="memoria-panel overflow-hidden">
      <div className="border-b border-white/[0.07] px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg ${
              base?.is_enabled ? 'bg-cyber-green/10 text-cyber-green' : 'bg-white/[0.05] text-zinc-500'
            }`}>
              <BookOpen size={19} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="base-detail-title" className="break-words text-lg font-semibold text-zinc-100 sm:text-xl">
                  {base?.name || '加载中...'}
                </h2>
                {base && (
                  <span className={`rounded-md px-2 py-1 text-[11px] font-medium ${
                    base.is_enabled ? 'bg-cyber-green/10 text-cyber-green' : 'bg-white/[0.05] text-zinc-500'
                  }`}>
                    {base.is_enabled ? '已启用' : '已停用'}
                  </span>
                )}
              </div>
              {base && <p className="mt-1 truncate font-mono text-[11px] text-zinc-600">{base.knowledge_base_id}</p>}
              <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
                {base?.description || '暂无描述。可通过编辑补充该知识库的用途和内容范围。'}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1 self-end xl:self-auto">
            <button type="button" onClick={onEdit} disabled={!base || busy} aria-label="编辑知识库" title="编辑" className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-white/[0.05] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-40">
              <Edit2 size={16} />
            </button>
            <button type="button" onClick={onToggle} disabled={!base || busy} aria-label={base?.is_enabled ? '停用知识库' : '启用知识库'} title={base?.is_enabled ? '停用' : '启用'} className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-cyber-green/[0.07] hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-40">
              {busy ? <Loader2 size={16} className="animate-spin" /> : base?.is_enabled ? <PowerOff size={16} /> : <Power size={16} />}
            </button>
            <button type="button" onClick={onDelete} disabled={!base || busy} aria-label="删除知识库" title="删除" className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-red-400/[0.08] hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300/35 disabled:cursor-not-allowed disabled:opacity-40">
              <Trash2 size={16} />
            </button>
          </div>
        </div>
      </div>

      {loading && (
        <div className="space-y-4 p-5" aria-label="正在加载知识库详情">
          <div className="h-20 animate-pulse rounded-lg bg-white/[0.035]" />
          <div className="h-14 animate-pulse rounded-lg bg-white/[0.035]" />
          <div className="h-52 animate-pulse rounded-lg bg-white/[0.035]" />
        </div>
      )}

      {!loading && error && (
        <div role="alert" className="m-5 rounded-lg border border-red-400/20 bg-red-400/[0.06] p-4">
          <p className="text-sm text-red-100/85">{error}</p>
          <button type="button" onClick={onRefresh} className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-300/20 px-3 text-xs font-medium text-red-100/80 hover:bg-red-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/40">
            <RefreshCw size={13} /> 重新加载
          </button>
        </div>
      )}

      {!loading && !error && base && (
        <div>
          <dl className="grid grid-cols-2 border-b border-white/[0.07] bg-black/10 sm:grid-cols-4">
            {[
              ['文档', getDocumentCount(base)],
              ['已就绪', readyDocumentCount],
              ['绑定范围', bindings.length],
              ['运行状态', base.is_enabled ? '参与检索' : '暂停检索'],
            ].map(([label, value], index) => (
              <div
                key={label}
                className={`px-4 py-3 sm:px-5 ${
                  index % 2 === 0 ? 'border-r border-white/[0.06]' : ''
                } ${index < 2 ? 'border-b border-white/[0.06] sm:border-b-0' : ''} ${
                  index === 1 ? 'sm:border-r' : ''
                }`}
              >
                <dt className="text-[11px] text-zinc-600">{label}</dt>
                <dd className="mt-1 text-sm font-semibold text-zinc-200 tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="grid grid-cols-2 gap-2 border-b border-white/[0.07] p-4 sm:p-5 xl:grid-cols-4">
            <button
              type="button"
              onClick={onShowUploadModal}
              disabled={busy}
              className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-cyber-green px-3 text-sm font-semibold text-[#09100b] transition-colors hover:bg-[#b8f7b0] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/45 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <Upload size={16} />
              上传文件
            </button>
            <button
              type="button"
              onClick={onShowPasteModal}
              disabled={busy}
              className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-cyber-green/20 bg-cyber-green/[0.055] px-3 text-sm font-medium text-cyber-green transition-colors hover:bg-cyber-green/[0.09] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <PenTool size={16} />
              粘贴文本
            </button>
            <button
              type="button"
              onClick={onShowBindingModal}
              disabled={busy}
              className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-white/[0.09] px-3 text-sm font-medium text-zinc-300 transition-colors hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/35 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <Link2 size={16} />
              管理绑定
            </button>
            <button
              type="button"
              onClick={onShowPreviewModal}
              disabled={busy}
              className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-white/[0.09] px-3 text-sm font-medium text-zinc-300 transition-colors hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <Eye size={16} />
              检索预览
            </button>
          </div>

          <section aria-labelledby="binding-summary-title" className="border-b border-white/[0.07] px-4 py-4 sm:px-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <Link2 size={15} className="shrink-0 text-amber-200/80" />
                <h3 id="binding-summary-title" className="text-sm font-semibold text-zinc-200">生效范围</h3>
              </div>
              <span className="text-xs text-zinc-600">{bindings.length} 项</span>
            </div>

            {bindings.length === 0 ? (
              <div className="mt-3 flex items-center justify-between gap-4 border-l-2 border-zinc-700 py-1 pl-3">
                <p className="text-xs leading-5 text-zinc-500">尚未绑定，该知识库不会进入任何对话上下文。</p>
                <button type="button" onClick={onShowBindingModal} className="min-h-11 shrink-0 rounded-md px-2 text-xs font-medium text-amber-200/75 hover:bg-amber-300/[0.05] hover:text-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/35">
                  去配置
                </button>
              </div>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {bindings.map((binding, index) => {
                  const targetLabel = binding.target_type === 'global'
                    ? '全局'
                    : binding.target_type === 'character'
                    ? '角色'
                    : '群聊';
                  return (
                    <span key={`${binding.target_type}-${binding.target_id || index}`} className="inline-flex min-h-8 max-w-full items-center gap-2 rounded-md border border-amber-300/10 bg-amber-300/[0.035] px-2.5 text-xs text-zinc-400">
                      <span className="shrink-0 font-medium text-amber-100/75">{targetLabel}</span>
                      <span className="truncate font-mono text-[11px] text-zinc-500">{binding.target_id || '所有上下文'}</span>
                    </span>
                  );
                })}
              </div>
            )}
          </section>

          <section aria-labelledby="document-list-title">
            <div className="flex items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-4 sm:px-5">
              <div className="flex min-w-0 items-center gap-2">
                <FileText size={15} className="shrink-0 text-cyber-green/70" />
                <h3 id="document-list-title" className="text-sm font-semibold text-zinc-200">文档</h3>
              </div>
              <span className="text-xs text-zinc-600">{documents.length} 项</span>
            </div>

            {documents.length === 0 ? (
              <div className="flex min-h-48 flex-col items-center justify-center px-5 py-10 text-center">
                <FileText size={30} className="text-zinc-700" />
                <p className="mt-3 text-sm font-medium text-zinc-400">暂无文档</p>
                <p className="mt-1 text-xs text-zinc-600">上传文件或粘贴文本后，可在此查看处理状态。</p>
              </div>
            ) : (
              <div className="divide-y divide-white/[0.06]">
                {documents.map(doc => {
                  const statusInfo = DOCUMENT_STATUS_MAP[doc.status] || DOCUMENT_STATUS_MAP.queued;
                  const StatusIcon = statusInfo.Icon;
                  const docBusy = deletingDocId === doc.document_id || retryingDocId === doc.document_id;
                  const statusClass = doc.status === 'ready'
                    ? 'bg-cyber-green/10 text-cyber-green'
                    : doc.status === 'failed'
                    ? 'bg-red-400/[0.08] text-red-300'
                    : 'bg-cyan-300/[0.08] text-cyan-200';

                  return (
                    <article key={doc.document_id} className="px-4 py-4 transition-colors hover:bg-white/[0.018] sm:px-5">
                      <div className="flex items-start gap-3">
                        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${statusClass}`}>
                          <StatusIcon size={16} className={doc.status === 'processing' ? 'animate-spin' : ''} />
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                            <div className="min-w-0">
                              <h4 className="break-words text-sm font-semibold text-zinc-200">{doc.original_name}</h4>
                              <p className="mt-1 truncate font-mono text-[10px] text-zinc-600">{doc.document_id}</p>
                              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500">
                                <span>{doc.source_type === 'upload' ? '文件上传' : '文本粘贴'}</span>
                                <span>{formatByteSize(doc.byte_size)}</span>
                                <span className={`font-medium ${
                                  doc.status === 'ready' ? 'text-cyber-green/75' :
                                  doc.status === 'failed' ? 'text-red-300/75' :
                                  'text-cyan-200/70'
                                }`}>
                                  {statusInfo.label}
                                </span>
                              </div>
                            </div>

                            <div className="flex shrink-0 items-center gap-1 self-end sm:self-start">
                              {doc.status === 'failed' && (
                                <button
                                  type="button"
                                  onClick={() => handleRetryDocument(doc)}
                                  disabled={docBusy}
                                  aria-label={`重试处理 ${doc.original_name}`}
                                  title="重试处理"
                                  className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-cyber-green/[0.07] hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/35 disabled:cursor-not-allowed disabled:opacity-45"
                                >
                                  {retryingDocId === doc.document_id ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => handleDeleteDocument(doc)}
                                disabled={docBusy}
                                aria-label={`删除文档 ${doc.original_name}`}
                                title="删除文档"
                                className="flex h-11 w-11 items-center justify-center rounded-lg text-zinc-600 transition-colors hover:bg-red-400/[0.08] hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300/35 disabled:cursor-not-allowed disabled:opacity-45"
                              >
                                {deletingDocId === doc.document_id ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                              </button>
                            </div>
                          </div>

                          {doc.error_message && (
                            <p className="mt-3 border-l-2 border-red-400/35 py-1 pl-3 text-xs leading-5 text-red-200/70">
                              {doc.error_message}
                            </p>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

function ModalFrame({ show, title, description, onClose, children, maxWidth = 'max-w-lg' }) {
  useEscapeClose(show, onClose);
  if (!show) return null;

  const titleId = `knowledge-modal-${title.replace(/\s+/g, '-')}`;
  return (
    <div className="fixed inset-0 z-[1300] flex items-center justify-center p-3 font-mono sm:p-5">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-md" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`relative flex max-h-[calc(100vh-1.5rem)] w-full ${maxWidth} flex-col overflow-hidden rounded-lg border border-cyber-green/20 bg-[#0d0d14]/98 shadow-[0_0_70px_rgba(167,239,158,0.08)] animate-fade-up sm:max-h-[calc(100vh-2.5rem)]`}
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-white/[0.06] px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <h2 id={titleId} className="text-sm font-bold tracking-wider text-zinc-100">{title}</h2>
            {description && <p className="mt-1 text-[11px] leading-5 text-zinc-400/70">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={`关闭${title}窗口`}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-cyber-green/40 transition-colors hover:bg-cyber-green/5 hover:text-cyber-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40"
          >
            <X size={17} />
          </button>
        </div>
        <div className="min-h-0 overflow-y-auto p-4 sm:p-5">{children}</div>
      </div>
    </div>
  );
}

function ModalError({ message }) {
  if (!message) return null;
  return (
    <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-red-400/18 bg-red-400/[0.055] px-3 py-2.5 text-xs leading-5 text-red-200/80">
      <AlertCircle size={14} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

function BindingModal({ show, base, onClose, onSuccess }) {
  const [targets, setTargets] = useState({ characters: [], group_threads: [] });
  const [globalEnabled, setGlobalEnabled] = useState(false);
  const [characterIds, setCharacterIds] = useState([]);
  const [groupIds, setGroupIds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!show || !base) return;
    const bindings = base.bindings || [];
    setGlobalEnabled(bindings.some(binding => binding.target_type === 'global'));
    setCharacterIds(bindings.filter(binding => binding.target_type === 'character').map(binding => binding.target_id));
    setGroupIds(bindings.filter(binding => binding.target_type === 'group_thread').map(binding => binding.target_id));
    setError('');
    setLoading(true);
    knowledgeApi.getBindingTargets()
      .then(result => setTargets({
        characters: Array.isArray(result?.characters) ? result.characters : [],
        group_threads: Array.isArray(result?.group_threads) ? result.group_threads : [],
      }))
      .catch(err => setError(err.message || '绑定目标加载失败'))
      .finally(() => setLoading(false));
  }, [show, base?.knowledge_base_id]);

  function toggleId(setter, current, id) {
    setter(current.includes(id) ? current.filter(item => item !== id) : [...current, id]);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!base) return;
    setSubmitting(true);
    setError('');
    const bindings = [
      ...(globalEnabled ? [{ target_type: 'global', target_id: '' }] : []),
      ...characterIds.map(target_id => ({ target_type: 'character', target_id })),
      ...groupIds.map(target_id => ({ target_type: 'group_thread', target_id })),
    ];
    try {
      await knowledgeApi.setBindings(base.knowledge_base_id, bindings);
      await onSuccess();
    } catch (err) {
      setError(err.message || '保存绑定失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalFrame
      show={show && !!base}
      title="管理绑定"
      description="决定该知识库在哪些对话上下文中参与检索。"
      onClose={onClose}
      maxWidth="max-w-2xl"
    >
      <form onSubmit={handleSubmit}>
        <ModalError message={error} />
        {loading ? (
          <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-cyber-green/45">
            <Loader2 size={17} className="animate-spin" /> 加载绑定目标...
          </div>
        ) : (
          <div className="space-y-5">
            <label className="flex min-h-[48px] cursor-pointer items-center gap-3 rounded-lg border border-amber-400/14 bg-amber-400/[0.035] px-3 py-2.5 hover:bg-amber-400/[0.06]">
              <input
                type="checkbox"
                checked={globalEnabled}
                onChange={event => setGlobalEnabled(event.target.checked)}
                className="h-4 w-4 accent-[#A7EF9E]"
              />
              <span>
                <span className="block text-sm font-bold text-amber-100/85">全局生效</span>
                <span className="mt-0.5 block text-[11px] text-zinc-400/65">所有单聊和群聊上下文均可使用</span>
              </span>
            </label>

            <BindingTargetList
              title="角色"
              emptyText="暂无可绑定角色"
              items={targets.characters}
              idKey="character_id"
              selectedIds={characterIds}
              onToggle={id => toggleId(setCharacterIds, characterIds, id)}
            />
            <BindingTargetList
              title="群聊"
              emptyText="暂无可绑定群聊"
              items={targets.group_threads}
              idKey="group_thread_id"
              selectedIds={groupIds}
              onToggle={id => toggleId(setGroupIds, groupIds, id)}
            />
          </div>
        )}

        <div className="mt-5 flex flex-col-reverse gap-2 border-t border-white/[0.06] pt-4 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="min-h-[44px] rounded-lg border border-white/10 px-4 text-sm text-zinc-300/70 hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20">取消</button>
          <button type="submit" disabled={loading || submitting} className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/10 px-4 text-sm font-bold text-cyber-green hover:bg-cyber-green/18 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40 disabled:cursor-not-allowed disabled:opacity-45">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
            {submitting ? '保存中...' : '保存绑定'}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}

function BindingTargetList({ title, emptyText, items, idKey, selectedIds, onToggle }) {
  return (
    <fieldset>
      <legend className="mb-2 text-xs font-bold tracking-wider text-zinc-300">{title}</legend>
      {items.length === 0 ? (
        <p className="rounded-lg border border-white/[0.06] px-3 py-4 text-xs text-zinc-500">{emptyText}</p>
      ) : (
        <div className="grid max-h-44 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
          {items.map(item => {
            const id = item[idKey];
            return (
              <label key={id} className="flex min-h-[48px] cursor-pointer items-center gap-3 rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2 hover:border-cyber-green/18 hover:bg-cyber-green/[0.035]">
                <input type="checkbox" checked={selectedIds.includes(id)} onChange={() => onToggle(id)} className="h-4 w-4 shrink-0 accent-[#9AD7FF]" />
                <span className="min-w-0">
                  <span className="block truncate text-sm text-zinc-200/85">{item.name || id}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-zinc-500">{id}</span>
                </span>
              </label>
            );
          })}
        </div>
      )}
    </fieldset>
  );
}

function UploadDocumentModal({ show, base, onClose, onSuccess }) {
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (show) {
      setFile(null);
      setError('');
    }
  }, [show]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!file || !base) {
      setError('请选择要上传的文件');
      return;
    }
    if (!/\.(txt|md|pdf|docx)$/i.test(file.name)) {
      setError('仅支持 TXT、Markdown、PDF 和 DOCX 文件');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await knowledgeApi.uploadDocument(base.knowledge_base_id, file);
      await onSuccess();
    } catch (err) {
      setError(err.message || '上传失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalFrame show={show && !!base} title="上传文档" description={`添加文件到「${base?.name || ''}」`} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <ModalError message={error} />
        <label htmlFor="knowledge-upload-file" className="sr-only">选择要上传的文档</label>
        <input
          id="knowledge-upload-file"
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,.pdf,.docx"
          onChange={event => setFile(event.target.files?.[0] || null)}
          className="sr-only"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="flex min-h-48 w-full flex-col items-center justify-center rounded-lg border border-dashed border-cyber-green/22 bg-cyber-green/[0.025] px-5 text-center transition-colors hover:border-cyber-green/40 hover:bg-cyber-green/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40"
        >
          <FileUp size={30} className="text-cyber-green/65" />
          <span className="mt-3 max-w-full break-all text-sm font-bold text-zinc-200/85">{file ? file.name : '选择文件'}</span>
          <span className="mt-2 text-[11px] leading-5 text-zinc-400/60">TXT、MD、PDF、DOCX，服务器默认上限 10 MB</span>
          {file && <span className="mt-1 text-[10px] text-cyber-green/55">{(file.size / 1024 / 1024).toFixed(2)} MB</span>}
        </button>
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="min-h-[44px] rounded-lg border border-white/10 px-4 text-sm text-zinc-300/70 hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20">取消</button>
          <button type="submit" disabled={submitting || !file} className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/10 px-4 text-sm font-bold text-cyber-green hover:bg-cyber-green/18 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40 disabled:cursor-not-allowed disabled:opacity-45">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            {submitting ? '上传中...' : '上传并处理'}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}

function PasteDocumentModal({ show, base, onClose, onSuccess }) {
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (show) {
      setTitle('');
      setText('');
      setError('');
    }
  }, [show]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!title.trim() || !text.trim() || !base) {
      setError('请填写文档标题和内容');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await knowledgeApi.pasteDocument(base.knowledge_base_id, { title: title.trim(), text: text.trim() });
      await onSuccess();
    } catch (err) {
      setError(err.message || '添加文本失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalFrame show={show && !!base} title="粘贴文本" description={`直接添加纯文本到「${base?.name || ''}」`} onClose={onClose} maxWidth="max-w-2xl">
      <form onSubmit={handleSubmit}>
        <ModalError message={error} />
        <label className="block text-xs font-bold text-zinc-300">
          文档标题
          <input value={title} onChange={event => setTitle(event.target.value)} maxLength={180} autoFocus placeholder="例如：北区交通规则" className="mt-2 min-h-[44px] w-full rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 text-sm font-normal text-cyber-green/85 outline-none placeholder:text-cyber-green/22 focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10" />
        </label>
        <label className="mt-4 block text-xs font-bold text-zinc-300">
          文档内容
          <textarea value={text} onChange={event => setText(event.target.value)} rows={11} placeholder="粘贴需要索引的知识内容..." className="mt-2 w-full resize-y rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 py-3 text-sm font-normal leading-6 text-cyber-green/85 outline-none placeholder:text-cyber-green/22 focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10" />
        </label>
        <div className="mt-2 text-right text-[10px] text-zinc-500">{text.length.toLocaleString()} 字符</div>
        <div className="mt-5 flex flex-col-reverse gap-2 border-t border-white/[0.06] pt-4 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="min-h-[44px] rounded-lg border border-white/10 px-4 text-sm text-zinc-300/70 hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20">取消</button>
          <button type="submit" disabled={submitting} className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/10 px-4 text-sm font-bold text-cyber-green hover:bg-cyber-green/18 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40 disabled:cursor-not-allowed disabled:opacity-45">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <PenTool size={14} />}
            {submitting ? '提交中...' : '添加并处理'}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}

function PreviewModal({ show, base, onClose }) {
  const [query, setQuery] = useState('');
  const [characterId, setCharacterId] = useState('');
  const [groupThreadId, setGroupThreadId] = useState('');
  const [targets, setTargets] = useState({ characters: [], group_threads: [] });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [targetsLoading, setTargetsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!show) return;
    setQuery('');
    setCharacterId('');
    setGroupThreadId('');
    setResult(null);
    setError('');
    setTargetsLoading(true);
    knowledgeApi.getBindingTargets()
      .then(data => setTargets({
        characters: Array.isArray(data?.characters) ? data.characters : [],
        group_threads: Array.isArray(data?.group_threads) ? data.group_threads : [],
      }))
      .catch(err => setError(err.message || '检索上下文加载失败'))
      .finally(() => setTargetsLoading(false));
  }, [show, base?.knowledge_base_id]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!query.trim() || !base) {
      setError('请输入检索内容');
      return;
    }
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const response = await knowledgeApi.preview({
        query: query.trim(),
        character_id: characterId || null,
        group_thread_id: groupThreadId || null,
        knowledge_base_id: base.knowledge_base_id,
      });
      setResult(response);
    } catch (err) {
      setError(err.message || '检索预览失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <ModalFrame show={show && !!base} title="检索预览" description={`仅检索「${base?.name || ''}」中当前上下文可访问的已就绪内容。`} onClose={onClose} maxWidth="max-w-3xl">
      <form onSubmit={handleSubmit}>
        <ModalError message={error} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-bold text-zinc-300">
            角色上下文
            <select value={characterId} onChange={event => setCharacterId(event.target.value)} disabled={targetsLoading} className="mt-2 min-h-[44px] w-full rounded-lg border border-white/10 bg-[#11131a] px-3 text-sm font-normal text-zinc-200 outline-none focus:border-cyber-green/35 focus:ring-2 focus:ring-cyber-green/10 disabled:opacity-50">
              <option value="">不指定角色</option>
              {targets.characters.map(item => <option key={item.character_id} value={item.character_id}>{item.name}</option>)}
            </select>
          </label>
          <label className="text-xs font-bold text-zinc-300">
            群聊上下文
            <select value={groupThreadId} onChange={event => setGroupThreadId(event.target.value)} disabled={targetsLoading} className="mt-2 min-h-[44px] w-full rounded-lg border border-white/10 bg-[#11131a] px-3 text-sm font-normal text-zinc-200 outline-none focus:border-cyber-green/35 focus:ring-2 focus:ring-cyber-green/10 disabled:opacity-50">
              <option value="">不指定群聊</option>
              {targets.group_threads.map(item => <option key={item.group_thread_id} value={item.group_thread_id}>{item.name}</option>)}
            </select>
          </label>
        </div>
        <label className="mt-4 block text-xs font-bold text-zinc-300">
          检索内容
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input value={query} onChange={event => setQuery(event.target.value)} maxLength={4000} autoFocus placeholder="输入一个问题或事实关键词" className="min-h-[44px] min-w-0 flex-1 rounded-lg border border-cyber-green/12 bg-cyber-surface/70 px-3 text-sm font-normal text-cyber-green/85 outline-none placeholder:text-cyber-green/22 focus:border-cyber-green/42 focus:ring-2 focus:ring-cyber-green/10" />
            <button type="submit" disabled={loading} className="inline-flex min-h-[44px] shrink-0 items-center justify-center gap-2 rounded-lg border border-cyber-green/30 bg-cyber-green/10 px-5 text-sm font-bold text-cyber-green hover:bg-cyber-green/18 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-green/40 disabled:cursor-not-allowed disabled:opacity-45">
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              {loading ? '检索中...' : '检索'}
            </button>
          </div>
        </label>
      </form>

      {result && (
        <section className="mt-5 border-t border-white/[0.06] pt-4" aria-live="polite">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-xs font-bold tracking-wider text-zinc-300">命中结果</h3>
            <span className="text-[10px] text-zinc-500">{(result.sources || []).length} 条</span>
          </div>
          {(result.sources || []).length === 0 ? (
            <div className="mt-3 rounded-lg border border-white/[0.07] px-4 py-8 text-center text-xs leading-5 text-zinc-500">当前绑定上下文中没有达到相似度阈值的已就绪内容。</div>
          ) : (
            <div className="mt-3 space-y-2">
              {result.sources.map(source => (
                <article key={source.chunk_id} className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-bold text-zinc-200/90">{source.document_name}</p>
                      <p className="mt-0.5 truncate text-[10px] text-cyber-green/45">{source.knowledge_base_name}</p>
                    </div>
                    <span className="rounded-md border border-cyber-green/15 bg-cyber-green/[0.05] px-2 py-1 text-[10px] font-bold text-cyber-green/70">{Math.round(Number(source.similarity || 0) * 100)}%</span>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap break-words text-xs leading-5 text-zinc-400/75">{source.excerpt}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
    </ModalFrame>
  );
}

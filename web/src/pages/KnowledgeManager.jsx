import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Clock,
  Database,
  Edit2,
  Eye,
  FileText,
  FileUp,
  Files,
  Layers3,
  Link2,
  Loader2,
  PenTool,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

import ArchiveWorkspace from '@/archive/ArchiveWorkspace';
import { useArchiveShell } from '@/archive/ArchiveShell';
import FadeContent from '@/components/FadeContent';
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
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { knowledgeApi } from '@/api/memoria';
import { useDialog } from '@/context/DialogContext';
import { useUser } from '@/context/UserContext';
import { getKnowledgeSourceMatch } from './knowledgePreviewScore';

const AUTH_ERROR_PATTERN = /认证|未登录|401|token/i;

const DOCUMENT_STATUS_MAP = {
  queued: { label: '队列中', Icon: Clock },
  processing: { label: '处理中', Icon: Loader2 },
  ready: { label: '已就绪', Icon: CheckCircle2 },
  failed: { label: '失败', Icon: AlertCircle },
};

const STATUS_FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'enabled', label: '已启用' },
  { id: 'disabled', label: '已停用' },
];

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
    document_count: Number(
      detail?.document_count
      ?? documents?.length
      ?? current?.document_count
      ?? 0
    ),
    ready_document_count: Number(
      detail?.ready_document_count
      ?? documents?.filter(doc => doc.status === 'ready').length
      ?? current?.ready_document_count
      ?? 0
    ),
    bindings: Array.isArray(detail?.bindings) ? detail.bindings : (current?.bindings || []),
  };
}

function EmptyDetail({ icon: Icon, title, description }) {
  return (
    <div className="flex min-h-[480px] flex-col items-center justify-center border-y border-dashed border-border px-6 text-center">
      <Icon className="h-9 w-9 text-muted-foreground" aria-hidden="true" />
      <h2 className="mt-4 font-archive-serif text-lg font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

export default function KnowledgeManager() {
  const navigate = useNavigate();
  const dialog = useDialog();
  const { setPrimaryAction } = useArchiveShell();
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

  const [selectedBaseId, setSelectedBaseId] = useState(null);
  const [selectedBase, setSelectedBase] = useState(null);
  const [baseLoading, setBaseLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const detailRequestRef = useRef(0);

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

  async function handleToggleBase(base) {
    if (!base) return;
    setBusyBaseId(base.knowledge_base_id);
    setNotice('');
    try {
      await knowledgeApi.setEnabled(base.knowledge_base_id, !base.is_enabled);
      setBases(prev => prev.map(b => (
        b.knowledge_base_id === base.knowledge_base_id
          ? { ...b, is_enabled: !b.is_enabled }
          : b
      )));
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

  const deferredSearch = useDeferredValue(search);
  const filtered = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();
    return bases.filter(base => {
      if (statusFilter === 'enabled' && !base.is_enabled) return false;
      if (statusFilter === 'disabled' && base.is_enabled) return false;
      if (!q) return true;
      return [
        base.name,
        base.description,
        base.knowledge_base_id,
      ].filter(Boolean).join(' ').toLowerCase().includes(q);
    });
  }, [bases, deferredSearch, statusFilter]);

  const totalDocs = bases.reduce((sum, base) => sum + getDocumentCount(base), 0);
  const enabledCount = bases.filter(base => base.is_enabled).length;
  const isAuthError = !!error && AUTH_ERROR_PATTERN.test(error);
  const isAuthBlocked = !user || isAuthError;
  const selectedSummary = bases.find(base => base.knowledge_base_id === selectedBaseId) || null;
  const activeBase = selectedBase?.knowledge_base_id === selectedBaseId
    ? selectedBase
    : selectedSummary;

  const openCreate = useCallback(() => setShowCreateModal(true), []);
  const primaryAction = useMemo(() => (
    <Button type="button" size="lg" onClick={openCreate} disabled={isAuthBlocked || loading}>
      <Plus aria-hidden="true" />
      新建知识库
    </Button>
  ), [isAuthBlocked, loading, openCreate]);

  useEffect(() => {
    setPrimaryAction(primaryAction);
    return () => setPrimaryAction(null);
  }, [primaryAction, setPrimaryAction]);

  function handleSelectBase(base) {
    setSelectedBase(base);
    setSelectedBaseId(base.knowledge_base_id);
  }

  function clearFilters() {
    setSearch('');
    setStatusFilter('all');
  }

  const noticeNode = notice ? (
    <div
      role="status"
      aria-live="polite"
      className="fixed right-3 top-20 z-[950] flex max-w-[calc(100vw-1.5rem)] items-center gap-2 rounded-md border border-primary/30 bg-popover px-4 py-3 text-sm text-popover-foreground shadow-xl sm:right-5"
    >
      <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <span>{notice}</span>
    </div>
  ) : null;

  return (
    <>
      <ArchiveWorkspace
        className="[&_button]:min-h-11"
        indexLabel="Archive index / knowledge registry"
        title="知识档案"
        description="整理检索资料，核对文档处理状态，并配置知识在对话中的生效范围。"
        stats={[
          { icon: Layers3, label: '知识库', value: bases.length },
          { icon: CheckCircle2, label: '已启用', value: enabledCount },
          { icon: Files, label: '文档总数', value: totalDocs },
          { icon: PowerOff, label: '已停用', value: bases.length - enabledCount },
        ]}
        mobileAction={(
          <Button type="button" size="lg" onClick={openCreate} disabled={isAuthBlocked || loading}>
            <Plus aria-hidden="true" />
            新建知识库
          </Button>
        )}
        notice={noticeNode}
        directory={(
          <KnowledgeDirectory
            bases={bases}
            filtered={filtered}
            loading={loading}
            refreshing={refreshing}
            error={error}
            isAuthError={isAuthError}
            isAuthBlocked={isAuthBlocked}
            search={search}
            statusFilter={statusFilter}
            selectedBaseId={selectedBaseId}
            onSearchChange={setSearch}
            onStatusFilterChange={setStatusFilter}
            onClearFilters={clearFilters}
            onRefresh={() => loadBases({ soft: true })}
            onRecover={isAuthError ? () => navigate('/') : () => loadBases()}
            onCreate={openCreate}
            onSelect={handleSelectBase}
          />
        )}
        detail={selectedBaseId ? (
          <FadeContent key={selectedBaseId}>
            <BaseDetailPanel
              base={activeBase}
              loading={baseLoading}
              error={detailError}
              busy={busyBaseId === selectedBaseId}
              onRefresh={() => loadBaseDetail(selectedBaseId)}
              onEdit={() => setShowEditModal(true)}
              onToggle={() => handleToggleBase(activeBase)}
              onDelete={() => handleDeleteBase(activeBase)}
              onShowBindingModal={() => setShowBindingModal(true)}
              onShowUploadModal={() => setShowUploadModal(true)}
              onShowPasteModal={() => setShowPasteModal(true)}
              onShowPreviewModal={() => setShowPreviewModal(true)}
            />
          </FadeContent>
        ) : (
          <EmptyDetail
            icon={BookOpen}
            title="选择一个知识库"
            description="从目录中选择知识库后，这里会展开文档、绑定范围与运行状态。"
          />
        )}
      />

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

      <EditBaseModal
        show={showEditModal}
        base={selectedBase}
        onClose={() => setShowEditModal(false)}
        onSuccess={(updated) => {
          setBases(prev => prev.map(base => (
            base.knowledge_base_id === updated.knowledge_base_id
              ? mergeBaseSummary(base, updated)
              : base
          )));
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
    </>
  );
}

function KnowledgeDirectory({
  bases,
  filtered,
  loading,
  refreshing,
  error,
  isAuthError,
  isAuthBlocked,
  search,
  statusFilter,
  selectedBaseId,
  onSearchChange,
  onStatusFilterChange,
  onClearFilters,
  onRefresh,
  onRecover,
  onCreate,
  onSelect,
}) {
  return (
    <>
      <div className="border-b border-border p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-archive-serif text-base font-semibold text-foreground">资料目录</h2>
            <p className="mt-1 font-archive-mono text-[10px] text-muted-foreground">
              {filtered.length} records
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onRefresh}
            disabled={isAuthBlocked || loading || refreshing}
            aria-label="刷新知识库列表"
            title="刷新知识库列表"
          >
            <RefreshCw className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />
          </Button>
        </div>

        <label htmlFor="knowledge-search" className="mt-4 block text-xs font-medium text-foreground">
          搜索知识库
        </label>
        <div className="relative mt-2">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            id="knowledge-search"
            type="search"
            value={search}
            onChange={event => onSearchChange(event.target.value)}
            placeholder="名称、描述或 ID"
            className="pl-9 pr-11"
          />
          {search && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => onSearchChange('')}
              aria-label="清空搜索"
              title="清空搜索"
              className="absolute right-0 top-1/2 -translate-y-1/2"
            >
              <X aria-hidden="true" />
            </Button>
          )}
        </div>

        <div className="mt-3 grid grid-cols-3 gap-1 rounded-md border border-border bg-muted/35 p-1" aria-label="按状态筛选">
          {STATUS_FILTERS.map(option => (
            <Button
              key={option.id}
              type="button"
              variant={statusFilter === option.id ? 'secondary' : 'ghost'}
              onClick={() => onStatusFilterChange(option.id)}
              aria-pressed={statusFilter === option.id}
              className="h-11 px-2 text-xs"
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {error && (
        <div role="alert" className="m-3 rounded-md border border-destructive/35 bg-destructive/10 p-3">
          <div className="flex items-start gap-2 text-sm leading-6 text-destructive">
            <AlertCircle className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
            <p className="break-words">{error}</p>
          </div>
          <Button type="button" variant="outline" onClick={onRecover} className="mt-3">
            {!isAuthError && <RefreshCw aria-hidden="true" />}
            {isAuthError ? '返回首页登录' : '重新加载'}
          </Button>
        </div>
      )}

      {loading && (
        <div className="space-y-2 p-3" aria-label="正在加载知识库">
          {[0, 1, 2, 3].map(item => <Skeleton key={item} className="h-24" />)}
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
          <Database className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="mt-3 text-sm font-medium text-foreground">
            {bases.length === 0 ? '还没有知识库' : '没有匹配的知识库'}
          </p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {bases.length === 0 ? '创建后即可添加文档与绑定范围' : '尝试调整关键词或状态筛选'}
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={bases.length === 0 ? onCreate : onClearFilters}
            className="mt-4"
          >
            {bases.length === 0 ? <Plus aria-hidden="true" /> : <X aria-hidden="true" />}
            {bases.length === 0 ? '创建知识库' : '清除筛选'}
          </Button>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="max-h-[620px] space-y-1 overflow-y-auto p-2 lg:max-h-[calc(100dvh-310px)]">
          {(search.trim() || statusFilter !== 'all') && (
            <div className="flex min-h-11 items-center justify-between gap-2 px-2 text-[11px] text-muted-foreground">
              <span className="font-archive-mono">显示 {filtered.length} / {bases.length}</span>
              <Button type="button" variant="ghost" size="sm" onClick={onClearFilters}>清除</Button>
            </div>
          )}
          {filtered.map((base, index) => {
            const isSelected = selectedBaseId === base.knowledge_base_id;
            const docCount = getDocumentCount(base);
            const readyCount = Number(base.ready_document_count ?? 0);
            return (
              <FadeContent key={base.knowledge_base_id} delay={Math.min(index, 6) * 0.025}>
                <button
                  type="button"
                  onClick={() => onSelect(base)}
                  aria-current={isSelected ? 'true' : undefined}
                  className={`min-h-[92px] w-full rounded-md border px-3 py-3 text-left transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    isSelected
                      ? 'border-primary/45 bg-primary/10'
                      : 'border-transparent hover:border-border hover:bg-accent'
                  } ${base.is_enabled ? '' : 'opacity-70 hover:opacity-100'}`}
                >
                  <span className="flex min-w-0 items-start gap-3">
                    <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md border ${
                      isSelected
                        ? 'border-primary/30 bg-primary/10 text-primary'
                        : 'border-border bg-muted/45 text-muted-foreground'
                    }`}>
                      <Database className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
                        <span className="min-w-0 break-words font-archive-serif text-sm font-semibold text-foreground">
                          {base.name || base.knowledge_base_id}
                        </span>
                        <span className="shrink-0 text-[11px] font-medium text-muted-foreground">
                          {base.is_enabled ? '● 启用' : '○ 停用'}
                        </span>
                      </span>
                      <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground">
                        {base.description || '暂无描述'}
                      </span>
                      <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-archive-mono text-[10px] tabular-nums text-muted-foreground">
                        <span>{docCount} docs</span>
                        <span>{readyCount} ready</span>
                      </span>
                    </span>
                  </span>
                </button>
              </FadeContent>
            );
          })}
        </div>
      )}
    </>
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
      await dialog.alert({
        title: '删除失败',
        message: err.message || '删除文档失败',
        variant: 'danger',
      });
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
      await dialog.alert({
        title: '重试失败',
        message: err.message || '重试处理失败',
        variant: 'danger',
      });
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
    <section aria-labelledby="base-detail-title" className="min-w-0">
      <div className="flex min-w-0 flex-col gap-4 border-b border-border pb-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border bg-muted/45 text-primary">
            <BookOpen className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="base-detail-title" className="break-words font-archive-serif text-xl font-semibold text-foreground sm:text-2xl">
                {base?.name || '加载中...'}
              </h2>
              {base && (
                <span className="rounded border border-border bg-muted/45 px-2 py-1 text-[11px] font-medium text-foreground">
                  {base.is_enabled ? '● 已启用' : '○ 已停用'}
                </span>
              )}
            </div>
            {base && (
              <p className="mt-1 break-all font-archive-mono text-[10px] text-muted-foreground">
                {base.knowledge_base_id}
              </p>
            )}
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              {base?.description || '暂无描述。可通过编辑补充该知识库的用途和内容范围。'}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 self-end xl:self-auto">
          <Button type="button" variant="outline" onClick={onEdit} disabled={!base || busy}>
            <Edit2 aria-hidden="true" />
            编辑
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={onToggle}
            disabled={!base || busy}
            aria-label={base?.is_enabled ? '停用知识库' : '启用知识库'}
          >
            {busy
              ? <Loader2 className="animate-spin" aria-hidden="true" />
              : base?.is_enabled
                ? <PowerOff aria-hidden="true" />
                : <Power aria-hidden="true" />}
            {base?.is_enabled ? '停用' : '启用'}
          </Button>
          <Button type="button" variant="destructive" onClick={onDelete} disabled={!base || busy}>
            <Trash2 aria-hidden="true" />
            删除
          </Button>
        </div>
      </div>

      {loading && (
        <div className="space-y-4 py-5" aria-label="正在加载知识库详情">
          <Skeleton className="h-20" />
          <Skeleton className="h-14" />
          <Skeleton className="h-52" />
        </div>
      )}

      {!loading && error && (
        <div role="alert" className="my-5 rounded-md border border-destructive/35 bg-destructive/10 p-4">
          <p className="break-words text-sm text-destructive">{error}</p>
          <Button type="button" variant="outline" onClick={onRefresh} className="mt-3">
            <RefreshCw aria-hidden="true" />
            重新加载
          </Button>
        </div>
      )}

      {!loading && !error && base && (
        <div>
          <dl className="grid grid-cols-2 divide-x divide-y divide-border border-b border-border sm:grid-cols-4 sm:divide-y-0">
            {[
              ['文档', getDocumentCount(base)],
              ['已就绪', readyDocumentCount],
              ['绑定范围', bindings.length],
              ['运行状态', base.is_enabled ? '参与检索' : '暂停检索'],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0 px-3 py-4 sm:px-4">
                <dt className="text-[11px] text-muted-foreground">{label}</dt>
                <dd className="mt-1 break-words font-archive-mono text-sm font-semibold tabular-nums text-foreground">
                  {value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="grid grid-cols-2 gap-2 border-b border-border py-5 xl:grid-cols-4">
            <Button type="button" onClick={onShowUploadModal} disabled={busy}>
              <Upload aria-hidden="true" />
              上传文件
            </Button>
            <Button type="button" variant="secondary" onClick={onShowPasteModal} disabled={busy}>
              <PenTool aria-hidden="true" />
              粘贴文本
            </Button>
            <Button type="button" variant="outline" onClick={onShowBindingModal} disabled={busy}>
              <Link2 aria-hidden="true" />
              管理绑定
            </Button>
            <Button type="button" variant="outline" onClick={onShowPreviewModal} disabled={busy}>
              <Eye aria-hidden="true" />
              检索预览
            </Button>
          </div>

          <ArchiveSection icon={Link2} title="生效范围" index="01">
            {bindings.length === 0 ? (
              <div className="flex flex-col items-start justify-between gap-3 border-l-2 border-border py-1 pl-3 sm:flex-row sm:items-center">
                <p className="text-sm leading-6 text-muted-foreground">
                  尚未绑定，该知识库不会进入任何对话上下文。
                </p>
                <Button type="button" variant="ghost" onClick={onShowBindingModal}>去配置</Button>
              </div>
            ) : (
              <dl className="divide-y divide-border border-y border-border">
                {bindings.map((binding, index) => {
                  const targetLabel = binding.target_type === 'global'
                    ? '全局'
                    : binding.target_type === 'character'
                      ? '角色'
                      : '群聊';
                  return (
                    <div
                      key={`${binding.target_type}-${binding.target_id || index}`}
                      className="grid min-w-0 gap-1 py-3 sm:grid-cols-[140px_minmax(0,1fr)] sm:gap-5"
                    >
                      <dt className="text-xs font-medium text-foreground">{targetLabel}</dt>
                      <dd className="break-all font-archive-mono text-xs text-muted-foreground">
                        {binding.target_id || '所有上下文'}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            )}
          </ArchiveSection>

          <ArchiveSection icon={FileText} title="文档文稿" index="02" last>
            {documents.length === 0 ? (
              <div className="flex min-h-48 flex-col items-center justify-center border-y border-dashed border-border px-5 py-10 text-center">
                <FileText className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
                <p className="mt-3 text-sm font-medium text-foreground">暂无文档</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  上传文件或粘贴文本后，可在此查看处理状态。
                </p>
              </div>
            ) : (
              <div className="divide-y divide-border border-y border-border">
                {documents.map(doc => {
                  const statusInfo = DOCUMENT_STATUS_MAP[doc.status] || DOCUMENT_STATUS_MAP.queued;
                  const StatusIcon = statusInfo.Icon;
                  const docBusy = deletingDocId === doc.document_id
                    || retryingDocId === doc.document_id;
                  const statusTone = doc.status === 'failed'
                    ? 'border-destructive/35 bg-destructive/10 text-destructive'
                    : doc.status === 'ready'
                      ? 'border-primary/30 bg-primary/10 text-primary'
                      : 'border-border bg-muted/45 text-muted-foreground';

                  return (
                    <article key={doc.document_id} className="py-4">
                      <div className="flex min-w-0 items-start gap-3">
                        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-md border ${statusTone}`}>
                          <StatusIcon
                            className={`h-4 w-4 ${doc.status === 'processing' ? 'animate-spin' : ''}`}
                            aria-hidden="true"
                          />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                            <div className="min-w-0">
                              <h4 className="break-words font-archive-serif text-base font-semibold text-foreground">
                                {doc.original_name}
                              </h4>
                              <p className="mt-1 break-all font-archive-mono text-[10px] text-muted-foreground">
                                {doc.document_id}
                              </p>
                              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                                <span>{doc.source_type === 'upload' ? '文件上传' : '文本粘贴'}</span>
                                <span className="font-archive-mono tabular-nums">{formatByteSize(doc.byte_size)}</span>
                                <span className="font-medium">{statusInfo.label}</span>
                              </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-1 self-end sm:self-start">
                              {doc.status === 'failed' && (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => handleRetryDocument(doc)}
                                  disabled={docBusy}
                                  aria-label={`重试处理 ${doc.original_name}`}
                                  title="重试处理"
                                >
                                  {retryingDocId === doc.document_id
                                    ? <Loader2 className="animate-spin" aria-hidden="true" />
                                    : <RefreshCw aria-hidden="true" />}
                                </Button>
                              )}
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                onClick={() => handleDeleteDocument(doc)}
                                disabled={docBusy}
                                aria-label={`删除文档 ${doc.original_name}`}
                                title="删除文档"
                                className="hover:text-destructive"
                              >
                                {deletingDocId === doc.document_id
                                  ? <Loader2 className="animate-spin" aria-hidden="true" />
                                  : <Trash2 aria-hidden="true" />}
                              </Button>
                            </div>
                          </div>

                          {doc.error_message && (
                            <p role="alert" className="mt-3 border-l-2 border-destructive/45 py-1 pl-3 text-xs leading-5 text-destructive">
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
          </ArchiveSection>
        </div>
      )}
    </section>
  );
}

function ArchiveSection({ icon: Icon, title, index, children, last = false }) {
  return (
    <section className={`py-5 ${last ? '' : 'border-b border-border'}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <h3 className="font-archive-serif text-lg font-semibold text-foreground">{title}</h3>
        </div>
        <span className="font-archive-mono text-[10px] text-muted-foreground">{index}</span>
      </div>
      {children}
    </section>
  );
}

function ModalFrame({
  show,
  title,
  description,
  onClose,
  children,
  className = 'max-w-lg',
}) {
  return (
    <Dialog open={show} onOpenChange={open => { if (!open) onClose(); }}>
      <DialogContent className={`max-h-[calc(100dvh-2rem)] overflow-y-auto [&_button]:min-h-11 ${className}`}>
        <DialogHeader className="pr-10">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

function ModalError({ message }) {
  if (!message) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2.5 text-xs leading-5 text-destructive">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="break-words">{message}</span>
    </div>
  );
}

function CreateBaseModal({ show, onClose, onSuccess }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (show) {
      setName('');
      setDescription('');
      setError('');
    }
  }, [show]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!name.trim()) {
      setError('请输入知识库名称');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      const newBase = await knowledgeApi.createBase({
        name: name.trim(),
        description: description.trim() || null,
      });
      onSuccess(newBase);
    } catch (err) {
      setError(err.message || '创建失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalFrame
      show={show}
      title="创建知识库"
      description="新建一个独立的知识档案集合。"
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <ModalError message={error} />
        <div>
          <label htmlFor="create-base-name" className="mb-2 block text-xs font-medium text-foreground">
            名称 *
          </label>
          <Input
            id="create-base-name"
            value={name}
            onChange={event => setName(event.target.value)}
            maxLength={120}
            placeholder="例如：游戏世界观设定"
            autoFocus
          />
        </div>
        <div>
          <label htmlFor="create-base-description" className="mb-2 block text-xs font-medium text-foreground">
            描述
          </label>
          <Textarea
            id="create-base-description"
            value={description}
            onChange={event => setDescription(event.target.value)}
            maxLength={2000}
            rows={3}
            placeholder="可选：简要描述该知识库的用途"
          />
        </div>
        <DialogFooter className="border-t border-border pt-4">
          <Button type="button" variant="outline" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={submitting}>
            {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
            {submitting ? '创建中...' : '创建'}
          </Button>
        </DialogFooter>
      </form>
    </ModalFrame>
  );
}

function EditBaseModal({ show, base, onClose, onSuccess }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (show && base) {
      setName(base.name || '');
      setDescription(base.description || '');
      setError('');
    }
  }, [show, base]);

  async function handleSubmit(event) {
    event.preventDefault();
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

  return (
    <ModalFrame
      show={show && !!base}
      title="编辑知识库"
      description="修改档案名称与用途说明。"
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <ModalError message={error} />
        <div>
          <label htmlFor="edit-base-name" className="mb-2 block text-xs font-medium text-foreground">
            名称 *
          </label>
          <Input
            id="edit-base-name"
            value={name}
            onChange={event => setName(event.target.value)}
            maxLength={120}
            autoFocus
          />
        </div>
        <div>
          <label htmlFor="edit-base-description" className="mb-2 block text-xs font-medium text-foreground">
            描述
          </label>
          <Textarea
            id="edit-base-description"
            value={description}
            onChange={event => setDescription(event.target.value)}
            maxLength={2000}
            rows={3}
          />
        </div>
        <DialogFooter className="border-t border-border pt-4">
          <Button type="button" variant="outline" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={submitting}>
            {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
            {submitting ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </form>
    </ModalFrame>
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
    setCharacterIds(
      bindings
        .filter(binding => binding.target_type === 'character')
        .map(binding => binding.target_id)
    );
    setGroupIds(
      bindings
        .filter(binding => binding.target_type === 'group_thread')
        .map(binding => binding.target_id)
    );
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
      className="max-w-2xl"
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        <ModalError message={error} />
        {loading ? (
          <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            加载绑定目标...
          </div>
        ) : (
          <>
            <label className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-border bg-muted/35 px-3 py-2.5">
              <input
                type="checkbox"
                checked={globalEnabled}
                onChange={event => setGlobalEnabled(event.target.checked)}
                className="h-5 w-5 shrink-0 accent-primary"
              />
              <span>
                <span className="block text-sm font-medium text-foreground">全局生效</span>
                <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                  所有单聊和群聊上下文均可使用
                </span>
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
          </>
        )}

        <DialogFooter className="border-t border-border pt-4">
          <Button type="button" variant="outline" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={loading || submitting}>
            {submitting
              ? <Loader2 className="animate-spin" aria-hidden="true" />
              : <Link2 aria-hidden="true" />}
            {submitting ? '保存中...' : '保存绑定'}
          </Button>
        </DialogFooter>
      </form>
    </ModalFrame>
  );
}

function BindingTargetList({ title, emptyText, items, idKey, selectedIds, onToggle }) {
  return (
    <fieldset>
      <legend className="mb-2 font-archive-serif text-base font-semibold text-foreground">
        {title}
      </legend>
      {items.length === 0 ? (
        <p className="border-y border-border px-3 py-4 text-xs text-muted-foreground">{emptyText}</p>
      ) : (
        <div className="grid max-h-48 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
          {items.map(item => {
            const id = item[idKey];
            return (
              <label
                key={id}
                className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-border px-3 py-2 transition-colors hover:bg-accent"
              >
                <input
                  type="checkbox"
                  checked={selectedIds.includes(id)}
                  onChange={() => onToggle(id)}
                  className="h-5 w-5 shrink-0 accent-primary"
                />
                <span className="min-w-0">
                  <span className="block break-words text-sm text-foreground">{item.name || id}</span>
                  <span className="mt-0.5 block break-all font-archive-mono text-[10px] text-muted-foreground">
                    {id}
                  </span>
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
    <ModalFrame
      show={show && !!base}
      title="上传文档"
      description={`添加文件到「${base?.name || ''}」`}
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="space-y-5">
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
          className="flex min-h-48 w-full flex-col items-center justify-center rounded-md border border-dashed border-border bg-muted/25 px-5 text-center transition-colors hover:border-primary/45 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <FileUp className="h-8 w-8 text-primary" aria-hidden="true" />
          <span className="mt-3 max-w-full break-all text-sm font-medium text-foreground">
            {file ? file.name : '选择文件'}
          </span>
          <span className="mt-2 text-xs leading-5 text-muted-foreground">
            TXT、MD、PDF、DOCX，服务器默认上限 10 MB
          </span>
          {file && (
            <span className="mt-1 font-archive-mono text-[10px] tabular-nums text-muted-foreground">
              {(file.size / 1024 / 1024).toFixed(2)} MB
            </span>
          )}
        </button>
        <DialogFooter className="border-t border-border pt-4">
          <Button type="button" variant="outline" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={submitting || !file}>
            {submitting
              ? <Loader2 className="animate-spin" aria-hidden="true" />
              : <Upload aria-hidden="true" />}
            {submitting ? '上传中...' : '上传并处理'}
          </Button>
        </DialogFooter>
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
      await knowledgeApi.pasteDocument(base.knowledge_base_id, {
        title: title.trim(),
        text: text.trim(),
      });
      await onSuccess();
    } catch (err) {
      setError(err.message || '添加文本失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalFrame
      show={show && !!base}
      title="粘贴文本"
      description={`直接添加纯文本到「${base?.name || ''}」`}
      onClose={onClose}
      className="max-w-2xl"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <ModalError message={error} />
        <div>
          <label htmlFor="paste-document-title" className="mb-2 block text-xs font-medium text-foreground">
            文档标题
          </label>
          <Input
            id="paste-document-title"
            value={title}
            onChange={event => setTitle(event.target.value)}
            maxLength={180}
            autoFocus
            placeholder="例如：北区交通规则"
          />
        </div>
        <div>
          <label htmlFor="paste-document-text" className="mb-2 block text-xs font-medium text-foreground">
            文档内容
          </label>
          <Textarea
            id="paste-document-text"
            value={text}
            onChange={event => setText(event.target.value)}
            rows={11}
            placeholder="粘贴需要索引的知识内容..."
          />
          <div className="mt-2 text-right font-archive-mono text-[10px] tabular-nums text-muted-foreground">
            {text.length.toLocaleString()} 字符
          </div>
        </div>
        <DialogFooter className="border-t border-border pt-4">
          <Button type="button" variant="outline" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={submitting}>
            {submitting
              ? <Loader2 className="animate-spin" aria-hidden="true" />
              : <PenTool aria-hidden="true" />}
            {submitting ? '提交中...' : '添加并处理'}
          </Button>
        </DialogFooter>
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
    <ModalFrame
      show={show && !!base}
      title="检索预览"
      description={`仅检索「${base?.name || ''}」中当前上下文可访问的已就绪内容。`}
      onClose={onClose}
      className="max-w-3xl"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <ModalError message={error} />
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-2 block text-xs font-medium text-foreground">角色上下文</label>
            <Select
              value={characterId || '__none__'}
              onValueChange={value => setCharacterId(value === '__none__' ? '' : value)}
              disabled={targetsLoading}
            >
              <SelectTrigger aria-label="角色上下文">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">不指定角色</SelectItem>
                {targets.characters.map(item => (
                  <SelectItem key={item.character_id} value={item.character_id}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-2 block text-xs font-medium text-foreground">群聊上下文</label>
            <Select
              value={groupThreadId || '__none__'}
              onValueChange={value => setGroupThreadId(value === '__none__' ? '' : value)}
              disabled={targetsLoading}
            >
              <SelectTrigger aria-label="群聊上下文">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">不指定群聊</SelectItem>
                {targets.group_threads.map(item => (
                  <SelectItem key={item.group_thread_id} value={item.group_thread_id}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div>
          <label htmlFor="knowledge-preview-query" className="mb-2 block text-xs font-medium text-foreground">
            检索内容
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              id="knowledge-preview-query"
              value={query}
              onChange={event => setQuery(event.target.value)}
              maxLength={4000}
              autoFocus
              placeholder="输入一个问题或事实关键词"
              className="min-w-0 flex-1"
            />
            <Button type="submit" disabled={loading} className="shrink-0">
              {loading
                ? <Loader2 className="animate-spin" aria-hidden="true" />
                : <Search aria-hidden="true" />}
              {loading ? '检索中...' : '检索'}
            </Button>
          </div>
        </div>
      </form>

      {result && (
        <section className="border-t border-border pt-4" aria-live="polite">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-archive-serif text-base font-semibold text-foreground">命中结果</h3>
            <span className="font-archive-mono text-[10px] tabular-nums text-muted-foreground">
              {(result.sources || []).length} 条
            </span>
          </div>
          {(result.sources || []).length === 0 ? (
            <div className="mt-3 border-y border-dashed border-border px-4 py-8 text-center text-xs leading-5 text-muted-foreground">
              当前绑定上下文中没有达到相似度阈值的已就绪内容。
            </div>
          ) : (
            <div className="mt-3 divide-y divide-border border-y border-border">
              {result.sources.map(source => {
                const match = getKnowledgeSourceMatch(source);
                return (
                  <article key={source.chunk_id} className="py-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="break-words font-archive-serif text-sm font-semibold text-foreground">
                          {source.document_name}
                        </p>
                        <p className="mt-0.5 break-words text-xs text-muted-foreground">
                          {source.knowledge_base_name}
                        </p>
                      </div>
                      <span
                        className="rounded border border-border bg-muted/45 px-2 py-1 font-archive-mono text-[10px] font-medium tabular-nums text-foreground"
                        aria-label={match.description}
                        title={match.description}
                      >
                        {match.label} {match.percent}%
                      </span>
                    </div>
                    <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">
                      {source.excerpt}
                    </p>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      )}
    </ModalFrame>
  );
}

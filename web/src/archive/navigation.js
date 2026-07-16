export const ARCHIVE_NAV_ITEMS = Object.freeze([
  { label: '对话', path: '/chat', icon: 'messages' },
  { label: '事件', path: '/events', icon: 'calendar' },
  { label: '角色', path: '/persona', icon: 'contact' },
  { label: '图谱', path: '/graph', icon: 'network' },
  { label: '知识', path: '/knowledge', icon: 'book' },
]);

const ROUTE_META = Object.freeze({
  '/chat': {
    title: '对话',
    description: '叙事会话与角色互动',
  },
  '/events': {
    title: '事件',
    description: '事件编排与执行记录',
  },
  '/persona': {
    title: '角色',
    description: '扮演身份与人物档案',
  },
  '/graph': {
    title: '关系图谱',
    description: '人物与线索关系网络',
  },
  '/knowledge': {
    title: '知识',
    description: '资料库与叙事知识管理',
  },
  '/editor': {
    title: '角色编辑',
    description: '角色设定与行为档案',
  },
});

function normalizePathname(pathname) {
  const cleanPath = String(pathname || '/')
    .split(/[?#]/, 1)[0]
    .replace(/\/+$/, '');
  return cleanPath || '/';
}

export function getArchiveRouteMeta(pathname) {
  const path = normalizePathname(pathname);
  if (ROUTE_META[path]) return ROUTE_META[path];
  if (path.startsWith('/events/')) {
    return {
      title: '事件详情',
      description: '事件条件、动作与执行配置',
    };
  }
  if (path.startsWith('/editor/')) return ROUTE_META['/editor'];
  return {
    title: '档案馆',
    description: 'Memoria 叙事档案系统',
  };
}

export function getActiveArchiveNavPath(pathname) {
  const path = normalizePathname(pathname);
  if (path === '/editor' || path.startsWith('/editor/')) return '/persona';
  const item = ARCHIVE_NAV_ITEMS.find(({ path: itemPath }) => (
    path === itemPath || path.startsWith(`${itemPath}/`)
  ));
  return item?.path || null;
}

export function shouldFocusArchiveMain(previousPathname, nextPathname) {
  if (previousPathname == null) return false;
  return normalizePathname(previousPathname) !== normalizePathname(nextPathname);
}

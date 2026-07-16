import {
  createContext,
  lazy,
  Suspense,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Archive,
  BookOpen,
  CalendarDays,
  Contact,
  Home,
  LogIn,
  LogOut,
  Menu,
  MessagesSquare,
  Moon,
  Network,
  Settings,
  Sun,
  UserRound,
} from 'lucide-react';
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from 'react-router-dom';

import { WorldClockDisplay } from '@/components/WorldClock';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { useUser } from '@/context/UserContext';
import { cn } from '@/lib/utils';

import {
  ARCHIVE_NAV_ITEMS,
  getActiveArchiveNavPath,
  getArchiveRouteMeta,
  shouldFocusArchiveMain,
} from './navigation';
import { useArchiveTheme } from './ArchiveThemeProvider';

const UserSettingsModal = lazy(() => import('@/components/UserSettingsModal'));
const ArchiveShellContext = createContext(null);

const NAV_ICONS = {
  messages: MessagesSquare,
  calendar: CalendarDays,
  contact: Contact,
  network: Network,
  book: BookOpen,
};

function ArchiveNavLink({ item, activePath, mobile = false, onNavigate }) {
  const Icon = NAV_ICONS[item.icon] || Archive;
  const active = activePath === item.path;
  return (
    <NavLink
      to={item.path}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'archive-nav-link group flex items-center gap-2 rounded-md text-sm font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        mobile ? 'min-h-12 px-3' : 'min-h-11 px-3',
        active
          ? 'bg-primary/12 text-primary'
          : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
      )}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{item.label}</span>
      {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />}
    </NavLink>
  );
}

function ThemeToggle({ compact = false }) {
  const { theme, toggleTheme } = useArchiveTheme();
  const isDark = theme === 'dark';
  const label = isDark ? '切换到浅色主题' : '切换到暗色主题';
  const Icon = isDark ? Sun : Moon;
  const button = (
    <Button
      type="button"
      variant="ghost"
      size={compact ? 'icon' : 'default'}
      onClick={toggleTheme}
      aria-label={label}
      className={cn(!compact && 'justify-start')}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      {!compact && <span>{isDark ? '浅色主题' : '暗色主题'}</span>}
    </Button>
  );

  if (!compact) return button;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function UserMenu({ onOpenSettings }) {
  const { user, logout } = useUser();
  const navigate = useNavigate();
  const displayName = user?.role_summary?.display_name || user?.username || '未登录';
  const avatarUrl = user?.role_summary?.avatar_url || user?.avatar_url;

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`打开用户菜单，当前用户：${displayName}`}
            >
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt=""
                  className="h-7 w-7 rounded-full border border-border object-cover"
                />
              ) : (
                <UserRound className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>用户菜单</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <span className="block truncate text-foreground">{displayName}</span>
          <span className="mt-0.5 block font-archive-mono text-[10px] font-normal text-muted-foreground">
            {user?.user_id || '尚未登录'}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {user ? (
          <>
            <DropdownMenuItem onSelect={onOpenSettings}>
              <Settings />
              用户设置
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => navigate('/persona')}>
              <Contact />
              角色资料
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={handleLogout}
              className="text-destructive focus:text-destructive"
            >
              <LogOut />
              退出登录
            </DropdownMenuItem>
          </>
        ) : (
          <DropdownMenuItem onSelect={() => navigate('/')}>
            <LogIn />
            返回首页登录
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MobileNavigation({
  activePath,
  meta,
  open,
  onOpenChange,
  onOpenSettings,
}) {
  const { user, logout } = useUser();
  const navigate = useNavigate();

  const handleLogout = () => {
    onOpenChange(false);
    logout();
    navigate('/');
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="打开主导航">
          <Menu className="h-5 w-5" aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="flex flex-col overflow-y-auto pt-16">
        <SheetHeader>
          <SheetTitle>Memoria 档案馆</SheetTitle>
          <SheetDescription>{meta.title} · {meta.description}</SheetDescription>
        </SheetHeader>

        <nav className="mt-5 grid gap-1" aria-label="移动端主导航">
          {ARCHIVE_NAV_ITEMS.map(item => (
            <ArchiveNavLink
              key={item.path}
              item={item}
              activePath={activePath}
              mobile
              onNavigate={() => onOpenChange(false)}
            />
          ))}
        </nav>

        <div className="mt-6 border-t border-border pt-4">
          <ThemeToggle />
          {user && (
            <Button
              type="button"
              variant="ghost"
              className="w-full justify-start"
              onClick={() => {
                onOpenChange(false);
                onOpenSettings();
              }}
            >
              <Settings />
              用户设置
            </Button>
          )}
          <Button variant="ghost" className="w-full justify-start" asChild>
            <Link to="/" onClick={() => onOpenChange(false)}>
              <Home />
              返回首页
            </Link>
          </Button>
          {user && (
            <Button
              type="button"
              variant="ghost"
              className="w-full justify-start text-destructive hover:text-destructive"
              onClick={handleLogout}
            >
              <LogOut />
              退出登录
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function ArchiveShell() {
  const location = useLocation();
  const { user } = useUser();
  const { theme } = useArchiveTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [primaryAction, setPrimaryAction] = useState(null);
  const initialTitleRef = useRef(document.title);
  const mainRef = useRef(null);
  const previousPathnameRef = useRef(null);
  const meta = getArchiveRouteMeta(location.pathname);
  const activePath = getActiveArchiveNavPath(location.pathname);

  useEffect(() => {
    document.title = `${meta.title} | Memoria`;
  }, [meta.title]);

  useEffect(() => () => {
    document.title = initialTitleRef.current;
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const previousPathname = previousPathnameRef.current;
    previousPathnameRef.current = location.pathname;
    if (!shouldFocusArchiveMain(previousPathname, location.pathname)) {
      return undefined;
    }

    const frameId = window.requestAnimationFrame(() => {
      const main = mainRef.current;
      if (!main) return;
      try {
        main.focus({ preventScroll: true });
      } catch {
        main.focus();
      }
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [location.pathname]);

  const openSettings = useCallback(() => {
    if (user) setSettingsOpen(true);
  }, [user]);

  const shellValue = useMemo(() => ({
    primaryAction,
    setPrimaryAction,
  }), [primaryAction]);

  return (
    <ArchiveShellContext.Provider value={shellValue}>
      <TooltipProvider>
        <div className={`archive-scope archive-theme-${theme} archive-shell min-h-dvh`}>
          <a href="#archive-main" className="archive-skip-link">
            跳到主要内容
          </a>
          <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
            <span key={location.pathname}>{meta.title}页面已加载</span>
          </div>

          <header className="archive-topbar sticky top-0 z-[900] border-b border-border">
            <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-2 px-3 sm:px-5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" asChild>
                    <Link to="/" aria-label="返回首页">
                      <img
                        src="/memoria-icon.svg"
                        alt=""
                        aria-hidden="true"
                        className="h-8 w-8"
                      />
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>返回首页</TooltipContent>
              </Tooltip>

              <div className="hidden min-w-0 sm:block">
                <div className="font-archive-serif text-sm font-semibold text-foreground">
                  Memoria
                </div>
                <div className="truncate font-archive-mono text-[9px] uppercase text-muted-foreground">
                  Narrative Archive
                </div>
              </div>

              <div className="mx-1 hidden h-7 w-px bg-border sm:block" aria-hidden="true" />

              <div className="min-w-0 flex-1 lg:hidden">
                <div className="truncate font-archive-serif text-sm font-semibold text-foreground">
                  {meta.title}
                </div>
                <div className="truncate text-[10px] text-muted-foreground">
                  {meta.description}
                </div>
              </div>

              <nav className="hidden min-w-0 flex-1 items-center gap-1 lg:flex" aria-label="主导航">
                {ARCHIVE_NAV_ITEMS.map(item => (
                  <ArchiveNavLink key={item.path} item={item} activePath={activePath} />
                ))}
              </nav>

              <div className="ml-auto flex shrink-0 items-center gap-1">
                {primaryAction && (
                  <div className="hidden items-center lg:flex" data-archive-primary-action>
                    {primaryAction}
                  </div>
                )}
                <div className="archive-world-clock hidden xl:block">
                  <WorldClockDisplay onClick={user ? openSettings : undefined} />
                </div>
                <div className="hidden lg:block">
                  <ThemeToggle compact />
                </div>
                <div className="hidden lg:block">
                  <UserMenu onOpenSettings={openSettings} />
                </div>
                <div className="lg:hidden">
                  <MobileNavigation
                    activePath={activePath}
                    meta={meta}
                    open={mobileOpen}
                    onOpenChange={setMobileOpen}
                    onOpenSettings={openSettings}
                  />
                </div>
              </div>
            </div>
          </header>

          <main
            ref={mainRef}
            id="archive-main"
            tabIndex={-1}
            aria-label={`${meta.title}主内容`}
            className="archive-content min-w-0 focus:outline-none"
          >
            <Outlet />
          </main>

          <Toaster position="top-right" richColors closeButton />
          {settingsOpen && (
            <Suspense fallback={null}>
              <UserSettingsModal onClose={() => setSettingsOpen(false)} />
            </Suspense>
          )}
        </div>
      </TooltipProvider>
    </ArchiveShellContext.Provider>
  );
}

export function useArchiveShell() {
  const context = useContext(ArchiveShellContext);
  if (!context) throw new Error('useArchiveShell must be used within ArchiveShell');
  return context;
}

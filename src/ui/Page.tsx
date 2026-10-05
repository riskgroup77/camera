import { useContext, useEffect, useMemo, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';
import { branding } from '../lib/branding';
import { cn, focusRing } from './cn';
import { ShellContext, type Crumb } from './pageContext';
import { Tabs } from './Tabs';
import { useUrlTab, type TabItem } from './urlTab';

export interface PageProps<T extends string = string> {
  title: string;
  subtitle?: ReactNode;
  /** Yuqori paneldagi non-yo'l. Oxirgi element — joriy sahifa (odatda title). */
  breadcrumbs?: Crumb[];
  /** Sarlavha yonidagi belgi/yorliq (masalan holat badge). */
  titleAddon?: ReactNode;
  /** Sahifa harakatlari — DOIM o'ng yuqorida. */
  actions?: ReactNode;
  /** Sarlavha ostidagi tablar; tanlov URL'da `?tab=` (useUrlTab bilan o'qing). */
  tabs?: readonly TabItem<T>[];
  defaultTab?: T;
  tabParam?: string;
  /** Tablar/sarlavha ostidagi filtrlar (Toolbar). */
  toolbar?: ReactNode;
  /** Hujjat/bo'lim kodi — o'ng yuqorida, monoshriftda ("HISOBOT-07"). */
  code?: ReactNode;
  /** Vaqt tamg'asi — kod ostida ("Tuzildi: 21.09.2026 09:14"). */
  stamp?: ReactNode;
  children?: ReactNode;
  className?: string;
}

/** Barcha sahifalar uchun yagona shablon: sarlavha + izoh chapda,
 *  harakatlar o'ngda, ostida tablar, keyin filtrlar va kontent.
 *  Non-yo'l yuqori panelga uzatiladi (AppShell). */
export function Page<T extends string = string>({
  title,
  subtitle,
  breadcrumbs,
  titleAddon,
  actions,
  tabs,
  defaultTab,
  tabParam = 'tab',
  toolbar,
  code,
  stamp,
  children,
  className,
}: PageProps<T>) {
  const { setPageMeta, inShell } = useContext(ShellContext);
  const crumbsKey = JSON.stringify(breadcrumbs ?? null);
  // Kalit bo'yicha: har renderda yangi massiv berilsa ham effekt qayta ishlamaydi.
  const crumbs = useMemo(() => (JSON.parse(crumbsKey) as Crumb[] | null) ?? undefined, [crumbsKey]);

  useEffect(() => {
    setPageMeta({ title, crumbs });
    const previous = document.title;
    document.title = `${title} · ${branding.systemName}`;
    return () => {
      setPageMeta(null);
      document.title = previous;
    };
  }, [title, crumbs, setPageMeta]);

  // Telefonda yuqori paneldagi non-yo'l yashiriladi — o'rniga "orqaga" havolasi.
  const parent = breadcrumbs ? [...breadcrumbs].reverse().find((crumb, index) => index > 0 && crumb.to) : undefined;

  return (
    <div className={cn('flex min-w-0 flex-col', className)}>
      {parent?.to && (
        <Link
          to={parent.to}
          className={cn('intel-micro mb-2 inline-flex w-fit items-center gap-1 rounded-control hover:!text-fg', inShell && 'md:hidden', focusRing)}
        >
          <ChevronLeft size={13} aria-hidden="true" />
          {parent.label}
        </Link>
      )}
      <header className="relative flex flex-wrap items-start justify-between gap-x-4 gap-y-3 overflow-hidden rounded-card border border-white/90 bg-surface/80 px-4 py-4 shadow-card sm:px-5">
        <span className="pointer-events-none absolute -right-10 -top-14 h-40 w-40 rounded-full bg-primary/10 blur-3xl" aria-hidden="true" />
        <div className="min-w-0 flex-1 basis-64">
          <span className="text-[11px] font-semibold text-primary">{branding.systemName}</span>
          <div className="mt-0.5 flex flex-wrap items-center gap-2">
            <h1 className="truncate text-[24px] font-bold leading-7 tracking-[-0.035em] text-fg sm:text-[28px]">{title}</h1>
            {titleAddon}
          </div>
          {subtitle && <p className="mt-1 text-[13px] leading-5 text-muted">{subtitle}</p>}
        </div>
        {(code || stamp) && (
          <div className="flex shrink-0 flex-col items-end gap-0.5 text-right">
            {code && <span className="rounded-full bg-primary-soft px-2.5 py-1 text-[11px] font-semibold text-primary">{code}</span>}
            {stamp && <span className="text-[11px] font-medium text-muted">{stamp}</span>}
          </div>
        )}
        {actions && <div className="flex flex-wrap items-center justify-end gap-1.5">{actions}</div>}
      </header>

      {tabs && tabs.length > 0 && <PageTabs tabs={tabs} defaultTab={defaultTab} param={tabParam} />}

      {toolbar && <div className={cn(tabs && tabs.length > 0 ? 'mt-0' : 'mt-3')}>{toolbar}</div>}

      <div className={cn('flex min-w-0 flex-col gap-4', toolbar ? 'mt-4' : 'mt-4')}>{children}</div>
    </div>
  );
}

function PageTabs<T extends string>({ tabs, defaultTab, param }: { tabs: readonly TabItem<T>[]; defaultTab?: T; param: string }) {
  const [active, setActive] = useUrlTab(tabs, { defaultTab, param });
  return <Tabs tabs={tabs} value={active} onChange={setActive} className="mt-3" />;
}

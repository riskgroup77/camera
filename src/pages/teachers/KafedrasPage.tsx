import { useSearchParams } from 'react-router-dom';
import { AlertTriangle, BarChart3, Building2, Trophy } from 'lucide-react';
import { Page, formatUzDate, relativeDayLabel, useUrlTab, type TabItem } from '../../ui';
import { AnalyticsTab } from '../../components/teachers/AnalyticsTab';
import { ChronicTab } from '../../components/teachers/ChronicTab';
import { RankingTab } from '../../components/teachers/RankingTab';
import { UnitsTab } from '../../components/teachers/UnitsTab';
import ReportGate from '../../components/hisobot/ReportGate';
import { useLoader } from '../../components/teachers/useLoader';
import { getKafedras } from '../../lib/situationApi';
import { useViewDate } from '../../lib/viewDate';

type TabId = 'bolinmalar' | 'tahlil' | 'reyting' | 'surunkali';

const TAB_IDS: readonly TabId[] = ['bolinmalar', 'tahlil', 'reyting', 'surunkali'];
const REFRESH_MS = 60_000;

/** Xodimlar va o'qituvchilar: bo'linmalar, tahlil, reyting, takror
 *  kechikkanlar va kun kuzatuvi. Kameralar tashxisi bu yerda emas —
 *  u kameralar sozlamalarida (u xodimlar haqida emas, kameralar haqida). */
export default function KafedrasPage() {
  const { date, isToday, today, withDate } = useViewDate();
  // Ro'yxat faqat "Bo'linmalar" tabida ko'rinadi (boshqa tablarda u
  // shunchaki tab hisoblagichi uchun kerak). Ilgari har 60 soniyada
  // "Reyting" yoki "Tahlil" ochiq turganda ham qayta so'ralardi.
  // Tab ro'yxati o'zgarmas, shuning uchun faol tabni `tabs` tuzilishidan
  // oldin ham aniq bilish mumkin (noma'lum qiymat standartga tushadi).
  const [searchParams] = useSearchParams();
  const rawTab = searchParams.get('tab');
  const onUnitsTab = !rawTab || !TAB_IDS.includes(rawTab as TabId) || rawTab === 'bolinmalar';
  const units = useLoader(`k:${date}`, (signal) => getKafedras(date, { signal }), {
    refreshMs: isToday && onUnitsTab ? REFRESH_MS : undefined,
  });

  const tabs: TabItem<TabId>[] = [
    { id: 'bolinmalar', label: "Bo'linmalar", icon: Building2, count: units.data?.length ?? null },
    { id: 'tahlil', label: 'Davr tahlili', icon: BarChart3 },
    { id: 'reyting', label: 'Reyting', icon: Trophy },
    { id: 'surunkali', label: 'Takror kechikkanlar', icon: AlertTriangle },
  ];
  const [tab] = useUrlTab(tabs, { defaultTab: 'bolinmalar' });
  const dayLabel = relativeDayLabel(date, today) ?? formatUzDate(date, { weekday: true });
  const periodTab = tab === 'tahlil' || tab === 'reyting' || tab === 'surunkali';

  return (
    <Page
      title="Xodimlar va o'qituvchilar"
      subtitle={
        periodTab ? 'Tanlangan davr' : dayLabel
      }
      breadcrumbs={[{ label: "Xodimlar va o'qituvchilar" }]}
      tabs={tabs}
      defaultTab="bolinmalar"
    >
      {tab === 'bolinmalar' && <UnitsTab loader={units} date={date} isToday={isToday} withDate={withDate} />}
      {/* Davr tahlili va reyting — hisobot: Hisobotlar bilan bir xil parol. */}
      {tab === 'tahlil' && (
        <ReportGate>
          <AnalyticsTab />
        </ReportGate>
      )}
      {tab === 'reyting' && (
        <ReportGate>
          <RankingTab />
        </ReportGate>
      )}
      {tab === 'surunkali' && <ChronicTab />}
    </Page>
  );
}

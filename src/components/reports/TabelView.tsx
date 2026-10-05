import { useMemo } from 'react';
import { CalendarOff, Info, TriangleAlert, UsersRound } from 'lucide-react';
import {
  CodeText,
  DocumentFooter,
  DocumentHeader,
  EmptyState,
  IntelPanel,
  MicroLabel,
  StatusLamp,
  cn,
  type IntelStatus,
} from '../../ui';
import { branding } from '../../lib/branding';
import { buildReference } from '../../lib/hisobotApi';
import { formatUzMonth } from '../../lib/uzDate';
import {
  TABEL_MARKS,
  TABEL_MARK_CLASS,
  grandTotals,
  normalizeMark,
  type TabelLegendItem,
  type TabelReport,
} from '../../lib/tabelApi';
import TabelSheet from './TabelSheet';

interface TabelViewProps {
  data: TabelReport;
  /** 'talabalar' — guruh ustuni, 'xodimlar' — bo'linma. */
  section: 'talabalar' | 'xodimlar';
  /** Hujjat raqami (sahifa holatidan tuziladi). Berilmasa — varaqning
   *  o'z ma'lumotidan tuziladi, shunda jadval yolg'iz ham to'liq hujjat. */
  reference?: string;
}

/** Server `legend` bermasa ham qog'oz o'z belgilarini tushuntirsin. */
const FALLBACK_LEGEND: TabelLegendItem[] = (Object.keys(TABEL_MARKS) as (keyof typeof TABEL_MARKS)[]).map((mark) => ({
  mark,
  label: TABEL_MARKS[mark].label,
}));

/** "Tuzildi:" tamg'asi — qaysi daqiqadagi ma'lumot bosilganini aytadi. */
function stamp(): string {
  try {
    return new Intl.DateTimeFormat('ru-RU', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: 'Asia/Tashkent',
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 16).replace('T', ' ');
  }
}

/**
 * Oylik tabel — buyurtmachi imzolaydigan hujjat.
 *
 * Varaq rasmiy blank kabi ochiladi: tepada tashkilot, hujjat nomi,
 * o'ng tomonda ro'yxat raqami va tuzilgan vaqti, ostida qamrov satri —
 * qog'ozga tushganda ham, ekranda ham varaq o'zi nima ekanini aytib
 * tursin. Pastda esa doim shartli belgilar kaliti: chop etilgan varaqni
 * tushuntiradigan boshqa hech narsa bo'lmaydi.
 */
export default function TabelView({ data, section, reference }: TabelViewProps) {
  const groupLabel = section === 'talabalar' ? 'Guruh' : "Bo'linma";
  const peopleWord = section === 'talabalar' ? 'talaba' : 'xodim';
  const legend = data.legend?.length ? data.legend : FALLBACK_LEGEND;
  const monthText = data.monthLabel || formatUzMonth(data.month);
  const generatedAt = useMemo(stamp, [data]);
  // Sahifa hujjat raqamini bermasa, varaqning o'zi tuzadi: jadval
  // ekranning qayerida turishidan qat'i nazar, kodsiz chiqmasin.
  const docRef =
    reference ?? buildReference({ view: 'tabel', section, period: data.month, parts: [data.scope] });
  // Yakunlar jadvaldagi belgilardan sanaladi (tabelApi.grandTotals) —
  // ekrandagi "N talaba, M tasining yuzi yo'q" satri va jadvalning
  // pastidagi "Jami" satri bitta manbadan chiqsin. Ilgari bu yerda
  // server `totals`i turardi va jadval bilan farq qilishi mumkin edi.
  const total = grandTotals(data);

  // Oy tanlangan, odamlar bor, lekin birorta ham qayd yo'q: bo'sh
  // jadvalni jim ko'rsatish o'rniga sababini aytamiz.
  const marked = total.present + total.late + total.absent;

  if (!data.days?.length) {
    return (
      <EmptyState
        icon={CalendarOff}
        title="Bu oy uchun tabel tuzilmagan"
        description={`${monthText} uchun ish kunlari aniqlanmadi. Boshqa oyni tanlang yoki ish taqvimi sozlanganini tekshiring.`}
      />
    );
  }

  if (!data.people?.length) {
    return (
      <EmptyState
        icon={UsersRound}
        title="Bu tanlovda odam yo'q"
        description="Filtrlarni kengaytiring — fakultet, kurs yoki guruh tanlovini bo'shating, qidiruv matnini olib tashlang."
      />
    );
  }

  const status: { tone: IntelStatus; label: string } =
    marked === 0
      ? { tone: 'alert', label: "Qayd yo'q" }
      : total.notEnrolled > 0
        // "Yuzsiz" — noto'g'ri ibora: odamning yuzi bor, tizimda yo'q.
        ? { tone: 'warn', label: `${total.notEnrolled} ta yuzi yo'q` }
        : { tone: 'ok', label: 'To’liq' };

  return (
    <div className="tabel-print flex min-w-0 flex-col gap-3">
      {/* Qog'ozdagi sarlavha — ekranda ko'rinmaydi. Hujjat raqami
          qog'ozda ham bosiladi: varaqni ekrandagi ko'rinish bilan
          solishtirish uchun yagona bog'lovchi. */}
      <header className="print-only tabel-print-head">
        <p className="tabel-print-org">{branding.orgFullName}</p>
        <p className="tabel-print-title">Davomat tabeli</p>
        <p className="tabel-print-scope">
          {data.scope} · {monthText}
        </p>
        <p className="tabel-print-ref intel-code">
          {docRef} · Tuzildi: {generatedAt}
        </p>
      </header>

      {/* Ekrandagi hujjat blanki. */}
      <DocumentHeader
        className="print-hide"
        org={branding.orgFullName}
        title="Davomat tabeli"
        reference={docRef}
        generatedAt={generatedAt}
        readouts={[
          { label: 'Qamrov', value: data.scope, title: data.scope },
          { label: 'Oy', value: monthText },
          {
            label: 'Odamlar soni',
            value: `${(total.people || data.people.length).toLocaleString('ru-RU')} ${peopleWord}`,
          },
          { label: 'Holat', value: <StatusLamp status={status.tone} label={status.label} /> },
        ]}
      />

      {data.note && (
        <p className="tabel-note flex items-start gap-2 border border-border bg-surface-2 px-3 py-2 text-[13px] text-muted">
          <Info size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{data.note}</span>
        </p>
      )}

      {marked === 0 && (
        <p
          role="status"
          className="tabel-note flex items-start gap-2 border border-warning/50 bg-warning-soft px-3 py-2 text-[13px] text-fg"
        >
          <TriangleAlert size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            Bu oyda hali birorta davomat qayd etilmagan — jadvaldagi hamma katak «·». Kameralar ishlayotganini va
            odamlarning yuzi ro&apos;yxatga olinganini tekshiring.
          </span>
        </p>
      )}

      <IntelPanel
        title="Davomat varag'i"
        code={docRef}
        right={<MicroLabel>{monthText}</MicroLabel>}
        bodyClassName="min-w-0"
      >
        <TabelSheet data={data} groupLabel={groupLabel} />
      </IntelPanel>

      {/* Shartli belgilar — DOIM, chop etilgan varaq o'zini tushuntirishi
          kerak. Rasmiy kalit shakli: har belgi o'z ramkasida, yonida
          ma'nosi; ikki ustunda joylashadi. */}
      <section className="tabel-legend intel-key intel-panel intel-brackets px-3 py-2.5" aria-label="Shartli belgilar">
        <MicroLabel>Shartli belgilar</MicroLabel>
        <ul className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {legend.map((item, index) => {
            const mark = normalizeMark(item.mark);
            return (
              // Kalitda indeks ham bor: server bitta belgini ikki marta
              // yuborsa React kalitlari to'qnashib, ro'yxat buzilardi.
              <li key={`${item.mark}-${index}`} className="flex items-center gap-2 text-[12px] text-muted">
                <span className={cn('intel-key-mark shrink-0', TABEL_MARK_CLASS[mark])} aria-hidden="true">
                  {item.mark}
                </span>
                <span className="min-w-0">{item.label}</span>
              </li>
            );
          })}
        </ul>
        {/* O'ngdagi ustunlar nimani anglatishi qog'ozda hech qayerda
            yozilmagan edi — imzolovchi "Ish kuni" nimadan hisoblanganini
            so'rardi. Bitta gap bilan tushuntiriladi. */}
        <p className="mt-2 border-t border-border pt-2 text-[11px] leading-4 text-subtle">
          O&apos;ngdagi ustunlar — shu odamning oy bo&apos;yicha yakuni. «Ish kuni» — dam olish («D») bo&apos;lmagan
          kunlar soni; «Keldi» + «Kech» + «Kelmadi» + «Ma&apos;lumot yo&apos;q» ayni shunga teng.
        </p>
      </section>

      {/* Imzo bloki — faqat qog'ozda. */}
      <section className="print-only tabel-sign" aria-hidden="true">
        <div className="tabel-sign-row">
          <span>Mas&apos;ul shaxs:</span>
          <span className="tabel-sign-line" />
          <span className="tabel-sign-hint">(F.I.Sh., imzo)</span>
        </div>
        <div className="tabel-sign-row">
          <span>Bo&apos;linma rahbari:</span>
          <span className="tabel-sign-line" />
          <span className="tabel-sign-hint">(F.I.Sh., imzo)</span>
        </div>
        <div className="tabel-sign-row">
          <span>Sana: «____» ____________ 20____ y.</span>
        </div>
      </section>

      <DocumentFooter
        className="print-hide"
        note={
          <>
            Xizmat uchun. Hujjat <CodeText>{docRef}</CodeText> raqami bilan tizimda tuzilgan; sonlar varaqdagi
            belgilardan sanaladi.
          </>
        }
      />
    </div>
  );
}

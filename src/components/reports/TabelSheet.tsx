import { cn } from '../../ui';
import { todayInTashkent } from '../../lib/uzDate';
import {
  TABEL_MARKS,
  TABEL_MARK_CELL,
  TABEL_MARK_CLASS,
  fallbackMark,
  grandTotals,
  normalizeMark,
  rowTotals,
  weekdayLetter,
  weekdayName,
  type TabelPerson,
  type TabelReport,
} from '../../lib/tabelApi';

interface TabelSheetProps {
  data: TabelReport;
  /** Talaba — "Guruh", xodim — "Bo'linma". */
  groupLabel: string;
  today?: string;
}

/** O'ngdagi jami ustunlari — qog'ozda ham, ekranda ham bir xil tartib. */
const TOTAL_COLUMNS: { key: keyof TabelPerson['totals']; label: string; hint: string }[] = [
  // «Keldi» emas: bu ustun faqat o'z vaqtida kelganlar — hisobot sahifasidagi
  // «Keldi» esa kech kelganlarni ham o'z ichiga oladi.
  { key: 'present', label: 'O‘z vaqtida', hint: 'O‘z vaqtida kelgan kunlar (kech kelganlar alohida)' },
  { key: 'late', label: 'Kech', hint: 'Kech kelgan kunlar soni' },
  { key: 'absent', label: 'Kelmadi', hint: 'Kelmagan kunlar soni' },
  // Ustun nomi shartli belgilar ro'yxatidagi («·  Ma'lumot yo'q») va
  // Excel'dagi nom bilan bir xil bo'lishi kerak — "Aniqlanmadi" uchinchi
  // nom edi va imzolayotgan odam uni alohida narsa deb o'ylardi.
  { key: 'unknown', label: "Ma'lumot yo'q", hint: "Ma'lumot yo'q bo'lgan kunlar soni" },
  { key: 'workDays', label: 'Ish kuni', hint: 'Oydagi ish kunlari soni' },
];

/** Yuzi ro'yxatga olinmagan odam uchun sabab — server katak izohini
 *  bermasa ham qator o'zini tushuntirib tursin. */
const NOT_ENROLLED_REASON = "Yuzi ro'yxatga olinmagan — davomat qayd etilmaydi";

/** Sarlavha katagi: monoshrift, kichik bosh harf — hujjat jadvali
 *  ko'rinishi (ustun nomlari matn emas, YORLIQ bo'lib turadi). */
const HEAD = 'intel-micro !text-muted border-b border-border-strong px-1.5 py-1 font-semibold';
const BODY = 'px-1.5 py-1 align-middle';
/** Chap uchta ustunning aniq kengligi — yopishgan ustunlar shu
 *  o'lchamlar bo'yicha joylashadi (left-0 / left-10 / left-[15.5rem]). */
const COL = {
  no: 'w-10 min-w-[2.5rem] max-w-[2.5rem]',
  name: 'w-44 min-w-[11rem] max-w-[11rem]',
  group: 'w-24 min-w-[6rem] max-w-[6rem]',
};
const OFFSET = { no: 'left-0', name: 'left-10', group: 'left-[13.5rem]' };

/** Har 5-kun ustunidan keyin qalinroq chiziq: 31 ta ustun bo'ylab ko'z
 *  chap tomondagi ismdan o'ng tomondagi kunga adashmasdan yetib boradi. */
function isMajorDay(index: number): boolean {
  return index % 5 === 4;
}

/**
 * Oylik tabel jadvali — rasmiy jurnal varag'i.
 *
 * Chap uchta ustun (tartib raqami, F.I.Sh., guruh) yopishib turadi —
 * 31 ta kun ustunini aylantirganda ham kimning qatori ekani ko'rinadi;
 * uchinchi ustunning o'ng chegarasi qalinroq, chunki aynan o'sha yerda
 * "kim" tugab, "qachon" boshlanadi. Har katakda ingichka to'r, har
 * beshinchi kun va har beshinchi odamdan keyin qalin chiziq bor.
 * Har katakdagi BELGI asosiy signal: qog'oz oq-qora bosiladi, shuning
 * uchun rang faqat ekranda yordam beradi.
 */
export default function TabelSheet({ data, groupLabel, today = todayInTashkent() }: TabelSheetProps) {
  const todayDay = today.slice(0, 7) === data.month ? Number(today.slice(8, 10)) : null;
  const sheetTotals = grandTotals(data);
  const lastIndex = data.people.length - 1;

  return (
    <div data-tabel-scroll className="overflow-x-auto bg-surface">
      <table data-tabel className="w-full border-collapse text-[13px] tabular-nums">
        <caption className="sr-only">
          {data.title} — {data.scope}, {data.monthLabel}
        </caption>
        <thead>
          <tr>
            <th scope="col" className={cn(HEAD, STICKY_HEAD, OFFSET.no, COL.no, 'z-30 text-center')}>
              №
            </th>
            <th scope="col" className={cn(HEAD, STICKY_HEAD, OFFSET.name, COL.name, 'z-30 text-left')}>
              F.I.Sh.
            </th>
            <th
              scope="col"
              data-sticky-edge
              className={cn(HEAD, STICKY_HEAD, OFFSET.group, COL.group, 'z-30 text-left')}
            >
              {groupLabel}
            </th>
            {data.days.map((day, index) => {
              const name = weekdayName(day.weekday, data.month, day.day);
              const isToday = todayDay === day.day;
              return (
                <th
                  key={day.day}
                  scope="col"
                  data-day={day.day}
                  data-rest={day.isWorkDay ? undefined : ''}
                  data-today={isToday ? '' : undefined}
                  data-major={isMajorDay(index) ? '' : undefined}
                  title={`${day.day}-kun, ${name}${day.isWorkDay ? '' : ' — dam olish kuni'}`}
                  className={cn(
                    HEAD,
                    'intel-code !normal-case !tracking-normal sticky top-0 z-20 w-6 min-w-[1.5rem] px-0 text-center',
                    day.isWorkDay ? 'bg-surface-2' : 'bg-surface-3 !text-subtle',
                    isToday && '!text-primary',
                  )}
                >
                  <span className="block text-[9px] font-normal uppercase leading-tight opacity-70">
                    {weekdayLetter(data.month, day.day)}
                  </span>
                  <span className="block text-[12px] leading-tight">{day.day}</span>
                </th>
              );
            })}
            {TOTAL_COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                title={column.hint}
                className={cn(HEAD, 'sticky top-0 z-20 w-11 min-w-[2.75rem] max-w-[2.75rem] intel-micro-wrap leading-tight border-l border-border-strong bg-surface-2 text-center')}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.people.map((person, index) => {
            const byDay = new Map(person.cells?.map((cell) => [cell.day, cell]) ?? []);
            // Jami — qatorda CHIZILGAN belgilardan (tabelApi.rowTotals),
            // server `totals`idan emas: qog'ozdagi son ko'z bilan sanab
            // chiqilganda ham to'g'ri chiqishi shart.
            const totals = rowTotals(person, data.days);
            // Zebra chiziq yopishgan ustunlarda ham ko'rinsin — shuning
            // uchun fon qatorga emas, HAR katakka beriladi.
            const stripe = index % 2 === 1 ? 'bg-surface-2/50' : 'bg-surface';
            // Har 5-odamdan keyin qalin chiziq (oxirgi qatorda keraksiz —
            // u yerda jadvalning o'z chegarasi turadi).
            const majorRow = index % 5 === 4 && index !== lastIndex;
            return (
              <tr
                key={person.id}
                data-tabel-row
                data-major-row={majorRow ? '' : undefined}
                className="border-t border-border/70"
              >
                <td className={cn(BODY, STICKY_BODY, OFFSET.no, COL.no, stripe, 'intel-code text-center text-subtle')}>
                  {index + 1}
                </td>
                <th
                  scope="row"
                  title={person.fullName}
                  className={cn(BODY, STICKY_BODY, OFFSET.name, COL.name, stripe, 'truncate text-left font-medium')}
                >
                  {person.fullName}
                  {!person.enrolled && (
                    <span className="ml-1.5 text-[11px] font-normal text-muted" title={NOT_ENROLLED_REASON}>
                      (yuzi yo&apos;q)
                    </span>
                  )}
                </th>
                <td
                  title={person.group}
                  data-sticky-edge
                  className={cn(BODY, STICKY_BODY, OFFSET.group, COL.group, stripe, 'truncate text-left text-muted')}
                >
                  {person.group}
                </td>
                {data.days.map((day, dayIndex) => {
                  const cell = byDay.get(day.day);
                  // Server katak bermagan kun ham bo'sh qolmasin: ish
                  // kunida "·", dam olish kunida "D" (fallbackMark).
                  const mark = normalizeMark(cell?.mark ?? fallbackMark(day));
                  const title =
                    cell?.title ||
                    (person.enrolled
                      ? `${day.day}-kun: ${TABEL_MARKS[mark].label}`
                      : `${day.day}-kun: ${NOT_ENROLLED_REASON}`);
                  return (
                    <td
                      key={day.day}
                      data-tabel-cell
                      data-day={day.day}
                      data-mark={mark}
                      data-rest={day.isWorkDay ? undefined : ''}
                      data-today={todayDay === day.day ? '' : undefined}
                      data-major={isMajorDay(dayIndex) ? '' : undefined}
                      title={title}
                      aria-label={`${person.fullName}, ${title}`}
                      className={cn(
                        BODY,
                        'intel-code px-0 text-center text-[13px] font-bold outline-offset-[-2px]',
                        TABEL_MARK_CLASS[mark],
                        TABEL_MARK_CELL[mark] || stripe,
                        !day.isWorkDay && 'bg-surface-3/70',
                      )}
                    >
                      {mark}
                    </td>
                  );
                })}
                {TOTAL_COLUMNS.map((column) => (
                  <td
                    key={column.key}
                    data-total={column.key}
                    className={cn(BODY, stripe, 'intel-code border-l border-border-strong text-center')}
                  >
                    {totals[column.key]}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
        {/* Pastdagi "Jami" satri: imzolovchi varaqning yakunini bir
            qarashda ko'radi. Sonlar qatorlardan yig'iladi, shuning uchun
            ustunni ko'z bilan qo'shib chiqqanda ham shu son chiqadi. */}
        <tfoot>
          <tr data-tabel-foot className="border-t-2 border-border-strong font-semibold">
            <td className={cn(BODY, STICKY_BODY, OFFSET.no, COL.no, 'bg-surface-2 text-center')} aria-hidden="true" />
            <th
              scope="row"
              colSpan={2}
              data-sticky-edge
              className={cn(BODY, STICKY_BODY, OFFSET.name, 'intel-micro !text-fg bg-surface-2 text-left')}
            >
              Jami
            </th>
            {data.days.map((day, index) => (
              <td
                key={day.day}
                data-major={isMajorDay(index) ? '' : undefined}
                className={cn(BODY, 'bg-surface-2 px-0')}
                aria-hidden="true"
              />
            ))}
            {TOTAL_COLUMNS.map((column) => (
              <td
                key={column.key}
                data-total-all={column.key}
                className={cn(BODY, 'intel-code border-l border-border-strong bg-surface-2 text-center')}
              >
                {column.key === 'workDays' ? '—' : sheetTotals[column.key]}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

const STICKY_HEAD = 'sticky top-0 bg-surface-2';
const STICKY_BODY = 'sticky z-10';

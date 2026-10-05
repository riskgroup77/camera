import { useEffect, useState } from 'react';
import { RefreshCw, TriangleAlert } from 'lucide-react';
import { Badge, Button, DataTable, ErrorState, SkeletonTiles, StatTile, cn, type DataTableColumn } from '../../ui';
import { ApiError, isAbortError } from '../../lib/apiClient';
import { getAttendanceCameras } from '../../lib/teachersApi';
import type { AttendanceCamera, AttendanceCameras } from '../../types';

const COLUMNS: DataTableColumn<AttendanceCamera>[] = [
  {
    key: 'name',
    header: 'Kamera',
    sortValue: (c) => c.name,
    cell: (c) => (
      <div className={cn('min-w-0', !c.attendanceEnabled && 'opacity-60')}>
        <p className="font-medium text-fg">{c.name}</p>
        <p className="text-xs text-muted">
          {c.building} · {c.zone}
        </p>
      </div>
    ),
  },
  {
    key: 'role',
    header: 'Vazifasi',
    hideOnMobile: true,
    cell: (c) => (
      <span className="text-[13px] text-muted">
        {c.role}
        {c.checkIntervalSeconds ? ` · har ${c.checkIntervalSeconds} s` : ''}
      </span>
    ),
  },
  {
    key: 'attendance',
    header: 'Davomat',
    sortValue: (c) => (c.attendanceEnabled ? 1 : 0),
    cell: (c) =>
      c.attendanceEnabled ? (
        <Badge tone="success" dot>
          Ishlaydi
        </Badge>
      ) : (
        <span className="text-xs text-muted">{c.disabledReason}</span>
      ),
  },
  {
    key: 'online',
    header: 'Aloqa va tasvir',
    cell: (c) => (
      <span className="inline-flex gap-1.5">
        <Badge tone={c.online ? 'success' : 'danger'}>{c.online ? 'Aloqada' : "Aloqa yo'q"}</Badge>
        <Badge tone={c.video ? 'success' : 'warning'}>{c.video ? 'Tasvir bor' : "Tasvir yo'q"}</Badge>
      </span>
    ),
  },
  {
    key: 'recognized',
    header: 'Bugun necha kishini tanigan',
    align: 'right',
    sortValue: (c) => c.recognizedToday,
    sortFirst: 'desc',
    cell: (c) => (
      <div>
        <p className="font-semibold tabular-nums text-fg">{c.recognizedToday}</p>
        <p className="text-xs tabular-nums text-muted">{c.lastRecognition ?? '—'}</p>
      </div>
    ),
  },
  {
    key: 'ai',
    header: 'Texnik tafsilot',
    hideOnMobile: true,
    cell: (c) =>
      c.framesCheckedToday > 0 ? (
        <div className="whitespace-nowrap text-xs tabular-nums text-muted">
          <p className="text-fg">
            {c.framesCheckedToday} kadr · {c.facesSeenToday} yuz
          </p>
          <p>
            {c.facePxMedian ? `~${c.facePxMedian} px` : '—'}
            {c.bestSimilarityToday != null ? ` · max ${c.bestSimilarityToday.toFixed(2)}` : ''}
            {c.relaxedPendingToday > 0 ? ` · ${c.relaxedPendingToday} kutilmoqda` : ''}
          </p>
          {(c.lastCycleSeconds != null || c.streamInUse) && (
            <p>
              {c.lastCycleSeconds != null ? `aylanish ${Math.round(c.lastCycleSeconds)} s (kadr ${Math.round(c.lastGrabSeconds ?? 0)} s)` : ''}
              {c.streamInUse ? ` · ${c.streamInUse}` : ''}
            </p>
          )}
        </div>
      ) : (
        <span className="text-xs text-subtle">{c.lastChecked ?? '—'}</span>
      ),
  },
  {
    key: 'diagnosis',
    header: 'Nega tanimayapti',
    cell: (c) =>
      c.diagnosis ? (
        <span className="block min-w-[12rem] text-xs text-warning">{c.diagnosis}</span>
      ) : (
        <span className="text-xs text-muted">Muammo topilmadi</span>
      ),
  },
];

/** Davomat kameralari tashxisi: qaysi kamera davomatga yozadi, tarmoq/tasvir
 *  holati, bugun kimni tanigani va nima uchun tanimayotgani. */
export function AttendanceCamerasPanel() {
  const [data, setData] = useState<AttendanceCameras | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getAttendanceCameras({ signal: controller.signal })
      .then(setData)
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      });
    return () => controller.abort();
  }, [nonce]);

  // Tashxis jonli: har daqiqada yangilanadi (sahifa ko'rinib turganda).
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') setNonce((n) => n + 1);
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  if (error) return <ErrorState variant="block" message={error} onRetry={() => setNonce((n) => n + 1)} />;
  if (!data)
    return (
      <div className="flex flex-col gap-5">
        <SkeletonTiles count={4} />
        <DataTable columns={COLUMNS} rows={[]} rowKey={(c) => c.id} loading />
      </div>
    );

  const problems = data.cameras.filter((c) => c.attendanceEnabled && c.diagnosis);

  return (
    <div className="flex flex-col gap-5">
      {/* Tashxis ma'lumoti bir marta olinadi va o'zi yangilanmaydi: kabel
          ulanib, kamera tasvir bera boshlaganini ko'rish uchun ilgari butun
          sahifani qayta yuklash kerak edi. */}
      <div className="flex justify-end">
        <Button
          size="sm"
          icon={RefreshCw}
          onClick={() => {
            setData(null);
            setNonce((n) => n + 1);
          }}
        >
          Yangilash
        </Button>
      </div>
      {(!data.staffModuleActive || !data.studentModuleActive) && (
        <div className="flex items-start gap-2 rounded-card border border-warning/30 bg-warning-soft px-4 py-3 text-[13px] text-warning">
          <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            {!data.staffModuleActive && "Xodimlar davomatini yozish o‘chirib qo‘yilgan — hech bir kamera xodimlarni qayd etmaydi. "}
            {!data.studentModuleActive && "Talabalar davomatini yozish o‘chirib qo‘yilgan — hech bir kamera talabalarni qayd etmaydi."}
          </span>
        </div>
      )}
      {problems.length > 0 && data.peopleRecognizedToday === 0 && (
        <div className="rounded-card border border-warning/30 bg-warning-soft px-4 py-3 text-[13px] text-warning">
          <p className="font-semibold">Bugun hali birorta odam davomatga tushmadi.</p>
          <p className="mt-1">
            Har bir kamera uchun «Nega tanimayapti» ustuniga qarang: kamera umuman tekshirilmayaptimi, suratda yuz
            ko&apos;rinmayaptimi, yuzlar juda kichikmi yoki tanilgan yuz ro&apos;yxatdagi hech kimga yetarlicha
            o&apos;xshamayaptimi.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label="Davomatni yozadigan kameralar"
          value={`${data.attendanceEnabled} / ${data.total}`}
          hint="Kelishni shular belgilaydi"
        />
        <StatTile
          label="Aloqada / tasvir bermoqda"
          value={`${data.online} / ${data.video}`}
          tone={data.video < data.attendanceEnabled ? 'warning' : 'success'}
          hint="Tasvirsiz kamera hech kimni tanimaydi"
        />
        <StatTile label="Bugun tanigan" value={data.recognizingToday} />
        <StatTile
          label="Bugun tanilgan odamlar"
          value={data.peopleRecognizedToday}
          hint={`Butun tizimda yuzi ro'yxatdan o'tgani ${data.enrolledFaces} kishi — faqat ularni tanish mumkin`}
        />
      </div>

      <DataTable
        columns={COLUMNS}
        rows={data.cameras}
        rowKey={(c) => c.id}
        rowTone={(c) => (c.attendanceEnabled && c.diagnosis ? 'warning' : null)}
        defaultSort={{ key: 'attendance', dir: 'desc' }}
        emptyTitle="Davomat uchun sozlangan kamera yo'q"
        emptyDescription="Faol kamera yo'q yoki davomat modullari (#6, #7) o'chirilgan. Har bir faol kamera odamni birinchi ko'rgan paytini kelish deb yozadi."
        ariaLabel="Davomat kameralari"
      />
      <p className="text-xs leading-relaxed text-muted">
        <span className="font-medium text-fg">Jadvalni qanday o&apos;qish kerak.</span> «Tasvir bor» — kamera so&apos;nggi daqiqalarda
        surat yuborib turgani; tasvir bo&apos;lmasa hech kim tanilmaydi. «Bugun necha kishini tanigan» — shu kamerada bugun tanilgan
        turli odamlar soni va oxirgi tanish vaqti. «Texnik tafsilot» ustuni mutaxassis uchun: tekshirilgan suratlar, ulardan topilgan
        yuzlar va yuzning o&apos;rtacha balandligi (piksel). Dastur odamni tanidi deb hisoblashi uchun o&apos;xshashlik {data.matchThreshold} dan
        yuqori bo&apos;lishi kerak
        {data.relaxedThreshold ? `; ${data.relaxedThreshold} va ${data.matchThreshold} oralig'idagi o'xshashlik esa odam ikkinchi marta ko'ringanda tasdiqlanadi` : ''}.
        Yuz juda kichik yoki qorong&apos;i bo&apos;lsa o&apos;xshashlik past chiqadi — bunda kamerani eshikka yaqinroq yoki pastroq
        o&apos;rnatish kerak.
      </p>
    </div>
  );
}

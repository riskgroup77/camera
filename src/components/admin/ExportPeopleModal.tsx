import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Download, Loader2, Users } from 'lucide-react';
import { Button, ErrorState, Field, Modal, Select, Tabs, cn, focusRing } from '../../ui';
import { api, type Page } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { config } from '../../lib/config';
import {
  NO_FACULTY_KEY,
  NO_FACULTY_LABEL,
  PERSON_LABELS,
  STATUS_FILTERS,
  exportFilename,
  type ExportKind,
  type PersonType,
  type StatusFilter,
} from '../../lib/peopleFilters';
import type { BiometricsCoverage, StudentStaffRecord } from '../../types';

export interface ExportDefaults {
  type: PersonType;
  faculty: string;
  course: number | null;
  status: StatusFilter;
  search: string;
}

const KIND_OPTIONS: { kind: ExportKind; title: string; description: string; icon: typeof Users }[] = [
  {
    kind: 'people',
    title: "Ro'yxat",
    description: 'Ism, JSHSHIR, bo‘linma va yuz holati',
    icon: Users,
  },
  {
    kind: 'stats',
    title: 'Statistika',
    description: 'Bo‘linmalar kesimida yig‘ma sonlar',
    icon: BarChart3,
  },
];

/**
 * Yuklab olish oynasi: KIMLAR (xodim/talaba), QANDAY FAYL (ro'yxat/statistika)
 * va ro'yxat uchun QAYSI QISMI (holat, fakultet, kurs).
 *
 * Boshlang'ich qiymatlar ekrandagi filtrdan olinadi — odatda odam aynan
 * ko'rib turgan narsasini yuklamoqchi bo'ladi — lekin har birini shu yerda
 * o'zgartirish mumkin. Faylga necha kishi tushishi oldindan ko'rsatiladi:
 * bo'sh fayl yoki kutilmaganda 6 ming qatorli fayl yuklanib qolmasin.
 */
export default function ExportPeopleModal({
  open,
  onClose,
  defaults,
  coverage,
}: {
  open: boolean;
  onClose: () => void;
  defaults: ExportDefaults;
  coverage: Record<PersonType, BiometricsCoverage | null>;
}) {
  const { token } = useAuth();
  const [type, setType] = useState<PersonType>(defaults.type);
  const [kind, setKind] = useState<ExportKind>('people');
  const [status, setStatus] = useState<StatusFilter>(defaults.status);
  const [faculty, setFaculty] = useState(defaults.faculty);
  const [course, setCourse] = useState<number | null>(defaults.course);
  const [useSearch, setUseSearch] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const [counting, setCounting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const searchText = defaults.search.trim();

  useEffect(() => {
    if (!open) return;
    setType(defaults.type);
    setKind('people');
    setStatus(defaults.status);
    setFaculty(defaults.faculty);
    setCourse(defaults.course);
    setUseSearch(Boolean(searchText));
    setError(null);
    // Faqat oyna ochilganda ekrandagi filtrdan boshlanadi
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function changeType(next: PersonType) {
    if (next === type) return;
    setType(next);
    setFaculty('');
    setCourse(null);
    setUseSearch(false); // qidiruv boshqa bo'limda yozilgan edi
  }

  const params = useMemo(() => {
    const p: Record<string, string> = { type };
    if (kind === 'people') {
      if (faculty) p.faculty = faculty;
      if (type === 'talaba' && course) p.course = String(course);
      if (status) p.biometricsStatus = status;
      if (useSearch && searchText) p.search = searchText;
    }
    return p;
  }, [type, kind, faculty, course, status, useSearch, searchText]);

  // Faylga necha kishi tushishi
  useEffect(() => {
    if (!open || !token) return;
    if (kind === 'stats') {
      setCount(coverage[type]?.total ?? null);
      return;
    }
    let cancelled = false;
    setCounting(true);
    const timer = window.setTimeout(() => {
      api
        .post<Page<StudentStaffRecord>>('/api/students-staff/search', { ...params, pageSize: 1 }, token)
        .then((page) => !cancelled && setCount(page.total))
        .catch(() => !cancelled && setCount(null))
        .finally(() => !cancelled && setCounting(false));
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, token, kind, type, params, coverage]);

  const facultyOptions = (coverage[type]?.byFaculty ?? []).map((row) => ({
    value: row.faculty === NO_FACULTY_LABEL ? NO_FACULTY_KEY : row.faculty,
    label: `${row.faculty} (${row.total.toLocaleString('ru-RU')})`,
  }));
  const courseOptions = (coverage.talaba?.byCourse ?? []).filter((row) => row.courseNumber !== null);

  async function download() {
    if (!token) return;
    setDownloading(true);
    setError(null);
    try {
      // POST: qidiruv (JSHSHIR bo'lishi mumkin) URL/access logga tushmasin.
      const res = await fetch(`${config.apiBaseUrl}/api/students-staff/export`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, ...params, course: params.course ? Number(params.course) : undefined }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = exportFilename(kind, type, course, status);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      onClose();
    } catch {
      setError("Faylni tayyorlab bo'lmadi");
    } finally {
      setDownloading(false);
    }
  }

  const who = PERSON_LABELS[type].toLowerCase();
  const empty = kind === 'people' && count === 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Excel faylni yuklab olish"
      size="lg"
      footer={
        <>
          <Button onClick={onClose} disabled={downloading}>
            Bekor qilish
          </Button>
          <Button variant="primary" icon={Download} onClick={download} loading={downloading} disabled={empty || !token}>
            {downloading ? 'Tayyorlanmoqda…' : 'Yuklab olish'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5 pb-1">
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Kimlar</p>
          <Tabs
            variant="segmented"
            ariaLabel="Kimlar"
            tabs={[
              { id: 'xodim' as PersonType, label: PERSON_LABELS.xodim },
              { id: 'talaba' as PersonType, label: PERSON_LABELS.talaba },
            ]}
            value={type}
            onChange={changeType}
          />
        </div>

        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Fayl</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {KIND_OPTIONS.map((option) => {
              const Icon = option.icon;
              const active = kind === option.kind;
              return (
                <button
                  key={option.kind}
                  type="button"
                  onClick={() => setKind(option.kind)}
                  aria-pressed={active}
                  className={cn(
                    'flex items-start gap-3 rounded-card border p-3 text-left transition-colors',
                    active ? 'border-primary bg-primary-soft' : 'border-border bg-surface hover:border-border-strong',
                    focusRing,
                  )}
                >
                  <span
                    className={cn(
                      'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-control',
                      active ? 'bg-primary text-primary-fg' : 'bg-surface-2 text-muted',
                    )}
                  >
                    <Icon size={16} aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-fg">{option.title}</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-muted">{option.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {kind === 'people' ? (
          <>
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Ro&apos;yxatdan o&apos;tish holati</p>
              <Tabs
                variant="segmented"
                ariaLabel="Ro'yxatdan o'tish holati"
                tabs={STATUS_FILTERS.map((f) => ({ id: f.key, label: f.label }))}
                value={status}
                onChange={setStatus}
              />
            </div>

            <div className={cn('grid gap-3', type === 'talaba' && 'sm:grid-cols-2')}>
              <Field label="Fakultet">
                <Select value={faculty} onChange={setFaculty} placeholder="Barcha fakultetlar" options={facultyOptions} className="sm:w-full" />
              </Field>
              {type === 'talaba' && (
                <Field label="Kurs">
                  <Select
                    value={course ? String(course) : ''}
                    onChange={(value) => setCourse(value ? Number(value) : null)}
                    placeholder="Barcha kurslar"
                    options={courseOptions.map((row) => ({
                      value: String(row.courseNumber),
                      label: `${row.course} (${row.total.toLocaleString('ru-RU')})`,
                    }))}
                    className="sm:w-full"
                  />
                </Field>
              )}
            </div>

            {searchText && type === defaults.type && (
              <label className="flex items-center gap-2 text-sm text-fg">
                <input
                  type="checkbox"
                  checked={useSearch}
                  onChange={(e) => setUseSearch(e.target.checked)}
                  className="h-4 w-4 rounded border-border-strong accent-primary"
                />
                Ekrandagi qidiruvni ham qo&apos;llash: «{searchText}»
              </label>
            )}
          </>
        ) : (
          <p className="rounded-control bg-surface-2 px-3 py-2.5 text-xs leading-relaxed text-muted">
            Statistika barcha {who} bo&apos;yicha tuziladi:{' '}
            {type === 'talaba' ? 'umumiy, fakultetlar, kurslar va guruhlar kesimida.' : 'umumiy, fakultetlar va kafedra/bo‘limlar kesimida.'}
          </p>
        )}

        <div
          role="status"
          className={cn(
            'flex items-center justify-between gap-3 rounded-control px-3 py-2.5 text-sm',
            empty ? 'bg-warning-soft text-fg' : 'bg-primary-soft text-fg',
          )}
        >
          <span>
            {counting && kind === 'people' ? (
              <span className="flex items-center gap-2 text-muted">
                <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Hisoblanmoqda…
              </span>
            ) : count === null ? (
              "Sonini aniqlab bo'lmadi"
            ) : empty ? (
              'Tanlangan shartlarga mos odam yo‘q'
            ) : (
              <>
                Faylga <span className="font-semibold tabular-nums">{count.toLocaleString('ru-RU')}</span> ta {who} tushadi
              </>
            )}
          </span>
          <span className="shrink-0 text-xs text-muted">.xlsx</span>
        </div>

        {error && <ErrorState title="Yuklab bo'lmadi" message={error} />}
      </div>
    </Modal>
  );
}

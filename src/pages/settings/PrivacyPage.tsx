import { useEffect, useState } from 'react';
import { Download, FileCheck, Power, Trash2, UserRound } from 'lucide-react';
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Input,
  IntelPanel,
  KeyValue,
  Page,
  SearchInput,
  Select,
  Skeleton,
  cn,
  focusRing,
  useToast,
  type KeyValueItem,
  type Tone,
} from '../../ui';
import { ApiError, isAbortError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useDebouncedValue } from '../../lib/useDebouncedValue';
import {
  CONSENT_SOURCE_LABELS,
  PRIVACY_FILTER_LABELS,
  confirmationWord,
  consentState,
  eraseBiometrics,
  exportFilename,
  exportPersonData,
  fetchPersonBiometrics,
  fetchPrivacyOverview,
  formatRetentionDays,
  recordConsent,
  formatUzDate,
  matchesConfirmation,
  searchPrivacyPeople,
  setPersonActive,
  type ConsentState,
  type PrivacyBiometrics,
  type PrivacyFilter,
  type PrivacyOverview,
  type PrivacyPerson,
} from '../../lib/privacyApi';

const BREADCRUMBS = [{ label: 'Sozlamalar' }, { label: 'Maxfiylik' }];

const CONSENT_BADGE: Record<ConsentState, { tone: Tone; label: string }> = {
  current: { tone: 'success', label: 'Rozilik bor' },
  outdated: { tone: 'warning', label: 'Rozilik eskirgan' },
  missing: { tone: 'danger', label: 'Rozilik yo‘q' },
  not_needed: { tone: 'neutral', label: 'Biometrika yo‘q' },
};

const FILTER_OPTIONS = (Object.keys(PRIVACY_FILTER_LABELS) as PrivacyFilter[]).map((value) => ({
  value,
  label: PRIVACY_FILTER_LABELS[value],
}));

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** Saqlash muddatlari — faqat ko‘rish (qiymatlar server sozlamasida). */
function RetentionPanel({ overview }: { overview: PrivacyOverview }) {
  const r = overview.retention;
  const items: KeyValueItem[] = [
    { label: 'Hodisa surati', value: formatRetentionDays(r.snapshotRetentionDays, 'Hodisa bilan') },
    { label: 'Hodisalar', value: formatRetentionDays(r.eventRetentionDays) },
    { label: 'Audit jurnali', value: formatRetentionDays(r.auditLogRetentionDays) },
    { label: 'Turniket qaydlari', value: formatRetentionDays(r.accessEventRetentionDays) },
    { label: 'Bildirishnomalar', value: formatRetentionDays(r.notificationLogRetentionDays) },
    { label: 'Kameradagi tashriflar', value: formatRetentionDays(r.presenceVisitRetentionDays ?? 0) },
    { label: 'Notanish yuzlar (rasmi bilan)', value: formatRetentionDays(r.unknownSightingRetentionDays ?? 0) },
    {
      label: 'Yuz (faolsizlantirilgach)',
      value: formatRetentionDays(r.biometricRetentionDaysAfterInactive, 'O‘chirilmaydi'),
    },
  ];
  return (
    <IntelPanel title="Saqlash muddati" bodyClassName="p-3">
      <KeyValue items={items} />
      <p className="mt-2.5 border-t border-border pt-2 text-[12px] text-muted">
        {`Biometrikasi bor: ${overview.withBiometrics} · rozilik yo‘q: ${overview.biometricsWithoutConsent}`}
        {overview.consentOutdated > 0 && ` · eski rozilik matni: ${overview.consentOutdated}`}
        {overview.inactiveWithBiometrics > 0 && ` · faol emas, yuzi saqlangan: ${overview.inactiveWithBiometrics}`}
        {overview.biometricPurgeOverdue > 0 && ` · o‘chirish muddati o‘tgan: ${overview.biometricPurgeOverdue}`}
        {overview.nextBiometricPurgeAt && ` · keyingi avto-o‘chirish: ${formatUzDate(overview.nextBiometricPurgeAt)}`}
      </p>
    </IntelPanel>
  );
}

export default function PrivacyPage() {
  const { token } = useAuth();
  const toast = useToast();
  const [overview, setOverview] = useState<PrivacyOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<PrivacyFilter | ''>('');
  const debounced = useDebouncedValue(search, 300);
  const [people, setPeople] = useState<PrivacyPerson[] | null>(null);
  const [total, setTotal] = useState(0);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchPrivacyOverview(token, ctrl.signal)
      .then((data) => {
        setOverview(data);
        setOverviewError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setOverviewError(errorText(err, 'Ma‘lumotni yuklab bo‘lmadi'));
      });
    return () => ctrl.abort();
  }, [token, nonce]);

  // Qidiruv so‘z yoki filtr bo‘lmasa ro‘yxat ko‘rsatilmaydi: sahifa
  // "ro‘yxat" emas, aniq odam bo‘yicha so‘rov uchun.
  const hasQuery = debounced.trim().length >= 2 || filter !== '';
  useEffect(() => {
    if (!hasQuery) {
      setPeople(null);
      setTotal(0);
      return;
    }
    const ctrl = new AbortController();
    searchPrivacyPeople(token, { search: debounced, filter: filter || null, pageSize: 20 }, ctrl.signal)
      .then((page) => {
        setPeople(page.items);
        setTotal(page.total);
        setListError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setListError(errorText(err, 'Qidirib bo‘lmadi'));
      });
    return () => ctrl.abort();
  }, [token, debounced, filter, hasQuery, nonce]);

  /** Amal (o‘chirish, faolsizlantirish) — ro‘yxat va umumiy sonlar yangilanadi. */
  const refresh = () => setNonce((n) => n + 1);

  return (
    <Page title="Maxfiylik" breadcrumbs={BREADCRUMBS}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="F.I.Sh., JSHSHIR yoki HEMIS ID"
              ariaLabel="Shaxsni qidirish"
              autoFocus
              className="min-w-0 flex-1"
            />
            <Select
              value={filter}
              onChange={(value) => setFilter(value as PrivacyFilter | '')}
              options={FILTER_OPTIONS}
              placeholder="Hammasi"
              ariaLabel="Filtr"
              highlightActive
              className="w-48"
            />
          </div>

          {listError ? (
            <ErrorState message={listError} onRetry={refresh} />
          ) : !hasQuery ? (
            <EmptyState icon={UserRound} title="Shaxsni toping" description="Kamida 2 harf yozing yoki filtr tanlang." />
          ) : people === null ? (
            <Skeleton className="h-40" />
          ) : people.length === 0 ? (
            <EmptyState icon={UserRound} title="Topilmadi" />
          ) : (
            <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <ul className="divide-y divide-border rounded-card border border-border bg-surface" aria-label="Natijalar">
                {people.map((person) => {
                  const consent = CONSENT_BADGE[consentState(person)];
                  return (
                    <li key={person.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(person.id)}
                        aria-current={selectedId === person.id || undefined}
                        className={cn(
                          'flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-surface-2',
                          focusRing,
                          selectedId === person.id && 'bg-primary-soft',
                        )}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-fg">{person.fullName}</span>
                          <span className="block truncate text-xs text-muted">
                            {[person.groupOrPosition, person.active ? null : 'faol emas'].filter(Boolean).join(' · ')}
                          </span>
                        </span>
                        <Badge tone={consent.tone}>{consent.label}</Badge>
                      </button>
                    </li>
                  );
                })}
                {total > people.length && (
                  <li className="px-3 py-2 text-xs text-muted">{`Yana ${total - people.length} ta — qidiruvni aniqlashtiring`}</li>
                )}
              </ul>
              {selectedId ? (
                <PersonPanel key={`${selectedId}-${nonce}`} personId={selectedId} onChanged={refresh} toast={toast} />
              ) : (
                <EmptyState title="Shaxsni tanlang" />
              )}
            </div>
          )}
        </div>

        <aside className="min-w-0">
          {overviewError ? (
            <ErrorState message={overviewError} onRetry={refresh} />
          ) : overview ? (
            <RetentionPanel overview={overview} />
          ) : (
            <Skeleton className="h-72" />
          )}
        </aside>
      </div>
    </Page>
  );
}

type ToastApi = ReturnType<typeof useToast>;

/** Tanlangan odam: nima saqlanayotgani va amallar. */
function PersonPanel({ personId, onChanged, toast }: { personId: string; onChanged: () => void; toast: ToastApi }) {
  const { token } = useAuth();
  const [data, setData] = useState<PrivacyBiometrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [erasing, setErasing] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState<'export' | 'active' | 'consent' | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchPersonBiometrics(token, personId, ctrl.signal)
      .then(setData)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorText(err, 'Ma‘lumotni yuklab bo‘lmadi'));
      });
    return () => ctrl.abort();
  }, [token, personId]);

  if (error) return <ErrorState message={error} />;
  if (!data) return <Skeleton className="h-72" />;

  const person = data.person;
  const consent = consentState(person);
  const expected = confirmationWord(person.fullName);
  const hasSamples = person.hasBiometrics || data.gallerySamples > 0 || data.linkedSightings > 0;

  const items: KeyValueItem[] = [
    {
      label: 'Rozilik',
      value: CONSENT_BADGE[consent].label,
      hint: person.consentGivenAt
        ? `${formatUzDate(person.consentGivenAt)} · ${CONSENT_SOURCE_LABELS[person.consentSource ?? ''] ?? person.consentSource ?? ''}`
        : undefined,
    },
    {
      label: 'Yuz rasmlari (3 tomon)',
      value: `${[data.photoUrl, data.photoLeftUrl, data.photoRightUrl].filter(Boolean).length} / 3`,
      hint: data.photoUrl && !(data.photoLeftUrl && data.photoRightUrl) ? 'Havola orqali qayta ro‘yxatdan o‘tishi kerak' : undefined,
    },
    { label: 'Yuz vektori', value: data.faceTemplateStored ? 'Bor' : 'Yo‘q' },
    { label: 'Kamera namunalari', value: data.gallerySamples },
    { label: 'Biriktirilgan kadrlar', value: data.linkedSightings },
    {
      label: `Ko‘rinish (${data.recentDays} kun)`,
      value: data.recentSightings,
      hint: data.lastSeenAt ? `Oxirgi: ${formatUzDate(data.lastSeenAt)}` : undefined,
    },
  ];
  if (person.biometricPurgeAt) {
    items.push({ label: 'Avto-o‘chirish', value: formatUzDate(person.biometricPurgeAt) });
  }

  async function doExport() {
    setBusy('export');
    try {
      const blob = await exportPersonData(token, person.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = exportFilename(person);
      link.click();
      // Darhol bekor qilinsa ayrim brauzerlarda yuklab olish uziladi.
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (err) {
      toast.error(errorText(err, 'Eksport qilib bo‘lmadi'));
    } finally {
      setBusy(null);
    }
  }

  async function recordPaperConsent() {
    setBusy('consent');
    try {
      await recordConsent(token, person.id, 'qogoz');
      toast.success('Rozilik qayd etildi');
      onChanged();
    } catch (err) {
      toast.error(errorText(err, 'Bajarib bo‘lmadi'));
    } finally {
      setBusy(null);
    }
  }

  async function toggleActive() {
    setBusy('active');
    try {
      await setPersonActive(token, person.id, !person.active);
      toast.success(person.active ? 'Faolsizlantirildi' : 'Faollashtirildi');
      onChanged();
    } catch (err) {
      toast.error(errorText(err, 'Bajarib bo‘lmadi'));
    } finally {
      setBusy(null);
    }
  }

  async function doErase() {
    // Tasdiq so‘zi — "ha" ni bosib yuborishdan himoya (qaytarib bo‘lmaydi).
    if (!matchesConfirmation(typed, expected)) throw new Error(`Tasdiqlash uchun «${expected}» deb yozing`);
    const res = await eraseBiometrics(token, person.id);
    setErasing(false);
    if (res.photoDeleted) toast.success('Biometrika o‘chirildi');
    else toast.error('Vektor o‘chirildi, rasm ombordan o‘chmadi — keyinroq qayta urining');
    onChanged();
  }

  return (
    <IntelPanel
      title={person.fullName}
      right={!person.active ? <Badge tone="neutral">Faol emas</Badge> : undefined}
      bodyClassName="space-y-3 p-3"
    >
      {(data.photoUrl || data.photoLeftUrl || data.photoRightUrl) && (
        <div className="flex gap-2">
          {(
            [
              ['Chap', data.photoLeftUrl],
              ['Old', data.photoUrl],
              ['O‘ng', data.photoRightUrl],
            ] as const
          ).map(([label, url]) => (
            <figure key={label} className="flex flex-col items-center gap-0.5">
              {url ? (
                <img src={url} alt={`${person.fullName} — ${label}`} className="h-24 w-24 rounded-control border border-border object-cover" />
              ) : (
                <span className="grid h-24 w-24 place-items-center rounded-control border border-dashed border-border text-[11px] text-subtle">yo‘q</span>
              )}
              <figcaption className="text-[11px] text-muted">{label}</figcaption>
            </figure>
          ))}
        </div>
      )}
      <KeyValue items={items} />
      <div className="flex flex-wrap gap-2 border-t border-border pt-3">
        <Button size="sm" icon={Download} loading={busy === 'export'} onClick={doExport}>
          Eksport
        </Button>
        {(consent === 'missing' || consent === 'outdated') && (
          <Button size="sm" icon={FileCheck} loading={busy === 'consent'} onClick={recordPaperConsent} title="Qog‘ozda imzolangan rozilikni qayd etish">
            Rozilikni qayd etish
          </Button>
        )}
        <Button size="sm" icon={Power} loading={busy === 'active'} onClick={toggleActive}>
          {person.active ? 'Faolsizlantirish' : 'Faollashtirish'}
        </Button>
        <Button
          size="sm"
          variant="danger"
          icon={Trash2}
          disabled={!hasSamples}
          onClick={() => {
            setTyped('');
            setErasing(true);
          }}
        >
          Biometrikani o‘chirish
        </Button>
      </div>

      <ConfirmDialog
        open={erasing}
        title="Biometrika o‘chirilsinmi?"
        confirmLabel="O‘chirish"
        onCancel={() => setErasing(false)}
        onConfirm={doErase}
        message={
          <div className="space-y-2">
            <p>Yuz rasmi, vektori va kamera namunalari o‘chadi. Qaytarib bo‘lmaydi.</p>
            <label className="block text-[12px]">
              {`Tasdiqlash: «${expected}»`}
              <Input className="mt-1" value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Tasdiqlash so‘zi" />
            </label>
          </div>
        }
      />
    </IntelPanel>
  );
}

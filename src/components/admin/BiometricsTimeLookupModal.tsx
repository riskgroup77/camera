import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowLeft, Clock, Loader2, Search, SearchX } from 'lucide-react';
import { Avatar, Badge, Button, EmptyState, ErrorState, Input, Modal, cn, focusRing, type Tone } from '../../ui';
import { ApiError, api, type Page } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { BiometricsConfirmation, StudentStaffRecord } from '../../types';

const MIN_QUERY_LENGTH = 2;
const SUGGESTION_LIMIT = 8;
const DEBOUNCE_MS = 250;

const STATUS_LABEL: Record<StudentStaffRecord['biometricsStatus'], string> = {
  tasdiqlangan: 'Yuzi tasdiqlangan',
  kutilmoqda: 'Kutilmoqda',
  yoq: 'Tasdiqlanmagan',
};

const STATUS_TONE: Record<StudentStaffRecord['biometricsStatus'], Tone> = {
  tasdiqlangan: 'success',
  kutilmoqda: 'warning',
  yoq: 'neutral',
};

function describePerson(p: StudentStaffRecord): string {
  return [p.type === 'talaba' ? 'Talaba' : 'Xodim', p.faculty, p.groupOrPosition].filter(Boolean).join(' · ');
}

/** "3 kun oldin" — aniq soatning yonida, qancha vaqt o'tganini bir qarashda ko'rish uchun. */
function timeAgo(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (seconds < 60) return 'hozirgina';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} daqiqa oldin`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} soat oldin`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} kun oldin`;
  const months = Math.floor(days / 30);
  return months < 12 ? `${months} oy oldin` : `${Math.floor(months / 12)} yil oldin`;
}

/**
 * Odam yuzini aniq qachon tasdiqlaganini topish.
 *
 * Ism yozilganda mos variantlar chiqadi; ↑/↓ bilan tanlab Enter bosiladi
 * yoki sichqoncha bilan bosiladi. Variantlar hali kelmagan bo'lsa Enter
 * qidiruvni darhol bajaradi: bitta odam topilsa — uni ochadi, bir nechta
 * bo'lsa — ro'yxatni ko'rsatadi. Ko'p odamdan birinchisini jimgina tanlash
 * bir xil familiyali boshqa odamning vaqtini ko'rsatib qo'yishi mumkin edi.
 */
export default function BiometricsTimeLookupModal({
  open,
  onClose,
  person = null,
}: {
  open: boolean;
  onClose: () => void;
  /** Ro'yxat qatoridan ochilganda — oyna darhol shu odamning natijasi bilan ochiladi. */
  person?: StudentStaffRecord | null;
}) {
  const { token } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const requestSeq = useRef(0);
  const resultSeq = useRef(0);

  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<StudentStaffRecord[]>([]);
  const [highlight, setHighlight] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchedFor, setSearchedFor] = useState<string | null>(null);
  const [result, setResult] = useState<BiometricsConfirmation | null>(null);
  const [loadingResult, setLoadingResult] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetToSearch = useCallback(() => {
    requestSeq.current += 1;
    resultSeq.current += 1;
    setResult(null);
    setLoadingResult(false);
    setSuggestions([]);
    setSearchedFor(null);
    setHighlight(0);
    setError(null);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const choose = useCallback(
    async (target: StudentStaffRecord) => {
      requestSeq.current += 1;
      // Oyna yopilib boshqa odam uchun qayta ochilsa, kechikkan eski javob
      // yangisining ustiga yozilmasin.
      const seq = ++resultSeq.current;
      setSuggestions([]);
      setSearching(false);
      setLoadingResult(true);
      setError(null);
      try {
        const data = await api.get<BiometricsConfirmation>(
          `/api/students-staff/${target.id}/biometrics-confirmation`,
          token,
        );
        if (seq === resultSeq.current) setResult(data);
      } catch (err) {
        if (seq === resultSeq.current) {
          setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi — qayta urinib ko'ring");
        }
      } finally {
        if (seq === resultSeq.current) setLoadingResult(false);
      }
    },
    [token],
  );

  useEffect(() => {
    if (!open) return;
    setQuery('');
    resetToSearch();
    if (person) void choose(person);
  }, [open, person, resetToSearch, choose]);

  const runSearch = useCallback(
    async (text: string): Promise<StudentStaffRecord[] | null> => {
      const seq = ++requestSeq.current;
      setSearching(true);
      try {
        const page = await api.post<Page<StudentStaffRecord>>(
          '/api/students-staff/search',
          { search: text, pageSize: SUGGESTION_LIMIT },
          token,
        );
        if (seq !== requestSeq.current) return null;
        setSuggestions(page.items);
        setSearchedFor(text);
        setHighlight(0);
        setError(null);
        return page.items;
      } catch (err) {
        if (seq === requestSeq.current) {
          setSuggestions([]);
          setError(err instanceof ApiError ? err.message : "Qidirib bo'lmadi — tarmoqni tekshirib, qayta urinib ko'ring");
        }
        return null;
      } finally {
        if (seq === requestSeq.current) setSearching(false);
      }
    },
    [token],
  );

  // Yozish to'xtagach qidirish
  useEffect(() => {
    if (!open || result) return;
    const text = query.trim();
    if (text.length < MIN_QUERY_LENGTH) {
      requestSeq.current += 1;
      setSuggestions([]);
      setSearchedFor(null);
      setSearching(false);
      return;
    }
    const timer = window.setTimeout(() => void runSearch(text), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query, open, result, runSearch]);

  async function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' && suggestions.length) {
      e.preventDefault();
      setHighlight((h) => (h + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp' && suggestions.length) {
      e.preventDefault();
      setHighlight((h) => (h - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const text = query.trim();
      if (text.length < MIN_QUERY_LENGTH) return;
      if (searchedFor === text && !searching && suggestions.length) {
        void choose(suggestions[Math.min(highlight, suggestions.length - 1)]);
        return;
      }
      const found = await runSearch(text);
      if (found && found.length === 1) void choose(found[0]);
    }
  }

  const trimmed = query.trim();
  const showEmpty = !searching && searchedFor === trimmed && trimmed.length >= MIN_QUERY_LENGTH && suggestions.length === 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Yuz tasdiqlangan vaqtni aniqlash"
      description={result ? undefined : "Odam ro'yxatdan o'tish sahifasida yuzini qaysi kuni, soat nechida tasdiqlagani."}
      size="lg"
      initialFocusRef={inputRef}
    >
      {!result && (
        <div className="flex flex-col gap-3 pb-2">
          <Input
            ref={inputRef}
            icon={Search}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ism, familiya yoki JSHSHIR — masalan: Karimova Dilnoza"
            aria-label="Ism, familiya yoki JSHSHIR"
            aria-autocomplete="list"
            aria-controls="biometrics-lookup-suggestions"
            autoComplete="off"
            size="lg"
            trailing={searching || loadingResult ? <Loader2 size={16} className="mr-1.5 animate-spin text-primary" aria-label="Qidirilmoqda" /> : undefined}
          />

          {error && <ErrorState title="Xatolik" message={error} />}

          {suggestions.length > 0 && (
            <ul id="biometrics-lookup-suggestions" role="listbox" className="max-h-80 overflow-y-auto rounded-card border border-border bg-surface p-1.5">
              {suggestions.map((person, index) => (
                <li key={person.id} role="option" aria-selected={index === highlight}>
                  <button
                    type="button"
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => void choose(person)}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-control px-3 py-2.5 text-left transition-colors',
                      index === highlight ? 'bg-primary-soft' : 'hover:bg-surface-2',
                      focusRing,
                    )}
                  >
                    <Avatar name={person.fullName} src={person.biometricPhotoUrl} size="md" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-fg">{person.fullName}</span>
                      <span className="block truncate text-xs text-muted">{describePerson(person)}</span>
                    </span>
                    <Badge tone={STATUS_TONE[person.biometricsStatus]} dot className="hidden sm:inline-flex">
                      {STATUS_LABEL[person.biometricsStatus]}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {suggestions.length > 1 && <p className="text-xs text-subtle">↑ ↓ — tanlash · Enter — aniqlash</p>}

          {showEmpty && <EmptyState icon={SearchX} compact title={`«${trimmed}» bo'yicha hech kim topilmadi`} />}
        </div>
      )}

      {result && <ConfirmationCard result={result} onBack={resetToSearch} />}
    </Modal>
  );
}

function ConfirmationCard({ result, onBack }: { result: BiometricsConfirmation; onBack: () => void }) {
  return (
    <div className="flex flex-col gap-4 pb-2">
      <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={onBack} className="-ml-2 w-fit">
        Boshqa odamni aniqlash
      </Button>

      <div className="flex items-center gap-3">
        <Avatar name={result.fullName} src={result.biometricPhotoUrl} size="lg" shape="square" />
        <div className="min-w-0">
          <p className="text-base font-semibold text-fg">{result.fullName}</p>
          <p className="text-xs text-muted">{describePerson(result)}</p>
        </div>
      </div>

      {result.confirmedTime && result.confirmedAt ? (
        <div className="rounded-card border border-success/25 bg-success-soft p-5">
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-success">
            <Clock size={13} aria-hidden="true" />
            Yuzini tasdiqlagan vaqti
          </p>
          <p className="mt-2 text-4xl font-semibold tabular-nums tracking-tight text-fg">{result.confirmedTime}</p>
          <p className="mt-1 text-sm font-medium text-fg">
            {result.confirmedDate}, {result.confirmedWeekday}
          </p>
          <p className="mt-1 text-xs text-muted">Toshkent vaqti (UTC+5) · {timeAgo(result.confirmedAt)}</p>
        </div>
      ) : result.source === 'nomalum' ? (
        <div className="rounded-card border border-warning/25 bg-warning-soft p-4 text-sm text-fg">
          Yuzi tasdiqlangan, lekin aniq vaqtni aniqlab bo&apos;lmadi: yuz rasmi omborda topilmadi.
        </div>
      ) : (
        <div className="rounded-card border border-border bg-surface-2 p-4">
          <p className="text-sm font-semibold text-fg">Hali yuzini tasdiqlamagan</p>
          <p className="mt-1 text-xs text-muted">
            Holati: {STATUS_LABEL[result.biometricsStatus]}. Odam https://cam.fermi.uz/royxatdan-otish sahifasida JSHSHIR bilan kirib, yuzini
            tasdiqlashi kerak.
          </p>
        </div>
      )}

      {result.source === 'rasm' && (
        <p className="text-xs leading-relaxed text-muted">
          Bu odam tasdiqlash vaqtini yozish funksiyasi qo&apos;shilishidan oldin tasdiqlagan — vaqt uning yuz rasmi saqlangan paytdan tiklandi.
          Rasm tasdiqlash so&apos;rovining o&apos;zida saqlanadi, shuning uchun vaqt aniq.
        </p>
      )}
    </div>
  );
}

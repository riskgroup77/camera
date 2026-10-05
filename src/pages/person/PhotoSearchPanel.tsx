import { useEffect, useRef, useState, type DragEvent } from 'react';
import { ImagePlus, Route, ScanFace, X } from 'lucide-react';
import { Avatar, Button, Card, DateRangePicker, EmptyState, ErrorState, IconButton, Skeleton, cn, rangeForPreset, type DateRangeValue } from '../../ui';
import { isAbortError } from '../../lib/apiClient';
import {
  clockTime,
  searchByPhoto,
  similarityPercent,
  type PhotoSearchResult,
} from '../../lib/personLocatorApi';
import type { RouteTarget } from './PersonRouteDrawer';

// Backend chegarasi (app/routers/person_locator.py) bilan bir xil —
// katta faylni yuklab, keyin rad javobini kutmaslik uchun.
const MAX_BYTES = 8 * 1024 * 1024;

function dayTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('uz-UZ', { day: '2-digit', month: 'short', timeZone: 'Asia/Tashkent' }).format(date) + ' ' + clockTime(iso);
}

export function PhotoSearchPanel({ onRoute }: { onRoute: (target: RouteTarget) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [range, setRange] = useState<DateRangeValue>(() => rangeForPreset('last7'));
  const [min, setMin] = useState(0.35);
  const [result, setResult] = useState<PhotoSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!file) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  function pick(next: File | undefined | null) {
    if (!next) return;
    if (!next.type.startsWith('image/')) { setError('Faqat rasm fayli'); return; }
    if (next.size > MAX_BYTES) { setError('Rasm 8 MB dan oshmasin'); return; }
    setError(null);
    setResult(null);
    setFile(next);
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    pick(event.dataTransfer.files?.[0]);
  }

  async function run() {
    if (!file) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      setResult(await searchByPhoto(file, { from: range.from, to: range.to, min }, controller.signal));
    } catch (err) {
      if (!isAbortError(err)) setError((err as Error).message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <Card padding="md" className="flex flex-col gap-3 sm:flex-row">
        <label
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'relative flex h-40 w-full shrink-0 cursor-pointer flex-col items-center justify-center gap-1 overflow-hidden rounded-card border-2 border-dashed text-[12px] text-muted transition-colors sm:w-40',
            dragging ? 'border-primary bg-primary-soft' : 'border-border hover:border-primary/60',
          )}
        >
          {preview ? (
            <img src={preview} alt="Qidirilayotgan yuz" className="h-full w-full object-cover" />
          ) : (
            <>
              <ImagePlus size={22} aria-hidden="true" />
              <span>Rasm tanlang</span>
            </>
          )}
          <input ref={inputRef} type="file" accept="image/*" className="sr-only" onChange={(event) => { pick(event.target.files?.[0]); event.target.value = ''; }} />
          {file && (
            <IconButton
              icon={X}
              label="Olib tashlash"
              size="sm"
              className="absolute right-1 top-1 bg-surface/90"
              onClick={(event) => { event.preventDefault(); setFile(null); setResult(null); }}
            />
          )}
        </label>
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <DateRangePicker value={range} onChange={setRange} presets={['today', 'last7', 'last30']} size="sm" />
          <label className="block text-[12px] font-medium text-muted">
            Kamida o‘xshashlik: <span className="font-semibold text-fg">{similarityPercent(min)}</span>
            <input
              type="range"
              min={25}
              max={80}
              step={5}
              value={Math.round(min * 100)}
              onChange={(event) => setMin(Number(event.target.value) / 100)}
              className="mt-1 w-full accent-primary"
            />
          </label>
          <Button icon={ScanFace} onClick={run} disabled={!file} loading={loading} className="self-start">Qidirish</Button>
        </div>
      </Card>

      {error && <ErrorState message={error} onRetry={file ? run : undefined} />}
      {!file && !result && !error && <EmptyState icon={ScanFace} title="Yuz rasmini yuklang" description="Rasmni shu yerga tashlang yoki tanlang" compact />}
      {loading && <div className="grid gap-2 sm:grid-cols-2"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>}

      {!loading && result && (
        <>
          <section className="flex flex-col gap-2">
            <h2 className="intel-micro !text-[11px]">Ro‘yxatdagilar · {result.people.length}</h2>
            {result.people.length === 0 ? (
              <p className="text-[12px] text-muted">Mos odam topilmadi</p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {result.people.map((person) => (
                  <Card key={person.id} padding="md" className="flex min-w-0 items-center gap-3">
                    <Avatar name={person.fullName} src={person.photoUrl} size="md" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14px] font-bold text-fg">{person.fullName}</p>
                      <p className="truncate text-[12px] text-muted">{person.groupOrPosition || (person.type === 'talaba' ? 'Talaba' : 'Xodim')}</p>
                      <p className="text-[11px] text-muted">{person.lastSeenAt ? dayTime(person.lastSeenAt) : 'Kamerada ko‘rilmagan'}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1.5">
                      <span className="intel-code text-[13px] font-bold text-primary">{similarityPercent(person.similarity)}</span>
                      <Button size="sm" variant="soft" icon={Route} onClick={() => onRoute(person)}>Yo‘li</Button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="intel-micro !text-[11px]">Notanish yuzlar · {result.sightings.length}</h2>
            {result.sightings.length === 0 ? (
              <p className="text-[12px] text-muted">Bu oraliqda topilmadi</p>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                {result.sightings.map((item) => {
                  return (
                    <Card key={item.id} padding="none" className="flex min-w-0 flex-col overflow-hidden">
                      <div className="relative aspect-square bg-surface-2">
                        {item.cropUrl
                          ? <img src={item.cropUrl} alt="" loading="lazy" className="h-full w-full object-cover" />
                          : <ScanFace size={28} className="absolute inset-0 m-auto text-subtle" aria-hidden="true" />}
                        <span className="intel-code absolute right-1 top-1 rounded bg-surface/90 px-1.5 text-[12px] font-bold text-primary">{similarityPercent(item.similarity)}</span>
                      </div>
                      <div className="flex flex-col gap-0.5 p-2">
                        <p className="truncate text-[12px] font-semibold text-fg">{item.cameraName ?? '—'}</p>
                        <p className="text-[11px] text-muted">{dayTime(item.firstSeenAt)}{item.hits > 1 ? ` · ${item.hits} marta` : ''}</p>
                      </div>
                    </Card>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

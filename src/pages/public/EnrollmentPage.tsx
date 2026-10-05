import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CheckCircle2, Clock, IdCard, RotateCcw, ScanFace, UserCheck, UserPlus } from 'lucide-react';
import EnrollmentConsent from '../../components/public/EnrollmentConsent';
import EnrollmentFaceCapture from '../../components/public/EnrollmentFaceCapture';
import EnrollmentRegisterForm from '../../components/public/EnrollmentRegisterForm';
import { Notice, Segmented } from '../../components/settings/kit';
import { Avatar, Button, CodeText, DocumentHeader, Field, Input, IntelPanel, MicroLabel, StatusLamp, cn, type IntelStatus } from '../../ui';
import { formNumber } from '../../components/public/formNumber';
import { ApiError } from '../../lib/apiClient';
import { branding } from '../../lib/branding';
import {
  type EnrollmentLookupResult,
  type EnrollmentRegisterInput,
  type EnrollmentIdentity,
  lookupPerson,
  registerSelf,
  submitEnrollment,
} from '../../lib/enrollment';

/** 'consent' — yuzni skanerlashdan oldin: biometrik ma'lumotni qayta
 *  ishlashga rozilik. Kamera faqat undan keyin yoqiladi. */
type Step = 'identify' | 'register' | 'confirm' | 'consent' | 'photo' | 'success';

/** Shaxsni aniqlash usuli.
 *
 *  JSHSHIR standart tanlov: institut kadrlar ro'yxati aynan shu raqam
 *  bilan yuritiladi va ommaviy kiritilgan xodimlarda pasport ma'lumoti
 *  umuman yo'q. Pasport yo'li ilgari shu tarzda ro'yxatdan o'tganlar
 *  uchun qoldirilgan. */
type Method = 'pinfl' | 'passport';

const METHOD_OPTIONS = [
  { value: 'pinfl' as const, label: 'JSHSHIR' },
  { value: 'passport' as const, label: 'Pasport' },
];

/** Bosqichlar ko'rsatkichi: odam telefonda qayerda turganini va nechta qadam qolganini ko'radi. */
const PROGRESS = ['Aniqlash', 'Tasdiqlash', 'Rozilik', 'Yuz'] as const;

/** JSHSHIR uzunligi — bitta joyda, chunki u uchta joyda ishlatiladi
 *  (yorliq, hisoblagich, tekshiruv) va ular bir-biriga zid bo'lib
 *  qolgan edi. */
const PINFL_LENGTH = 14;

function progressIndex(step: Step): number {
  switch (step) {
    case 'identify':
    case 'register':
      return 0;
    case 'confirm':
      return 1;
    case 'consent':
      return 2;
    case 'photo':
      return 3;
    case 'success':
      return PROGRESS.length;
  }
}

/**
 * Serverdan kelgan xatoni ochiq sahifada ko'rsatishga yaroqli holga
 * keltiradi.
 *
 * 422 — pydantic tekshiruvi: xabari doim ingliz tilida ("field
 * required", "value is not a valid integer") va butunlay o'zbekcha
 * sahifada odamni sarosimaga solardi. 5xx — "Internal Server Error".
 * Ikkala holda ham o'zimizning tushunarli matnimiz ko'rsatiladi;
 * qolgan xatolar (400/404/409) serverda ataylab o'zbekcha yozilgan va
 * aynan shundayligicha foydali.
 */
function userMessage(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback;
  if (err.status === 422 || err.status >= 500) return fallback;
  return err.message;
}

/** Bosqich holati — RANG emas, SO'Z: bajarilgan / joriy / navbatda. */
const STEP_STATE = { done: 'OK', active: 'JORIY', todo: 'NAVBAT' } as const;

function StepProgress({ current }: { current: number }) {
  return (
    <ol
      className="grid grid-cols-4 divide-x divide-border border-b border-border"
      aria-label="Ro'yxatdan o'tish bosqichlari"
    >
      {PROGRESS.map((label, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={label} className="min-w-0 px-2 py-1.5" aria-current={active ? 'step' : undefined}>
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className={cn('h-1.5 w-1.5 shrink-0 rounded-full', done ? 'bg-success' : active ? 'bg-primary' : 'bg-surface-3')}
              />
              <CodeText className="text-[10px] text-subtle">B{index + 1}</CodeText>
            </span>
            <span className={cn('mt-0.5 block truncate text-[12px] leading-4', active ? 'font-semibold text-fg' : done ? 'text-fg' : 'text-subtle')}>
              {label}
            </span>
            <MicroLabel className={cn('block truncate', done && '!text-success', active && '!text-primary')}>
              {done ? STEP_STATE.done : active ? STEP_STATE.active : STEP_STATE.todo}
            </MicroLabel>
          </li>
        );
      })}
      {/* Bosqich almashgani ekranni ko'rmaydigan foydalanuvchiga
          aytilsin: chiziqchalarning rangi o'zgargani unga hech narsa
          bildirmaydi, sahifa esa jimgina butunlay boshqa formaga
          almashadi. */}
      <li className="sr-only" aria-live="polite">
        {current < PROGRESS.length
          ? `${current + 1}-bosqich: ${PROGRESS[current]}`
          : 'Barcha bosqichlar bajarildi'}
      </li>
    </ol>
  );
}

export default function EnrollmentPage() {
  const [searchParams] = useSearchParams();
  // QR kartadan kelganda (?guruh=DI-2301) — guruh nomi eslatma sifatida ko'rsatiladi.
  const groupHint = (searchParams.get('guruh') ?? '').trim().slice(0, 60);
  const [step, setStep] = useState<Step>('identify');
  const [method, setMethod] = useState<Method>('pinfl');
  // Topilmadi: yozuvi yo'q odam shu tugma orqali o'zini qo'shadi.
  // Avval bu avtomatik bo'lardi, lekin endi "topilmadi" javobi
  // "kod noto'g'ri" bilan bir xil — ya'ni sababini faqat odamning
  // o'zi biladi va tanlovni ham o'zi qilishi kerak.
  const [notFound, setNotFound] = useState(false);
  const [pinfl, setPinfl] = useState('');
  const [series, setSeries] = useState('');
  const [number, setNumber] = useState('');
  const [found, setFound] = useState<EnrollmentLookupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [awaitingApproval, setAwaitingApproval] = useState(false);
  const [consent, setConsent] = useState(false);

  useEffect(() => {
    const previous = document.title;
    document.title = `Ro'yxatdan o'tish · ${branding.systemName}`;
    return () => {
      document.title = previous;
    };
  }, []);

  // Har yangi bosqichda sahifa tepasiga — telefonda oldingi forma pastda qolib ketmasin.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [step]);

  const identity: EnrollmentIdentity =
    method === 'pinfl' ? { kind: 'pinfl', pinfl } : { kind: 'passport', passportSeries: series, passportNumber: number };

  async function handleLookup(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotFound(false);
    setLoading(true);
    try {
      const result = await lookupPerson(identity);
      setFound(result);
      setStep('confirm');
    } catch (err) {
      // 404 — "topilmadi YOKI kod noto'g'ri". Server ataylab ikkisini
      // ajratmaydi: aks holda begona odam kodni to'g'ri topganini
      // javobdan bilib olardi. Shuning uchun bu yerda ham avtomatik
      // ravishda "o'zini qo'shish"ga o'tilmaydi — xabar ko'rsatiladi
      // va tanlov odamning o'ziga qoldiriladi.
      if (err instanceof ApiError && err.status === 404) {
        setError(err.message);
        setNotFound(true);
      } else {
        setError(userMessage(err, "So'rovni bajarib bo'lmadi. Internet aloqasini tekshirib, qayta urinib ko'ring."));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(input: EnrollmentRegisterInput) {
    setError(null);
    setLoading(true);
    try {
      const created = await registerSelf(input);
      setFound(created);
      setStep('confirm');
    } catch (err) {
      setError(userMessage(err, "Ro'yxatdan o'tkazib bo'lmadi. Ma'lumotlarni tekshirib, qayta urinib ko'ring."));
    } finally {
      setLoading(false);
    }
  }

  async function handleFramesSubmit(frames: Blob[]) {
    if (!found) return;
    setError(null);
    setCaptureError(null);
    setLoading(true);
    try {
      const result = await submitEnrollment(found.recordId, identity, frames, consent);
      setAwaitingApproval(Boolean(result.awaitingApproval));
      setStep('success');
    } catch (err) {
      // Xato bo'lsa kamera qadamida qolamiz va bosqichlar boshidan
      // boshlanadi. Server qaysi kadr o'tmaganini aytadi — bu xabar
      // komponentga uzatiladi, chunki "tekshiruvdan o'tmadingiz" degan
      // umumiy xabar odamni nima qilishni bilmay qoldirardi.
      setCaptureError(userMessage(err, "Yuzni saqlab bo'lmadi. Qayta urinib ko'ring."));
    } finally {
      setLoading(false);
    }
  }

  /** Birinchi bosqichga to'liq qaytish.
   *
   *  Rozilik va kamera qadamining holati ham tozalanadi: bu sahifa
   *  ommaviy va bitta telefondan navbatma-navbat bir necha kishi
   *  foydalanadi. Ilgari `consent` va `captureError` tozalanmasdi —
   *  ya'ni oldingi odam qo'ygan rozilik belgisi keyingisining
   *  so'roviga qo'shilib ketardi, ekranda esa unga aloqasi yo'q eski
   *  xato osilib turardi. */
  function restartIdentify() {
    setStep('identify');
    setFound(null);
    setError(null);
    setNotFound(false);
    setConsent(false);
    setCaptureError(null);
    setAwaitingApproval(false);
  }

  // JSHSHIR qat'iy 14 raqam. Ilgari bu yerda ham, maydonning
  // minLength'ida ham 13 turardi — natijada 13 raqamli (ya'ni bitta
  // raqami tushib qolgan) qiymat brauzer tekshiruvidan o'tib ketib,
  // serverdan "topilmadi" javobini olardi va odam sababini bilmasdi.
  const pinflShort = method === 'pinfl' && pinfl.length > 0 && pinfl.length < PINFL_LENGTH;

  const current = progressIndex(step);

  /** Blank raqami — forma HOLATIDAN hisoblanadi (vaqtdan yoki render
   *  sonidan emas): bitta telefonda bir xil bosqichda doim bir xil
   *  raqam chiqadi, shuning uchun odam uni dekanatga aytishi mumkin.
   *  JSHSHIR va pasport raqami raqamga QO'SHILMAYDI. */
  const reference = formNumber({
    kind: 'royxat',
    step: Math.min(current + 1, PROGRESS.length),
    of: PROGRESS.length,
    parts: [method, groupHint],
  });

  // Holat — rang emas, SO'Z.
  const lamp: { status: IntelStatus; label: string } =
    step === 'success'
      ? awaitingApproval
        ? { status: 'warn', label: 'Tasdiq kutilmoqda' }
        : { status: 'ok', label: 'Saqlandi' }
      : error || captureError
        ? { status: 'alert', label: 'Xato' }
        : loading
          ? { status: 'warn', label: 'Yuborilmoqda' }
          : { status: 'idle', label: "To'ldirilmoqda" };

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 pb-10">
      <DocumentHeader
        org={branding.orgName}
        title="Ro'yxatdan o'tish"
        reference={reference}
        readouts={[
          { label: 'Qamrov', value: 'Shaxsiy yozuv' },
          { label: 'Guruh', value: groupHint || '—' },
          { label: 'Usul', value: method === 'pinfl' ? 'JSHSHIR' : 'Pasport' },
          { label: 'Bosqich', value: `${Math.min(current + 1, PROGRESS.length)}/${PROGRESS.length}` },
        ]}
      />

      <IntelPanel title="Yuzni ro'yxatga olish" right={<StatusLamp status={lamp.status} label={lamp.label} pulse={loading} />}>
        <StepProgress current={current} />
        <div className="flex flex-col gap-4 p-4 [&_button]:min-h-11">
          {error && <Notice tone="danger">{error}</Notice>}
          {groupHint && step !== 'success' && (
            <Notice tone="info" title={`Guruh: ${groupHint}`}>
              {step === 'register'
                ? `«Guruh» maydoniga «${groupHint}» deb yozing.`
                : "Bu havola guruhingiz uchun berilgan. JSHSHIR yoki pasport ma'lumotlari bilan o'zingizni toping."}
            </Notice>
          )}

          {step === 'identify' && (
            <form onSubmit={handleLookup} className="flex flex-col gap-4">
              <div>
                <MicroLabel>Bosqich 1 — Aniqlash</MicroLabel>
                <h2 className="mt-0.5 text-[15px] font-semibold text-fg">Shaxsingizni aniqlaymiz</h2>
                <p className="mt-1 text-[13px] leading-relaxed text-muted">
                  Tizimdagi yozuvingizni topish uchun JSHSHIR raqamingizni kiriting. U pasportingizning ma&apos;lumot sahifasida, 14
                  raqamdan iborat.
                </p>
              </div>

              <Segmented
                ariaLabel="Aniqlash usuli"
                value={method}
                onChange={(value) => {
                  setMethod(value);
                  setError(null);
                }}
                options={METHOD_OPTIONS}
                size="lg"
              />

              {method === 'pinfl' ? (
                <Field
                  label={`JSHSHIR (${PINFL_LENGTH} raqam)`}
                  hint={`Kiritilgan: ${pinfl.length}/${PINFL_LENGTH} raqam`}
                  required
                >
                  <Input
                    value={pinfl}
                    onChange={(e) => setPinfl(e.target.value.replace(/\D/g, '').slice(0, PINFL_LENGTH))}
                    placeholder="30302654150047"
                    inputMode="numeric"
                    autoComplete="off"
                    required
                    // Birinchi maydon — kursor darhol shu yerda bo'lsin.
                    autoFocus
                    minLength={PINFL_LENGTH}
                    maxLength={PINFL_LENGTH}
                    size="lg"
                    invalid={pinflShort}
                    className="[&_input]:min-h-11 [&_input]:text-base [&_input]:font-mono [&_input]:tracking-wide [&_input::placeholder]:font-sans [&_input::placeholder]:tracking-normal"
                  />
                </Field>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  <Field label="Seriya" required>
                    <Input
                      value={series}
                      onChange={(e) => setSeries(e.target.value.toUpperCase())}
                      placeholder="AD"
                      maxLength={4}
                      autoComplete="off"
                      autoCapitalize="characters"
                      required
                      size="lg"
                      className="[&_input]:min-h-11 [&_input]:text-base [&_input]:uppercase"
                    />
                  </Field>
                  <Field label="Raqam" required className="col-span-2">
                    <Input
                      value={number}
                      onChange={(e) => setNumber(e.target.value.replace(/\D/g, ''))}
                      placeholder="1234567"
                      maxLength={10}
                      inputMode="numeric"
                      autoComplete="off"
                      required
                      size="lg"
                      className="[&_input]:min-h-11 [&_input]:text-base"
                    />
                  </Field>
                </div>
              )}

              <Button
                type="submit"
                variant="primary"
                size="lg"
                icon={IdCard}
                loading={loading}
                disabled={method === 'pinfl' ? pinfl.length !== PINFL_LENGTH : !series || !number}
                fullWidth
              >
                {loading ? 'Qidirilmoqda...' : 'Davom etish'}
              </Button>

              {notFound && (
                <Button
                  type="button"
                  variant="ghost"
                  icon={UserPlus}
                  onClick={() => {
                    setError(null);
                    setNotFound(false);
                    setStep('register');
                  }}
                  fullWidth
                >
                  Ro&apos;yxatda yo&apos;qman — o&apos;zimni qo&apos;shish
                </Button>
              )}
            </form>
          )}

          {step === 'confirm' && found && (
            <div className="flex flex-col gap-4">
              <div>
                <MicroLabel>Bosqich 2 — Tasdiqlash</MicroLabel>
                <h2 className="mt-0.5 text-[15px] font-semibold text-fg">Bu sizmi?</h2>
              </div>
              <div className="rounded-control border border-border">
                <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-3 py-1.5">
                  <MicroLabel>Topilgan yozuv</MicroLabel>
                  <span className="ms-auto">
                    <StatusLamp
                      status={found.alreadyEnrolled ? 'ok' : found.awaitingApproval ? 'warn' : 'idle'}
                      label={found.alreadyEnrolled ? "Ro'yxatda" : found.awaitingApproval ? 'Tasdiq kutilmoqda' : 'Yangi'}
                    />
                  </span>
                </div>
                <div className="flex items-center gap-3 p-3">
                  <Avatar name={found.fullName} size="md" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-fg">{found.fullName}</p>
                    <p className="text-[13px] text-muted">
                      {found.typeLabel} · {found.groupOrPosition}
                    </p>
                  </div>
                  <UserCheck size={20} className="shrink-0 text-success" aria-hidden="true" />
                </div>
                <div className="grid grid-cols-2 gap-x-4 border-t border-border px-3 py-2">
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <MicroLabel>Blank</MicroLabel>
                    <CodeText className="truncate text-[13px] font-semibold text-fg">{reference}</CodeText>
                  </span>
                </div>
              </div>

              {found.alreadyEnrolled ? (
                <Notice tone="warning">Siz allaqachon ro&apos;yxatdan o&apos;tgansiz. O&apos;zgartirish kerak bo&apos;lsa, administratorga murojaat qiling.</Notice>
              ) : found.awaitingApproval ? (
                <>
                  <Notice tone="warning" icon={Clock}>
                    Yuzingiz qabul qilingan va administrator tasdig&apos;ini kutmoqda. Rasmni almashtirmoqchi bo&apos;lsangiz, qayta skanerlashingiz
                    mumkin.
                  </Notice>
                  <Button size="lg" icon={ScanFace} onClick={() => setStep('consent')} fullWidth>
                    Qayta skanerlash
                  </Button>
                </>
              ) : (
                <>
                  <p className="text-sm text-muted">Bu siz ekanligingizni tasdiqlab, yuzingizni skanerlashga o&apos;ting.</p>
                  <Button variant="primary" size="lg" icon={ScanFace} onClick={() => setStep('consent')} fullWidth>
                    Ha, bu men — davom etish
                  </Button>
                </>
              )}
              <Button variant="ghost" icon={RotateCcw} onClick={restartIdentify} fullWidth>
                Boshqa ma&apos;lumot bilan qayta urinish
              </Button>
            </div>
          )}

          {step === 'register' && (
            <EnrollmentRegisterForm
              pinfl={method === 'pinfl' ? pinfl : undefined}
              passportSeries={method === 'passport' ? series : undefined}
              passportNumber={method === 'passport' ? number : undefined}
              initialGroup={groupHint}
              onSubmit={handleRegister}
              onCancel={restartIdentify}
              submitting={loading}
            />
          )}

          {step === 'consent' && (
            <EnrollmentConsent
              onContinue={(agreed) => {
                setConsent(agreed);
                setCaptureError(null);
                setStep('photo');
              }}
              onBack={() => setStep('confirm')}
            />
          )}

          {step === 'photo' && <EnrollmentFaceCapture onSubmit={handleFramesSubmit} submitting={loading} externalError={captureError} />}

          {step === 'success' && found && (
            <div className="flex flex-col gap-3 py-2" role="status">
              <div className="flex items-center gap-3">
                <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-control border', awaitingApproval ? 'border-warning/35 bg-warning-soft text-warning' : 'border-success/35 bg-success-soft text-success')}>
                  {awaitingApproval ? <Clock size={18} aria-hidden="true" /> : <CheckCircle2 size={18} aria-hidden="true" />}
                </span>
                <div className="min-w-0">
                  <StatusLamp
                    status={awaitingApproval ? 'warn' : 'ok'}
                    label={awaitingApproval ? 'Tasdiq kutilmoqda' : 'Saqlandi'}
                  />
                  <p className="mt-0.5 text-[15px] font-semibold text-fg">
                    {awaitingApproval ? 'Qabul qilindi' : "Muvaffaqiyatli saqlandi"}
                  </p>
                </div>
              </div>
              <div className="border-y border-border py-2">
                <span className="flex min-w-0 flex-col gap-0.5">
                  <MicroLabel>Blank</MicroLabel>
                  <CodeText className="truncate text-[13px] font-semibold text-fg">{reference}</CodeText>
                </span>
              </div>
              <p className="text-[13px] leading-relaxed text-muted">
                {awaitingApproval
                  ? `${found.fullName}, ma'lumotlaringiz qabul qilindi. Administrator tekshirib tasdiqlagandan keyin kameralar sizni taniy boshlaydi (odatda bir ish kuni ichida).`
                  : `${found.fullName}, yuzingiz endi kameralar orqali tanib olinadi.`}
              </p>
            </div>
          )}
          </div>
      </IntelPanel>

      <p className="px-1 text-[12px] leading-relaxed text-subtle">
        Kameralar sizni tanishi va davomat avtomatik belgilanishi uchun. Ma&apos;lumotlaringiz faqat davomat va bino
        xavfsizligi uchun ishlatiladi; rozilikni istalgan vaqtda qaytarib olishingiz mumkin.
      </p>
    </div>
  );
}

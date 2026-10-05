import { useEffect, useState } from 'react';
import { ArrowLeft, UserPlus } from 'lucide-react';
import { Button, CodeText, Field, Input, MicroLabel, Select, StatusLamp } from '../../ui';
import { Notice, Segmented } from '../settings/kit';
import {
  type EnrollmentFaculty,
  type EnrollmentGroup,
  type EnrollmentRegisterInput,
  type EnrollmentUnit,
  listEnrollmentFaculties,
  listEnrollmentGroups,
  listEnrollmentUnits,
} from '../../lib/enrollment';

interface EnrollmentRegisterFormProps {
  /** Qidiruvda kiritilgan identifikator — qayta so'ralmaydi. */
  pinfl?: string;
  passportSeries?: string;
  passportNumber?: string;
  /** Guruh QR kartasidan kelganda (?guruh=) — maydon oldindan to'ldiriladi. */
  initialGroup?: string;
  onSubmit: (input: EnrollmentRegisterInput) => void;
  onCancel: () => void;
  submitting?: boolean;
}

const TYPE_OPTIONS = [
  { value: 'talaba' as const, label: 'Talaba' },
  { value: 'xodim' as const, label: 'Xodim' },
];

/**
 * Tizimda yozuvi yo'q odam uchun ro'yxatdan o'tish formasi.
 *
 * Ilgari pasport topilmasa jarayon shu yerda tugardi — "yozuv topilmadi"
 * degan xato chiqib, odam administratorni kutishi kerak edi. Endi u
 * o'zini o'zi kiritadi va darhol yuzini yuklashga o'tadi.
 *
 * Pasport qayta so'ralmaydi: u allaqachon qidiruvda kiritilgan va aynan
 * o'sha qiymatlar bilan yozuv yaratiladi. Qayta terish faqat xato
 * kiritish ehtimolini oshirardi.
 */
export default function EnrollmentRegisterForm({
  pinfl,
  passportSeries,
  passportNumber,
  initialGroup = '',
  onSubmit,
  onCancel,
  submitting = false,
}: EnrollmentRegisterFormProps) {
  const [fullName, setFullName] = useState('');
  const [type, setType] = useState<'talaba' | 'xodim'>('talaba');
  const [groupOrPosition, setGroupOrPosition] = useState(initialGroup);
  const [facultyId, setFacultyId] = useState('');
  const [faculties, setFaculties] = useState<EnrollmentFaculty[]>([]);
  const [groups, setGroups] = useState<EnrollmentGroup[]>([]);
  const [units, setUnits] = useState<EnrollmentUnit[]>([]);
  const [orgUnitId, setOrgUnitId] = useState('');

  // HEMIS guruh va bo'linmalari — maslahat sifatida (ro'yxat yuklanmasa ham forma ishlaydi).
  useEffect(() => {
    let cancelled = false;
    listEnrollmentGroups()
      .then((rows) => !cancelled && setGroups(rows))
      .catch(() => undefined);
    listEnrollmentUnits()
      .then((rows) => !cancelled && setUnits(rows))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Fakultet ro'yxati bo'lmasa ham forma ishlayveradi — maydon
  // ixtiyoriy, va ro'yxatni yuklab bo'lmagani odamning ro'yxatdan
  // o'tishiga to'sqinlik qilmasligi kerak.
  useEffect(() => {
    let cancelled = false;
    listEnrollmentFaculties()
      .then((rows) => {
        if (!cancelled) setFaculties(rows);
      })
      .catch(() => {
        /* ixtiyoriy maydon — ro'yxatsiz davom etamiz */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Telefonda 16px dan kichik shrift iOS'da maydonni kattalashtirib yuboradi.
  const mobileText = '[&_input]:min-h-11 [&_input]:text-base';

  // Brauzerning `required` va `minLength` tekshiruvi bo'sh joylarni ham
  // belgi deb sanaydi: " a " uzunligi 3 bo'lgani uchun o'tib ketardi,
  // qirqilgandan keyin esa serverga bir harflik ism borardi. Shuning
  // uchun tekshiruv qirqilgan qiymat bo'yicha, tugmada.
  const trimmedName = fullName.trim();
  const trimmedGroup = groupOrPosition.trim();
  const valid = trimmedName.length >= 3 && trimmedGroup.length > 0;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        onSubmit({
          fullName: trimmedName,
          type,
          groupOrPosition: trimmedGroup,
          facultyId: facultyId || undefined,
          orgUnitId: type === 'xodim' ? orgUnitId || undefined : undefined,
          pinfl,
          passportSeries,
          passportNumber,
        });
      }}
      className="flex flex-col gap-4"
    >
      <div>
        <MicroLabel>Bosqich 1 — Yangi yozuv</MicroLabel>
        <h2 className="mt-0.5 text-[15px] font-semibold text-fg">Ma&apos;lumotlaringizni kiriting</h2>
        <Notice tone="warning" className="mt-2">
          Bu raqam bo&apos;yicha tizimda yozuv topilmadi. Ma&apos;lumotlaringizni kiriting — ro&apos;yxatdan o&apos;tkazamiz.
        </Notice>
      </div>

      <Field label="F.I.SH." required>
        <Input
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="Familiya Ism Sharif"
          autoComplete="name"
          required
          minLength={3}
          size="lg"
          className={mobileText}
        />
      </Field>

      <fieldset className="flex flex-col gap-1.5">
        <legend className="intel-micro mb-1.5 !text-fg">Kim sifatida</legend>
        <Segmented
          ariaLabel="Kim sifatida"
          value={type}
          onChange={(next) => {
            setType(next);
            // QR dagi guruh nomi xodimga lavozim bo'lib o'tib ketmasin.
            if (next === 'xodim' && groupOrPosition === initialGroup) setGroupOrPosition('');
          }}
          options={TYPE_OPTIONS}
          size="lg"
        />
      </fieldset>

      <Field label={type === 'talaba' ? 'Guruh' : 'Lavozim'} required>
        <Input
          value={groupOrPosition}
          onChange={(e) => setGroupOrPosition(e.target.value)}
          placeholder={type === 'talaba' ? 'Guruh nomini yozing, ro‘yxatdan tanlang' : 'Laborant'}
          list={type === 'talaba' && groups.length ? 'enroll-groups' : undefined}
          autoComplete="off"
          required
          size="lg"
          className={mobileText}
        />
      </Field>
      {type === 'talaba' && groups.length > 0 && (
        <datalist id="enroll-groups">
          {groups
            .filter((g) => !facultyId || g.facultyId === facultyId)
            .map((g) => (
              <option key={g.name} value={g.name}>{`${g.course}-kurs`}</option>
            ))}
        </datalist>
      )}

      {type === 'xodim' && units.length > 0 && (
        <Field label={<>Kafedra yoki bo‘lim <span className="font-normal text-muted">(ixtiyoriy)</span></>}>
          <Select
            value={orgUnitId}
            onChange={setOrgUnitId}
            placeholder="Tanlanmagan"
            options={units.map((u) => ({ value: u.id, label: u.name }))}
            size="lg"
            className="sm:!w-full [&_select]:min-h-11 [&_select]:text-base"
          />
        </Field>
      )}

      {faculties.length > 0 && (
        <Field label={<>Fakultet <span className="font-normal text-muted">(ixtiyoriy)</span></>}>
          <Select
            value={facultyId}
            onChange={setFacultyId}
            placeholder="Tanlanmagan"
            options={faculties.map((f) => ({ value: f.id, label: f.name }))}
            size="lg"
            className="sm:!w-full [&_select]:min-h-11 [&_select]:text-base"
          />
        </Field>
      )}

      {/* Qidiruvda kiritilgan identifikator — rekvizit satri sifatida
          ko'rinib turadi, chunki yozuv aynan shu raqam bilan yaratiladi. */}
      <div className="flex items-center gap-3 rounded-control border border-border bg-surface-2 px-3 py-2">
        <span className="flex min-w-0 flex-col gap-0.5">
          <MicroLabel>{pinfl ? 'JSHSHIR' : 'Pasport'}</MicroLabel>
          <CodeText className="truncate text-[13px] font-semibold text-fg">
            {pinfl || `${passportSeries} ${passportNumber}`}
          </CodeText>
        </span>
        <span className="ms-auto shrink-0">
          <StatusLamp
            status={submitting ? 'warn' : valid ? 'idle' : 'alert'}
            label={submitting ? 'Yuborilmoqda' : valid ? 'Tayyor' : "To'ldirilmagan"}
            pulse={submitting}
          />
        </span>
      </div>

      <Button type="submit" variant="primary" size="lg" icon={UserPlus} loading={submitting} disabled={!valid} fullWidth>
        {submitting ? 'Saqlanmoqda...' : "Ro'yxatdan o'tish"}
      </Button>

      {/* So'rov ketayotganda orqaga qaytish yozuv yaratilishini
          to'xtatmaydi — faqat odam natijani ko'rmay qoladi. */}
      <Button variant="ghost" icon={ArrowLeft} onClick={onCancel} disabled={submitting} fullWidth>
        Boshqa raqam bilan qayta urinish
      </Button>
    </form>
  );
}

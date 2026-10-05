import { useCallback, useEffect, useState } from 'react';
import { Pencil, Plus, Send, Trash2 } from 'lucide-react';
import { Button, ConfirmDialog, Field, IconButton, Input, Modal, Select, Textarea, useToast } from '../../ui';
import { Switch } from '../settings/kit';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { formatLogTime } from '../../lib/notificationsApi';
import {
  SCHEDULE_KIND_OPTIONS,
  SCHEDULE_REPORT_OPTIONS,
  parseChatIds,
  reportSchedulesApi,
  scheduleLabel,
  type ReportSchedule,
  type ScheduleKind,
  type ScheduleReport,
} from '../../lib/kpiApi';

/**
 * Avtomatik yuborish: har dushanba yoki har oyning 1-sanasida 08:00 dan
 * keyin o'tgan davr hisoboti Telegram'ga Excel fayl bo'lib boradi.
 * Faqat "Bildirishnomalar" huquqi borlarga ochiladi.
 */

interface Draft {
  id: string | null;
  name: string;
  kind: ScheduleKind;
  report: ScheduleReport;
  chats: string;
  enabled: boolean;
}

const EMPTY: Draft = { id: null, name: '', kind: 'haftalik', report: 'kpi', chats: '', enabled: true };

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export default function ReportSchedulesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { token } = useAuth();
  const toast = useToast();
  const [rows, setRows] = useState<ReportSchedule[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState<string | null>(null);
  const [removing, setRemoving] = useState<ReportSchedule | null>(null);

  const load = useCallback(() => {
    setLoadError(null);
    reportSchedulesApi
      .list(token)
      .then(setRows)
      .catch((err) => setLoadError(errorText(err, 'Ro‘yxat yuklanmadi')));
  }, [token]);

  useEffect(() => {
    if (open) load();
    else setDraft(null);
  }, [open, load]);

  async function save() {
    if (!draft) return;
    const { ids, error } = parseChatIds(draft.chats);
    if (!draft.name.trim()) return setFormError('Nom kiriting');
    if (error) return setFormError(error);
    setSaving(true);
    setFormError(null);
    const body = { name: draft.name.trim(), kind: draft.kind, report: draft.report, telegramChatIds: ids, enabled: draft.enabled };
    try {
      if (draft.id) await reportSchedulesApi.update(draft.id, body, token);
      else await reportSchedulesApi.create(body, token);
      setDraft(null);
      load();
    } catch (err) {
      setFormError(errorText(err, 'Saqlanmadi'));
    } finally {
      setSaving(false);
    }
  }

  async function toggle(row: ReportSchedule, enabled: boolean) {
    try {
      const updated = await reportSchedulesApi.update(row.id, { enabled }, token);
      setRows((prev) => prev?.map((r) => (r.id === row.id ? updated : r)) ?? null);
    } catch (err) {
      toast.error(errorText(err, 'Saqlanmadi'));
    }
  }

  async function sendNow(row: ReportSchedule) {
    setSending(row.id);
    try {
      const res = await reportSchedulesApi.sendNow(row.id, token);
      if (res.failed === 0) toast.success(`Yuborildi: ${res.sent} ta chat`);
      else toast.error(`Yuborildi ${res.sent}, xato ${res.failed}: ${res.errors[0] ?? ''}`);
    } catch (err) {
      toast.error(errorText(err, 'Yuborilmadi'));
    } finally {
      setSending(null);
    }
  }

  const edit = (row: ReportSchedule) => {
    setFormError(null);
    setDraft({ id: row.id, name: row.name, kind: row.kind, report: row.report,
      chats: row.telegramChatIds.join('\n'), enabled: row.enabled });
  };

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title="Avtomatik yuborish"
        description="Telegram‘ga Excel: haftalik — dushanba, oylik — 1-sana, 08:00."
        size="lg"
        dismissible={!draft}
      >
        {draft ? (
          <div className="flex flex-col gap-3">
            <Field label="Nomi" required>
              <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} maxLength={120} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Davriylik">
                <Select value={draft.kind} options={SCHEDULE_KIND_OPTIONS}
                  onChange={(kind) => setDraft({ ...draft, kind: kind as ScheduleKind })} className="sm:w-full" />
              </Field>
              <Field label="Hisobot">
                <Select value={draft.report} options={SCHEDULE_REPORT_OPTIONS}
                  onChange={(report) => setDraft({ ...draft, report: report as ScheduleReport })} className="sm:w-full" />
              </Field>
            </div>
            <Field label="Telegram chat ID" hint="Har qatorga bitta; bot /chatid buyrug‘i bilan beradi" error={formError}>
              <Textarea rows={3} value={draft.chats} onChange={(e) => setDraft({ ...draft, chats: e.target.value })} />
            </Field>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-[13px]">
                <Switch checked={draft.enabled} onChange={(enabled) => setDraft({ ...draft, enabled })} label="Yoqilgan" />
                Yoqilgan
              </span>
              <span className="flex gap-2">
                <Button variant="ghost" onClick={() => setDraft(null)} disabled={saving}>Bekor</Button>
                <Button variant="primary" onClick={save} loading={saving}>Saqlash</Button>
              </span>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {loadError && <p role="alert" className="text-[13px] text-danger">{loadError}</p>}
            {rows === null && !loadError && <p className="text-[13px] text-subtle">Yuklanmoqda…</p>}
            {rows?.length === 0 && <p className="text-[13px] text-subtle">Hali yo‘q</p>}
            {rows && rows.length > 0 && (
              <ul className="flex flex-col divide-y divide-border border border-border">
                {rows.map((row) => (
                  <li key={row.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
                    <Switch checked={row.enabled} onChange={(v) => void toggle(row, v)} label={`${row.name}: yoqilgan`} />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-[13px] font-medium">{row.name}</span>
                      <span className="truncate text-[12px] text-subtle">
                        {scheduleLabel(row)} · {row.telegramChatIds.length} chat
                        {row.lastSentAt ? ` · oxirgi: ${formatLogTime(row.lastSentAt).slice(0, 16)}` : ''}
                      </span>
                    </span>
                    <Button size="sm" variant="secondary" icon={Send} loading={sending === row.id}
                      onClick={() => void sendNow(row)}>
                      Sinov
                    </Button>
                    <IconButton icon={Pencil} label="Tahrirlash" size="sm" onClick={() => edit(row)} />
                    <IconButton icon={Trash2} label="O‘chirish" size="sm" onClick={() => setRemoving(row)} />
                  </li>
                ))}
              </ul>
            )}
            <div>
              <Button variant="soft" icon={Plus} onClick={() => { setFormError(null); setDraft({ ...EMPTY }); }}>
                Qo‘shish
              </Button>
            </div>
          </div>
        )}
      </Modal>
      <ConfirmDialog
        open={removing !== null}
        title="O‘chirilsinmi?"
        message={removing?.name}
        confirmLabel="O‘chirish"
        tone="danger"
        onCancel={() => setRemoving(null)}
        onConfirm={async () => {
          if (!removing) return;
          await reportSchedulesApi.remove(removing.id, token);
          setRemoving(null);
          load();
        }}
      />
    </>
  );
}

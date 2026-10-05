import { useCallback, useEffect, useState } from 'react';
import { Link2, ListTree, Pencil, PlugZap, Plus, Trash2 } from 'lucide-react';
import {
  Button,
  CodeText,
  ConfirmDialog,
  DataTable,
  Drawer,
  IconButton,
  IntelPanel,
  MicroLabel,
  StatusLamp,
  useToast,
  type DataTableColumn,
} from '../../ui';
import { Notice } from '../settings/kit';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { videoAnalysisApi, type Nvr, type NvrChannel, type NvrInput } from '../../lib/videoAnalysisApi';
import NvrModal from './NvrModal';

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** NVR qurilmalari va kanallarni kameralarga bog'lash (systemSettings). */
export default function NvrTab({ mappedCameras, activeCameras }: { mappedCameras: number; activeCameras: number }) {
  const { token } = useAuth();
  const toast = useToast();
  const [nvrs, setNvrs] = useState<Nvr[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Nvr | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [deleting, setDeleting] = useState<Nvr | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [channelsOf, setChannelsOf] = useState<Nvr | null>(null);
  const [channels, setChannels] = useState<NvrChannel[] | null>(null);
  const [channelsError, setChannelsError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setNvrs(await videoAnalysisApi.nvrs(token));
      setError(null);
    } catch (err) {
      setError(errorText(err, "NVR ro'yxatini yuklab bo'lmadi"));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadChannels = useCallback(
    async (nvr: Nvr) => {
      setChannels(null);
      setChannelsError(null);
      try {
        setChannels(await videoAnalysisApi.channels(nvr.id, token));
      } catch (err) {
        setChannelsError(errorText(err, "Kanallarni olib bo'lmadi"));
      }
    },
    [token],
  );

  async function save(body: NvrInput) {
    if (editing) {
      await videoAnalysisApi.updateNvr(editing.id, body, token);
      toast.success('NVR saqlandi');
    } else {
      await videoAnalysisApi.createNvr(body, token);
      toast.success("NVR qo'shildi");
    }
    setModalOpen(false);
    await load();
  }

  async function test(nvr: Nvr) {
    setBusyId(nvr.id);
    try {
      const result = await videoAnalysisApi.testNvr(nvr.id, token);
      if (result.ok) toast.success(result.model ? `${result.message} (${result.model})` : result.message);
      else toast.error(result.message);
      await load();
    } catch (err) {
      toast.error(errorText(err, "Tekshirib bo'lmadi"));
    } finally {
      setBusyId(null);
    }
  }

  async function autoMap(nvr: Nvr) {
    setBusyId(nvr.id);
    try {
      const result = await videoAnalysisApi.autoMap(nvr.id, token);
      const rest = result.unmatchedChannels.length ? `, ${result.unmatchedChannels.length} ta kanal topilmadi` : '';
      toast.success(`${result.mapped} ta kamera bog'landi${rest}`);
      await load();
      if (channelsOf?.id === nvr.id) await loadChannels(nvr);
    } catch (err) {
      toast.error(errorText(err, "Bog'lab bo'lmadi"));
    } finally {
      setBusyId(null);
    }
  }

  async function remove() {
    if (!deleting) return;
    await videoAnalysisApi.deleteNvr(deleting.id, token);
    toast.success("NVR o'chirildi");
    setDeleting(null);
    await load();
  }

  const columns: DataTableColumn<Nvr>[] = [
    {
      key: 'name',
      header: 'NVR',
      cell: (n) => (
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-fg">{n.name}</p>
          <CodeText className="text-[12px] text-muted">{n.kind === 'fayl' ? n.basePath : `${n.ip}:${n.httpPort}`}</CodeText>
        </div>
      ),
    },
    {
      key: 'state',
      header: 'Holat',
      cell: (n) =>
        !n.enabled ? (
          <StatusLamp status="idle" label="O'chirilgan" />
        ) : n.lastError ? (
          <span title={n.lastError}>
            <StatusLamp status="alert" label="Xato" />
          </span>
        ) : n.lastCheckAt ? (
          <StatusLamp status="ok" label={`${n.channelCount ?? 0} kanal`} />
        ) : (
          <StatusLamp status="warn" label="Tekshirilmagan" />
        ),
    },
    { key: 'cameras', header: 'Kameralar', align: 'right', cell: (n) => n.cameras },
    {
      key: 'mode',
      header: 'Olish',
      hideOnMobile: true,
      cell: (n) => <MicroLabel>{n.kind === 'fayl' ? 'papka' : `${n.fetchMode} · ${n.stream} · ${n.maxStreams} oqim`}</MicroLabel>,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      mobileLabel: 'Amallar',
      cell: (n) => (
        <div onClick={(e) => e.stopPropagation()} className="flex justify-end gap-1">
          <IconButton icon={PlugZap} label={`${n.name}: ulanishni tekshirish`} size="sm" disabled={busyId === n.id} onClick={() => void test(n)} />
          <IconButton
            icon={ListTree}
            label={`${n.name}: kanallar`}
            size="sm"
            onClick={() => {
              setChannelsOf(n);
              void loadChannels(n);
            }}
          />
          <IconButton icon={Link2} label={`${n.name}: kameralarga bog'lash`} size="sm" disabled={busyId === n.id} onClick={() => void autoMap(n)} />
          <IconButton
            icon={Pencil}
            label={`${n.name}: tahrirlash`}
            size="sm"
            onClick={() => {
              setEditing(n);
              setModalOpen(true);
            }}
          />
          <IconButton icon={Trash2} label={`${n.name}: o'chirish`} size="sm" variant="danger" onClick={() => setDeleting(n)} />
        </div>
      ),
    },
  ];

  const channelColumns: DataTableColumn<NvrChannel>[] = [
    { key: 'channel', header: 'Kanal', align: 'right', cell: (c) => c.channel },
    {
      key: 'name',
      header: 'NVR dagi nomi',
      cell: (c) => (
        <div className="min-w-0">
          <p className="truncate text-[13px] text-fg">{c.name}</p>
          {c.ip && <CodeText className="text-[12px] text-muted">{c.ip}</CodeText>}
        </div>
      ),
    },
    {
      key: 'online',
      header: 'Holat',
      cell: (c) => (c.online === null ? <span className="text-muted">—</span> : <StatusLamp status={c.online ? 'ok' : 'alert'} label={c.online ? 'onlayn' : 'oflayn'} />),
    },
    {
      key: 'camera',
      header: 'Tizimdagi kamera',
      cell: (c) => (c.cameraName ? <span className="text-[13px] text-fg">{c.cameraName}</span> : <span className="text-[12px] text-warning">bog'lanmagan</span>),
    },
  ];

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Notice tone={mappedCameras === 0 ? 'warning' : 'info'}>
        {mappedCameras === 0
          ? "Hali birorta kamera NVR kanaliga bog'lanmagan — kunlik tahlil video ololmaydi. NVR qo'shing va «Kameralarga bog'lash» tugmasini bosing (IP manzil bo'yicha avtomatik)."
          : `${mappedCameras} / ${activeCameras} ta faol kamera NVR kanaliga bog'langan. Bog'lanmagan kameralar tahlilga kirmaydi.`}
      </Notice>
      <IntelPanel
        title="NVR qurilmalari"
        right={
          <Button
            size="sm"
            variant="primary"
            icon={Plus}
            onClick={() => {
              setEditing(null);
              setModalOpen(true);
            }}
          >
            NVR
          </Button>
        }
      >
        <DataTable
          columns={columns}
          rows={nvrs}
          rowKey={(n) => n.id}
          loading={loading && nvrs.length === 0}
          loadingRows={2}
          error={error}
          onRetry={() => void load()}
          emptyTitle="NVR qo'shilmagan"
          emptyDescription="Kameralar yozuvini saqlovchi NVR (yoki eksport papkasi) qo'shing."
          ariaLabel="NVR qurilmalari"
          maxHeight="none"
          dense
        />
      </IntelPanel>

      <NvrModal open={modalOpen} nvr={editing} onClose={() => setModalOpen(false)} onSubmit={save} />
      <ConfirmDialog
        open={!!deleting}
        title="NVR ni o'chirish"
        message={`"${deleting?.name ?? ''}" o'chiriladi va unga bog'langan kameralar tahlildan chiqadi. Avvalgi natijalar saqlanadi.`}
        confirmLabel="O'chirish"
        onCancel={() => setDeleting(null)}
        onConfirm={remove}
      />
      <Drawer
        open={channelsOf !== null}
        onClose={() => setChannelsOf(null)}
        title={channelsOf ? `${channelsOf.name} — kanallar` : 'Kanallar'}
      >
        {channelsError ? (
          <Notice tone="danger">{channelsError}</Notice>
        ) : (
          <DataTable
            columns={channelColumns}
            rows={channels ?? []}
            rowKey={(c) => String(c.channel)}
            loading={channels === null}
            emptyTitle="Kanal topilmadi"
            ariaLabel="NVR kanallari"
            maxHeight="none"
            dense
          />
        )}
      </Drawer>
    </div>
  );
}

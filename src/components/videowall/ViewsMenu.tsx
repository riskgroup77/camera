import { useId, useRef, useState } from 'react';
import { Check, Download, ExternalLink, LayoutGrid, Pencil, Save, Trash2, Upload, X } from 'lucide-react';
import { Button, IconButton, Input, cn } from '../../ui';
import { LAYOUT_LABELS, MAX_VIEW_NAME, isViewNameTaken, type WallView } from '../../lib/videoWall';
import { isForeignShared, type ViewMetaMap } from '../../lib/wallViewsApi';
import WallPopover from './WallPopover';

/** "Ko'rinishlar" — nomlangan setkalar (serverda, ish joylari bilan
 * umumiy; server yo'q bo'lsa shu brauzerda): tez
 * almashtirish, joriy holatni saqlash/yangilash, nomini o'zgartirish,
 * o'chirish, JSON eksport/import va alohida oynada ochish. */
export default function ViewsMenu({
  views,
  meta = {},
  remote = false,
  activeViewId,
  dirty,
  onApply,
  onSaveNew,
  onUpdate,
  onRename,
  onDelete,
  onExport,
  onImport,
  onOpenWindow,
  align = 'right',
}: {
  views: WallView[];
  /** Serverdan: kimniki, tahrirlash mumkinmi (bo'lmasa — o'ziniki). */
  meta?: ViewMetaMap;
  /** Ko'rinishlar serverda saqlanadimi. */
  remote?: boolean;
  activeViewId: string | null;
  /** Joriy devor faol ko'rinishdan farq qiladimi. */
  dirty: boolean;
  onApply: (view: WallView) => void;
  onSaveNew: (name: string) => void;
  onUpdate: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onExport: () => void;
  onImport: (file: File) => void;
  onOpenWindow: (id: string) => void;
  align?: 'left' | 'right';
}) {
  const [newName, setNewName] = useState('');
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const inputId = useId();
  const active = views.find((view) => view.id === activeViewId) ?? null;

  const newNameError = newName.trim() && isViewNameTaken(views, newName) ? 'Bu nom band' : null;
  const editError = editing && editing.name.trim() && isViewNameTaken(views, editing.name, editing.id) ? 'Bu nom band' : null;

  return (
    <WallPopover
      icon={<LayoutGrid size={16} aria-hidden="true" />}
      label={
        <span className="max-w-[10rem] truncate">
          {active ? active.name : "Ko'rinishlar"}
          {active && dirty ? ' •' : ''}
        </span>
      }
      title="Saqlangan ko'rinishlar"
      align={align}
      widthClass="w-[22rem]"
    >
      {(close) => (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold">Ko&apos;rinishlar</p>
            <span className="text-xs text-muted">{remote ? 'serverda saqlanadi' : 'shu brauzerda saqlanadi'}</span>
          </div>

          {views.length === 0 ? (
            <p className="rounded-control border border-dashed border-border-strong/70 px-3 py-4 text-center text-[13px] text-muted">
              Hali saqlangan ko&apos;rinish yo&apos;q. Devorni to&apos;ldirib, pastda nom bering.
            </p>
          ) : (
            <ul className="-mx-1 max-h-72 space-y-0.5 overflow-y-auto px-1">
              {views.map((view, index) => {
                const filled = view.tiles.filter(Boolean).length;
                const isActive = view.id === activeViewId;
                const info = meta[view.id];
                const foreign = isForeignShared(info);
                const editable = info?.canEdit !== false;
                if (editing?.id === view.id) {
                  return (
                    <li key={view.id}>
                      <form
                        className="flex items-center gap-1 rounded-control bg-surface-2 p-1"
                        onSubmit={(event) => {
                          event.preventDefault();
                          if (!editing.name.trim() || editError) return;
                          onRename(view.id, editing.name.trim());
                          setEditing(null);
                        }}
                      >
                        <Input
                          size="sm"
                          autoFocus
                          value={editing.name}
                          maxLength={MAX_VIEW_NAME}
                          onChange={(event) => setEditing({ id: view.id, name: event.target.value })}
                          aria-label="Yangi nom"
                          invalid={Boolean(editError)}
                          className="min-w-0 flex-1"
                        />
                        <IconButton type="submit" icon={Check} label="Saqlash" size="sm" disabled={!!editError} />
                        <IconButton icon={X} label="Bekor qilish" size="sm" onClick={() => setEditing(null)} />
                      </form>
                      {editError && <p className="px-1 pt-0.5 text-xs text-warning">{editError}</p>}
                    </li>
                  );
                }
                return (
                  <li
                    key={view.id}
                    className={cn('group flex items-center gap-1 rounded-control px-1 py-0.5', isActive ? 'bg-primary-soft' : 'hover:bg-surface-2')}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        onApply(view);
                        close();
                      }}
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-[6px] px-1.5 py-1 text-left"
                    >
                      <span className="w-4 shrink-0 text-xs tabular-nums text-subtle">{index + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className={cn('truncate text-[13px] font-medium', isActive ? 'text-primary' : 'text-fg')}>{view.name}</span>
                          {foreign && (
                            <span
                              className="shrink-0 rounded-full bg-surface-2 px-1.5 text-[11px] leading-4 text-muted"
                              title={info?.ownerName ? `${info.ownerName} ulashgan` : 'Boshqa operator ulashgan'}
                            >
                              umumiy
                            </span>
                          )}
                        </span>
                        <span className="block text-xs text-muted">
                          {LAYOUT_LABELS[view.layout]} katak · {filled} ta kamera
                        </span>
                      </span>
                    </button>
                    {confirmDelete === view.id ? (
                      <span className="flex items-center gap-1">
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => {
                            onDelete(view.id);
                            setConfirmDelete(null);
                          }}
                        >
                          O&apos;chirish
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                          Yo&apos;q
                        </Button>
                      </span>
                    ) : (
                      <span className="flex shrink-0 items-center opacity-70 group-hover:opacity-100">
                        <IconButton icon={ExternalLink} size="sm" label="Yangi oynada ochish" title="Yangi oynada ochish (ikkinchi monitor)" onClick={() => onOpenWindow(view.id)} />
                        {editable && (
                          <>
                            <IconButton icon={Pencil} size="sm" label="Nomini o'zgartirish" onClick={() => setEditing({ id: view.id, name: view.name })} />
                            <IconButton icon={Trash2} size="sm" variant="danger" label="O'chirish" onClick={() => setConfirmDelete(view.id)} />
                          </>
                        )}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {active && dirty && meta[active.id]?.canEdit !== false && (
            <Button variant="soft" size="sm" icon={Save} fullWidth onClick={() => onUpdate(active.id)}>
              «{active.name}» ni joriy devor bilan yangilash
            </Button>
          )}

          <form
            className="space-y-1.5 border-t border-border pt-3"
            onSubmit={(event) => {
              event.preventDefault();
              const name = newName.trim();
              if (!name || newNameError) return;
              onSaveNew(name);
              setNewName('');
            }}
          >
            <label className="text-[13px] font-medium text-fg" htmlFor={inputId}>
              Joriy devorni yangi ko&apos;rinish sifatida saqlash
            </label>
            <div className="flex gap-1.5">
              <Input
                id={inputId}
                size="sm"
                value={newName}
                maxLength={MAX_VIEW_NAME}
                onChange={(event) => setNewName(event.target.value)}
                placeholder="Masalan: 1-bino kirishlari"
                invalid={Boolean(newNameError)}
                className="min-w-0 flex-1"
              />
              <Button type="submit" variant="primary" size="sm" icon={Save} disabled={!newName.trim() || !!newNameError}>
                Saqlash
              </Button>
            </div>
            {newNameError && <p className="text-xs text-warning">{newNameError}</p>}
          </form>

          <div className="flex gap-1.5">
            <Button size="sm" icon={Download} onClick={onExport} disabled={views.length === 0} className="flex-1">
              Eksport (JSON)
            </Button>
            <Button size="sm" icon={Upload} onClick={() => fileInput.current?.click()} className="flex-1">
              Import
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) onImport(file);
              }}
            />
          </div>
        </div>
      )}
    </WallPopover>
  );
}

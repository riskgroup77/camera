/** Dizayn tizimi — barcha yangi sahifalar faqat shu yerdan import qiladi.
 *  Namunalar: /sozlamalar/ui (uslub qo'llanmasi, faqat super-admin). */

export { cn, focusRing, controlBase } from './cn';
export { TONE_SOFT, TONE_SOLID, TONE_TEXT, TONE_BORDER, TONE_RING, DEFAULT_RATE_THRESHOLDS, toneForRate } from './tones';
export type { Tone, RateThresholds } from './tones';
export { ATTENDANCE_STATUS, EVENT_STATUS, SEVERITY, attendanceMeta } from './status';
export type { AttendanceStatus, EventStatusKey, SeverityKey } from './status';
export { initials, formatNumber, formatPercent } from './text';
export { ThemeProvider } from './theme';
export { useTheme } from './themeContext';
export type { ThemeName } from './themeContext';

export { Button, ButtonLink } from './Button';
export type { ButtonProps, ButtonLinkProps } from './Button';
export { buttonClasses } from './buttonStyles';
export type { ButtonVariant, ButtonSize } from './buttonStyles';
export { IconButton } from './IconButton';
export type { IconButtonProps } from './IconButton';
export { Card, CardHeader } from './Card';
export type { CardProps, CardHeaderProps } from './Card';
export { Section } from './Section';
export { KeyValue } from './KeyValue';
export type { KeyValueItem } from './KeyValue';

export { Page } from './Page';
export type { PageProps } from './Page';
export { useShell } from './pageContext';
export type { Crumb } from './pageContext';
export { Tabs } from './Tabs';
export type { TabsProps } from './Tabs';
export { useUrlTab, resolveTab } from './urlTab';
export type { TabItem } from './urlTab';

export { StatTile } from './StatTile';
export type { StatTileProps, StatDelta } from './StatTile';
export { ProgressRing, ProgressBar } from './Progress';
export type { ProgressRingProps, ProgressBarProps, ProgressSegment } from './Progress';
export { Badge, StatusBadge, StatusDot } from './Badge';
export type { BadgeProps } from './Badge';
export { Avatar } from './Avatar';
export type { AvatarProps, AvatarSize } from './Avatar';
export { PersonCard, PersonGrid } from './PersonCard';
export type { PersonCardProps } from './PersonCard';

export { DataTable } from './DataTable';
export type { DataTableColumn, DataTableProps } from './DataTable';
export { rag, ragHint, RATE_RAG, LATE_RAG, RAG_LETTER, RAG_LABEL, RAG_TEXT, RAG_FILL, RAG_SOLID } from './rag';
export type { Rag, RagThresholds } from './rag';
export { sortRows, compareValues, nextSort } from './tableSort';
export type { SortState, SortDir, SortValue } from './tableSort';

export { Toolbar, FilterBar } from './Toolbar';
export type { ToolbarProps, FilterBarProps } from './Toolbar';
export { filterActiveCount, isFilterActive, resetFilterFields, presentFilterFields } from './filterFields';
export type { FilterField, FilterFieldEntry } from './filterFields';
export { SearchInput } from './SearchInput';
export type { SearchInputProps } from './SearchInput';
export { Select } from './Select';
export type { SelectProps, SelectOption } from './Select';
export { Input, Textarea, Field } from './Input';
export type { InputProps, FieldProps } from './Input';
export { DatePicker } from './DatePicker';
export type { DatePickerProps } from './DatePicker';
export { DateRangePicker } from './DateRangePicker';
export type { DateRangePickerProps } from './DateRangePicker';
export { formatUzDate, formatUzRange, relativeDayLabel, isIsoDate, rangeForPreset, detectPreset, RANGE_PRESET_LABELS } from './dates';
export type { DateRangeValue, RangePreset } from './dates';

export { Drawer } from './Drawer';
export type { DrawerProps } from './Drawer';
export { Modal } from './Modal';
export type { ModalProps } from './Modal';
export { ConfirmDialog } from './ConfirmDialog';
export type { ConfirmDialogProps } from './ConfirmDialog';
export { Menu } from './Menu';
export type { MenuEntry, MenuProps } from './Menu';

export { EmptyState } from './EmptyState';
export type { EmptyStateProps } from './EmptyState';
export { ErrorState } from './ErrorState';
export type { ErrorStateProps } from './ErrorState';
export { Skeleton, SkeletonText, SkeletonTiles, SkeletonCard, SkeletonCards, SkeletonTable, PageSkeleton } from './Skeleton';
export { ToastProvider, useToast } from './Toast';

export { useChartTheme, readChartTheme, readToken } from './chartTheme';
export type { ChartTheme } from './chartTheme';

export { CountUp } from './CountUp';
export { parseDisplayNumber, formatLike } from './numberTween';
export { Sparkline } from './Sparkline';
export type { SparklineProps } from './Sparkline';

export { topDialogPanel } from './internal/useDialog';

// Operatsiya markazi uslubi — hisobot va kamera ekranlari uchun.
export {
  MicroLabel,
  CodeText,
  Readout,
  StatusLamp,
  IntelPanel,
  DocumentHeader,
  DocumentFooter,
} from './intel';
export type { IntelStatus } from './intel';

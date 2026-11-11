import { useId, useState } from 'react'
import type {
  ButtonHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import * as Tooltip from '@radix-ui/react-tooltip'
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import type { ColumnDef, SortingState } from '@tanstack/react-table'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Inbox,
  Info,
  LoaderCircle,
  Search,
  Unplug,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import { initials, stageIndex, workflowStages } from '../lib/format'
import type { IncidentStatus } from '../types'

export function Button({
  variant = 'secondary',
  className,
  children,
  busy,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  busy?: boolean
}) {
  return (
    <button
      type="button"
      className={clsx('button', `button-${variant}`, className)}
      {...props}
      disabled={props.disabled || busy}
    >
      {busy && <LoaderCircle size={16} className="spin" />}
      {children}
    </button>
  )
}

export function IconButton({
  label,
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          aria-label={label}
          className={clsx('icon-button', className)}
          {...props}
        >
          {children}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip" sideOffset={7}>
          {label}
          <Tooltip.Arrow />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

export function Badge({
  children,
  tone,
  dot = true,
}: {
  children: ReactNode
  tone?: 'critical' | 'neutral' | 'success' | 'warning' | 'outline'
  dot?: boolean
}) {
  const inferred = /critical|error|failed|breached|rejected/i.test(
    String(children)
  )
    ? 'critical'
    : /waiting|pending|degraded|high|investigating|paused|inferred|unverified/i.test(
      String(children)
    )
      ? 'warning'
      : /passed|healthy|completed|approved|resolved|validated/i.test(
        String(children)
      )
        ? 'success'
        : 'neutral'
  return (
    <span className={clsx('badge', `badge-${tone ?? inferred}`)}>
      {dot && <span className="badge-dot" />}
      {children}
    </span>
  )
}

export function Avatar({
  name,
  small = false,
}: {
  name: string
  small?: boolean
}) {
  return (
    <span className={clsx('avatar', small && 'avatar-small')} title={name}>
      {initials(name)}
    </span>
  )
}

export function PageHeader({
  title,
  eyebrow,
  description,
  actions,
}: {
  title: string
  eyebrow?: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

/** Kyndryl Bridge-style wordmark: the product name followed by red "kyndryl". */
export function BrandMark() {
  return (
    <span className="brand-mark">
      <span className="brand-product">behave</span>{' '}
      <span className="brand-kyndryl">kyndryl</span>
    </span>
  )
}

export function SectionHeader({
  title,
  caption,
  actions,
  icon: Icon,
}: {
  title: string
  caption?: string
  actions?: ReactNode
  icon?: LucideIcon
}) {
  return (
    <div className="section-header">
      <div>
        <h2>
          {Icon && <Icon size={18} />}
          {title}
        </h2>
        {caption && <p>{caption}</p>}
      </div>
      {actions && <div className="section-actions">{actions}</div>}
    </div>
  )
}

export function Metric({
  label,
  value,
  detail,
  icon: Icon,
  critical = false,
  trend,
  onClick,
}: {
  label: string
  value: ReactNode
  detail: string
  icon: LucideIcon
  critical?: boolean
  trend?: number[]
  onClick?: () => void
}) {
  const contents = (
    <>
      <div className="metric-label">
        {label}
        <Icon size={17} />
      </div>
      <div className="metric-main">
        <strong className={critical ? 'metric-critical' : ''}>{value}</strong>
        {trend && (
          <div
            className={clsx('spark-bars', critical && 'spark-red')}
            aria-hidden="true"
          >
            {trend.map((height, index) => (
              <i key={index} style={{ height: `${height}%` }} />
            ))}
          </div>
        )}
      </div>
      <div className="metric-detail">
        {detail}
        {onClick && <ArrowUpRight size={14} />}
      </div>
    </>
  )
  return onClick ? (
    <button className="metric" onClick={onClick}>
      {contents}
    </button>
  ) : (
    <div className="metric">{contents}</div>
  )
}

export function Select({
  label,
  children,
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return (
    <label className={clsx('select-wrap', className)}>
      <span className="sr-only">{label}</span>
      <select {...props} aria-label={label}>
        {children}
      </select>
    </label>
  )
}

export function SearchInput({
  value,
  onChange,
  placeholder = 'Search records',
  label,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  label?: string
}) {
  return (
    <label className="search-input">
      <Search size={16} />
      <span className="sr-only">{label ?? placeholder}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      {value && (
        <button aria-label="Clear search" onClick={() => onChange('')}>
          <X size={14} />
        </button>
      )}
    </label>
  )
}

export function Tabs({
  items,
  value,
  onChange,
}: {
  items: (string | { label: string; value: string; count?: number })[]
  value: string
  onChange: (value: string) => void
}) {
  const id = useId()
  const options = items.map((item) =>
    typeof item === 'string'
      ? { label: item, value: item, count: undefined }
      : item
  )
  return (
    <div className="tabs" role="tablist" aria-label="Workspace views">
      {options.map((item, index) => (
        <button
          key={item.value}
          id={`${id}-${index}`}
          role="tab"
          type="button"
          aria-selected={value === item.value}
          tabIndex={value === item.value ? 0 : -1}
          className={clsx(value === item.value && 'active')}
          onClick={() => onChange(item.value)}
          onKeyDown={(event) => {
            if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key))
              return
            event.preventDefault()
            const next =
              event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? options.length - 1
                  : (index +
                    (event.key === 'ArrowRight' ? 1 : -1) +
                    options.length) %
                  options.length
            onChange(options[next].value)
            document.getElementById(`${id}-${next}`)?.focus()
          }}
        >
          {item.label}
          {item.count !== undefined && (
            <span className="tab-count">{item.count}</span>
          )}
        </button>
      ))}
    </div>
  )
}

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
  wide?: boolean
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(value) => !value && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content
          className={clsx('modal', wide && 'modal-wide')}
          onOpenAutoFocus={(event) => {
            if (!open) event.preventDefault()
          }}
        >
          <div className="modal-heading">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              <Dialog.Description
                className={description ? 'modal-description' : 'sr-only'}
              >
                {description ?? title}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button className="icon-button" aria-label="Close dialog">
                <X size={19} />
              </button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(value) => !value && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay drawer-overlay" />
        <Dialog.Content className="drawer">
          <div className="modal-heading">
            <div>
              <Dialog.Description className="eyebrow">
                {subtitle ?? 'Record detail'}
              </Dialog.Description>
              <Dialog.Title>{title}</Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <button className="icon-button" aria-label="Close inspector">
                <X size={19} />
              </button>
            </Dialog.Close>
          </div>
          <div className="drawer-body">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function EmptyState({
  title = 'No matching records',
  description = 'No records match the current filters.',
  action,
  icon: Icon = Inbox,
}: {
  title?: string
  description?: string
  action?: ReactNode
  icon?: LucideIcon
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon size={26} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function Notice({
  title,
  children,
  tone = 'info',
  action,
}: {
  title: string
  children?: ReactNode
  tone?: 'info' | 'warning' | 'error'
  action?: ReactNode
}) {
  const Icon =
    tone === 'error' ? CircleAlert : tone === 'warning' ? Unplug : Info
  return (
    <div className={clsx('notice', `notice-${tone}`)}>
      <Icon size={18} />
      <div>
        <strong>{title}</strong>
        {children && <p>{children}</p>}
      </div>
      {action}
    </div>
  )
}

export function LoadingState() {
  return (
    <div
      className="loading-workspace"
      aria-label="Loading workspace"
      role="status"
    >
      <div className="loading-brand">
        <BrandMark />
      </div>
      <LoaderCircle className="spin" size={24} />
      <div className="skeleton-grid">
        {[1, 2, 3, 4].map((item) => (
          <div key={item} className="skeleton" />
        ))}
      </div>
      <p>Loading workspace records</p>
    </div>
  )
}

export function KeyValue({
  label,
  children,
  mono = false,
}: {
  label: string
  children: ReactNode
  mono?: boolean
}) {
  return (
    <div className="key-value">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : ''}>{children}</dd>
    </div>
  )
}

export function WorkflowSteps({ status }: { status: IncidentStatus }) {
  const active = stageIndex(status)
  return (
    <ol className="workflow-steps" aria-label="Incident lifecycle">
      {workflowStages.map((stage, index) => (
        <li
          key={stage}
          className={clsx(
            index < active && 'complete',
            index === active && 'current'
          )}
          aria-current={index === active ? 'step' : undefined}
        >
          <span>{index < active ? <Check size={12} /> : index + 1}</span>
          <div>{stage}</div>
        </li>
      ))}
    </ol>
  )
}

export function DataTable<RecordType>({
  data,
  columns,
  onRowClick,
  searchPlaceholder = 'Search records',
  toolbar,
  pageSize = 6,
  initialSorting = [],
  searchable = true,
  emptyTitle,
  emptyDescription,
}: {
  data: RecordType[]
  columns: ColumnDef<RecordType, any>[]
  onRowClick?: (record: RecordType) => void
  searchPlaceholder?: string
  toolbar?: ReactNode
  pageSize?: number
  initialSorting?: SortingState
  searchable?: boolean
  emptyTitle?: string
  emptyDescription?: string
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting)
  const [search, setSearch] = useState('')
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize })
  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: search, pagination },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    autoResetPageIndex: false,
  })
  const filteredCount = table.getFilteredRowModel().rows.length
  const pageCount = Math.max(1, table.getPageCount())
  const effectivePage = Math.min(pagination.pageIndex, pageCount - 1)
  if (effectivePage !== pagination.pageIndex)
    setPagination({ ...pagination, pageIndex: effectivePage })
  return (
    <div className="data-table">
      {(searchable || toolbar) && (
        <div className="table-toolbar">
          {searchable && (
            <SearchInput
              value={search}
              onChange={(value) => {
                setSearch(value)
                table.setPageIndex(0)
              }}
              placeholder={searchPlaceholder}
            />
          )}
          {toolbar && <div className="table-filters">{toolbar}</div>}
        </div>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th
                    key={header.id}
                    aria-sort={
                      header.column.getIsSorted() === 'asc'
                        ? 'ascending'
                        : header.column.getIsSorted() === 'desc'
                          ? 'descending'
                          : undefined
                    }
                  >
                    {header.isPlaceholder ? null : header.column.getCanSort() ? (
                      <button
                        className="sort-button"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                        {header.column.getIsSorted() === 'asc' ? (
                          <ArrowUp size={12} />
                        ) : header.column.getIsSorted() === 'desc' ? (
                          <ArrowDown size={12} />
                        ) : (
                          <ArrowUpDown size={12} />
                        )}
                      </button>
                    ) : (
                      flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={onRowClick ? 'clickable-row' : ''}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={() => onRowClick?.(row.original)}
                onKeyDown={(event) => {
                  if (
                    onRowClick &&
                    event.target === event.currentTarget &&
                    (event.key === 'Enter' || event.key === ' ')
                  ) {
                    event.preventDefault()
                    onRowClick(row.original)
                  }
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!filteredCount && (
          <EmptyState title={emptyTitle} description={emptyDescription} />
        )}
      </div>
      <div className="table-footer">
        <span>
          {filteredCount
            ? `${effectivePage * pagination.pageSize + 1}-${Math.min((effectivePage + 1) * pagination.pageSize, filteredCount)} of ${filteredCount}`
            : '0 records'}
        </span>
        <div>
          <Select
            label="Rows per page"
            value={pagination.pageSize}
            onChange={(event) => {
              table.setPageSize(Number(event.target.value))
              table.setPageIndex(0)
            }}
          >
            {[6, 12, 24, 50].map((size) => (
              <option key={size} value={size}>
                {size} / page
              </option>
            ))}
          </Select>
          <IconButton
            label="Previous page"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
          >
            <ChevronLeft size={16} />
          </IconButton>
          <span className="page-counter">
            {effectivePage + 1} / {pageCount}
          </span>
          <IconButton
            label="Next page"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
          >
            <ChevronRight size={16} />
          </IconButton>
        </div>
      </div>
    </div>
  )
}

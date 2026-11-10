import { pctColor, shortDate, typeColor, typeLabel } from '../format'

// Pieces shared by every card: header, "why" line, market line, footer.

export function TypePill({ type }) {
  return (
    <span className={'rounded-full px-2 py-0.5 text-[11px] font-semibold ' + typeColor(type)}>
      {typeLabel(type)}
    </span>
  )
}

export function CardHeader({ event, label, onOpen }) {
  return (
    <button onClick={() => onOpen(event.id)} className="flex w-full items-start justify-between gap-3 text-left">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-base font-bold tracking-tight">{event.symbol}</span>
          <TypePill type={event.type} />
        </div>
        <div className="truncate text-xs text-slate-500 dark:text-slate-400">
          {event.name}
          {label ? ' · ' + label : ''}
        </div>
      </div>
      <span className="shrink-0 text-xs text-slate-400">{shortDate(event.end)}</span>
    </button>
  )
}

export function WhyLine({ reason }) {
  if (!reason) return null
  return (
    <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">
      <span className="font-semibold text-slate-900 dark:text-white">Why it's here: </span>
      {reason}
    </p>
  )
}

export function MarketLine({ market }) {
  if (!market) return null
  return (
    <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
      <span className="font-semibold text-slate-900 dark:text-white">Market: </span>
      <span className={'tabular font-semibold ' + pctColor(market.pct_change)}>
        {market.pct_change > 0 ? '+' : ''}
        {market.pct_change}%
      </span>
      {market.volume_alert ? ' on ' + market.volume_ratio + '× volume' : ''}
      {' · ' + shortDate(market.date)}
    </p>
  )
}

export function CardFooter({ event, pdfUrl, onOpen }) {
  const count = event.filings ? event.filings.length : 0
  return (
    <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2 text-xs dark:border-slate-800">
      <button onClick={() => onOpen(event.id)} className="font-medium text-sky-700 dark:text-sky-400">
        {count > 1 ? count + ' filings · details' : 'Details'} →
      </button>
      {pdfUrl && (
        <a href={pdfUrl} target="_blank" rel="noreferrer" className="text-slate-500 underline-offset-2 hover:underline">
          Source PDF ↗
        </a>
      )}
    </div>
  )
}

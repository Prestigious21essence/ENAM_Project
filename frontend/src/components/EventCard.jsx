import { shortDate } from '../format'
import MgmtCard from './MgmtCard'
import ResultsCard from './ResultsCard'
import { CardFooter, CardHeader, MarketLine, TypePill, WhyLine } from './parts'

// Picks the right card for an event
export function BigCard({ event, onOpen }) {
  if (event.card_type === 'results' && event.card && event.card.rows) {
    return <ResultsCard event={event} onOpen={onOpen} />
  }
  if (event.card_type === 'management' && event.card && event.card.changes) {
    return <MgmtCard event={event} onOpen={onOpen} />
  }
  return <EventCard event={event} onOpen={onOpen} />
}

// Generic card for M&A, legal, fund raise, ...
export function EventCard({ event, onOpen }) {
  let pdfUrl = null
  if (event.filings && event.filings.length > 0) {
    pdfUrl = event.filings[event.filings.length - 1].pdf_url
  }
  return (
    <article className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <CardHeader event={event} onOpen={onOpen} />
      <p className="mt-2 text-[15px] leading-snug">{stripCount(event.headline)}</p>
      <WhyLine reason={event.reason} />
      <MarketLine market={event.market} />
      <CardFooter event={event} pdfUrl={pdfUrl} onOpen={onOpen} />
    </article>
  )
}

// One-line row for the "worth a look" list
export function EventRow({ event, onOpen }) {
  return (
    <button onClick={() => onOpen(event.id)} className="flex w-full items-start gap-3 py-3 text-left">
      <div className="w-16 shrink-0">
        <div className="text-sm font-bold">{event.symbol}</div>
        <div className="text-[11px] text-slate-400">{shortDate(event.end)}</div>
      </div>
      <div className="min-w-0 flex-1">
        <TypePill type={event.type} />
        <p className="mt-1 line-clamp-2 text-sm leading-snug text-slate-700 dark:text-slate-300">{stripCount(event.headline)}</p>
      </div>
    </button>
  )
}

// "... (4 filings)" is shown in the footer instead
export function stripCount(headline) {
  return (headline || '').replace(/ \(\d+ filings\)$/, '')
}

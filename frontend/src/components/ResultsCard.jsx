import { crore, pctColor, quarterLabel, signedPct } from '../format'
import { CardFooter, CardHeader, MarketLine, WhyLine } from './parts'

// Short labels so 4 tiles fit on a phone
const SHORT_NAMES = {
  'Net interest income': 'NII',
  'Operating profit': 'Op. profit',
}

function MetricTile({ row }) {
  const label = SHORT_NAMES[row.metric] || row.metric
  return (
    <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/60">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className={'tabular mt-0.5 text-lg font-semibold leading-tight ' + (row.unverified ? 'text-slate-400' : '')}>
        ₹{crore(row.value_cr)}
        <span className="ml-0.5 text-xs font-normal text-slate-500"> cr</span>
        {row.unverified && <span className="ml-1 text-[10px] font-medium text-amber-600">unverified</span>}
      </div>
      <div className="tabular mt-1 flex gap-3 text-xs">
        <span className={pctColor(row.yoy_pct)}>{signedPct(row.yoy_pct)} <span className="text-slate-400">YoY</span></span>
        <span className={pctColor(row.qoq_pct)}>{signedPct(row.qoq_pct)} <span className="text-slate-400">QoQ</span></span>
      </div>
    </div>
  )
}

export default function ResultsCard({ event, onOpen }) {
  const card = event.card
  const quarter = quarterLabel(card.periods && card.periods[0])
  const isBank = card.type === 'bank'
  return (
    <article className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <CardHeader event={event} label={quarter + ' results'} onOpen={onOpen} />
      <div className="mt-3 grid grid-cols-2 gap-2">
        {card.rows.map((row) => (
          <MetricTile key={row.metric} row={row} />
        ))}
      </div>
      {isBank && (
        <p className="mt-2 text-[11px] text-slate-500">Bank: net interest income and pre-provision operating profit, standalone.</p>
      )}
      {card.note && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{card.note}</p>}
      {card.warning && (
        <p className="mt-2 rounded-lg bg-amber-50 px-2 py-1.5 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">⚠ {card.warning}</p>
      )}
      <WhyLine reason={event.reason} />
      <MarketLine market={event.market} />
      <CardFooter event={event} pdfUrl={card.pdf_url} onOpen={onOpen} />
    </article>
  )
}

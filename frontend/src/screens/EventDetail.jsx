import { useEffect, useState } from 'react'
import { getEvent } from '../api'
import { BigCard } from '../components/EventCard'
import { pctColor, shortDate, typeLabel } from '../format'
import { ErrorBox, Loading, SectionTitle } from './Today'

export default function EventDetail({ id, onBack, onOpen }) {
  const [event, setEvent] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setEvent(null)
    setError(null)
    getEvent(id).then(setEvent).catch((e) => setError(e.message))
    window.scrollTo(0, 0)
  }, [id])

  let cardEvent = null
  if (event) {
    // the card components expect the digest shape: one biggest "market" move
    let biggest = null
    for (const move of event.market_moves) {
      if (move.price_alert && (biggest === null || Math.abs(move.pct_change) > Math.abs(biggest.pct_change))) biggest = move
    }
    cardEvent = { ...event, market: biggest }
  }

  return (
    <div className="pb-8">
      <div className="sticky top-0 z-10 bg-slate-100/90 px-4 py-3 backdrop-blur dark:bg-slate-950/90">
        <button onClick={onBack} className="text-sm font-medium text-sky-700 dark:text-sky-400">← Back</button>
      </div>
      {error && <ErrorBox message={error} />}
      {!event && !error && <Loading />}
      {event && (
        <div className="space-y-6 px-4">
          <BigCard event={cardEvent} onOpen={onOpen} />

          {/* push meets pull: from the filing to the company's track record */}
          <a
            href={'#/research/' + encodeURIComponent(event.symbol)}
            className="flex items-center justify-between rounded-2xl bg-sky-50 px-4 py-3 text-sm ring-1 ring-sky-200 dark:bg-sky-950 dark:ring-sky-900"
          >
            <span>
              <span className="font-semibold text-sky-900 dark:text-sky-100">Research {event.symbol} →</span>
              <span className="block text-xs text-sky-800/80 dark:text-sky-200/80">Promised vs delivered, numbers, transcripts</span>
            </span>
            <span className="text-sky-700 dark:text-sky-300">⌕</span>
          </a>

          {event.market_moves.length > 0 && (
            <section>
              <SectionTitle>Market around these filings</SectionTitle>
              <div className="divide-y divide-slate-100 rounded-2xl bg-white ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
                {event.market_moves.map((move) => (
                  <div key={move.date} className="flex justify-between px-4 py-2.5 text-sm">
                    <span className="text-slate-500">{shortDate(move.date)}</span>
                    <span className="tabular">
                      <span className={move.price_alert ? 'font-semibold ' + pctColor(move.pct_change) : 'text-slate-500'}>
                        {move.pct_change > 0 ? '+' : ''}
                        {move.pct_change}%
                      </span>
                      <span className={'ml-3 ' + (move.volume_alert ? 'font-semibold text-amber-600 dark:text-amber-400' : 'text-slate-400')}>
                        {move.volume_ratio}× vol
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <SectionTitle>Filings ({event.filings.length})</SectionTitle>
            <ol className="relative space-y-4 border-l border-slate-200 pl-4 dark:border-slate-800">
              {event.filings
                .slice()
                .reverse()
                .map((filing) => (
                  <li key={filing.id}>
                    <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-slate-300 dark:bg-slate-700" />
                    <div className="text-xs text-slate-400">
                      {shortDate(filing.datetime)} {filing.datetime.slice(11)} · {typeLabel(filing.category)}
                    </div>
                    <div className="text-sm font-medium">{filing.subject}</div>
                    <p className="mt-0.5 text-sm leading-snug text-slate-600 dark:text-slate-300">{filing.summary || filing.details}</p>
                    {filing.pdf_url && (
                      <a href={filing.pdf_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-sky-700 dark:text-sky-400">
                        Open filing ↗
                      </a>
                    )}
                  </li>
                ))}
            </ol>
          </section>
        </div>
      )}
    </div>
  )
}

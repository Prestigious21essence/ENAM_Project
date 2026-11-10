import { useEffect, useState } from 'react'
import { getDigest } from '../api'
import { BigCard, EventRow, stripCount } from '../components/EventCard'
import { shortDate, typeLabel } from '../format'

// The morning brief: the few things that matter as full cards, the rest collapsed.
const WINDOWS = [
  { label: '24 h', hours: 24 },
  { label: '3 days', hours: 72 },
  { label: '7 days', hours: 168 },
  { label: 'Season', hours: 45 * 24 },
]
const MEDIUM_PREVIEW = 4

function greeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

function todayText() {
  return new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })
}

export default function Today({ onOpen }) {
  const [hours, setHours] = useState(24)
  const [digest, setDigest] = useState(null)
  const [highlights, setHighlights] = useState([])   // shown on quiet days
  const [error, setError] = useState(null)
  const [showAllMedium, setShowAllMedium] = useState(false)
  const [showRoutine, setShowRoutine] = useState(false)

  useEffect(() => {
    let cancelled = false
    setDigest(null)
    setError(null)
    setShowAllMedium(false)
    setShowRoutine(false)
    getDigest(hours)
      .then((data) => {
        if (cancelled) return
        setDigest(data)
        // Quiet day: nothing high in the window -> show the last important things of the week
        if (data.high.length === 0 && hours < 168) {
          getDigest(168).then((week) => {
            if (!cancelled) setHighlights(week.high.slice(0, 3))
          })
        } else {
          setHighlights([])
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [hours])

  return (
    <div>
      <header className="px-4 pt-6 pb-3">
        <div className="text-xs font-semibold tracking-[0.2em] text-sky-700 dark:text-sky-400">FINN</div>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">{greeting()}</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">{todayText()}</p>
      </header>

      <div className="no-scrollbar flex gap-2 overflow-x-auto px-4 pb-3">
        {WINDOWS.map((w) => (
          <button
            key={w.hours}
            onClick={() => setHours(w.hours)}
            className={
              'shrink-0 rounded-full px-3.5 py-1.5 text-sm font-medium ' +
              (hours === w.hours
                ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                : 'bg-white text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-800')
            }
          >
            {w.label}
          </button>
        ))}
      </div>

      {error && <ErrorBox message={error} />}
      {!digest && !error && <Loading />}
      {digest && (
        <div className="space-y-6 px-4 pb-8">
          <Summary digest={digest} />

          <section>
            <SectionTitle>What matters</SectionTitle>
            {digest.high.length === 0 ? (
              <QuietDay hours={hours} highlights={highlights} onOpen={onOpen} />
            ) : (
              <div className="space-y-3">
                {digest.high.map((event) => (
                  <BigCard key={event.id} event={event} onOpen={onOpen} />
                ))}
              </div>
            )}
          </section>

          {digest.medium.length > 0 && (
            <section>
              <SectionTitle>Worth a look</SectionTitle>
              <div className="divide-y divide-slate-100 rounded-2xl bg-white px-4 ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
                {(showAllMedium ? digest.medium : digest.medium.slice(0, MEDIUM_PREVIEW)).map((event) => (
                  <EventRow key={event.id} event={event} onOpen={onOpen} />
                ))}
              </div>
              {digest.medium.length > MEDIUM_PREVIEW && (
                <button onClick={() => setShowAllMedium(!showAllMedium)} className="mt-2 text-sm font-medium text-sky-700 dark:text-sky-400">
                  {showAllMedium ? 'Show less' : 'Show all ' + digest.medium.length}
                </button>
              )}
            </section>
          )}

          {digest.low.length > 0 && (
            <Routine digest={digest} open={showRoutine} onToggle={() => setShowRoutine(!showRoutine)} onOpen={onOpen} />
          )}

          <p className="text-center text-[11px] text-slate-400">
            Filings up to {shortDate(digest.data_as_of.filings)} · prices up to {shortDate(digest.data_as_of.prices)} (end of day)
          </p>
        </div>
      )}
    </div>
  )
}

function Summary({ digest }) {
  const parts = []
  parts.push(digest.high.length + (digest.high.length === 1 ? ' thing matters' : ' things matter'))
  if (digest.medium.length > 0) parts.push(digest.medium.length + ' worth a look')
  if (digest.low.length > 0) parts.push(digest.low.length + ' routine hidden')
  return <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{parts.join(' · ')}</p>
}

function QuietDay({ hours, highlights, onOpen }) {
  const label = hours === 24 ? 'the last 24 hours' : 'this window'
  return (
    <div className="space-y-3">
      <div className="rounded-2xl bg-white p-4 text-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        <div className="font-semibold">Nothing urgent in {label}.</div>
        <div className="mt-0.5 text-slate-500 dark:text-slate-400">Your portfolio is quiet. Here is what mattered most this week.</div>
      </div>
      {highlights.map((event) => (
        <BigCard key={event.id} event={event} onOpen={onOpen} />
      ))}
    </div>
  )
}

function Routine({ digest, open, onToggle, onOpen }) {
  const counts = Object.entries(digest.low_counts).sort((a, b) => b[1] - a[1])
  const text = counts.map(([type, n]) => n + ' ' + typeLabel(type).toLowerCase()).join(', ')
  return (
    <section>
      <button onClick={onToggle} className="flex w-full items-center justify-between rounded-2xl bg-slate-200/60 px-4 py-3 text-left dark:bg-slate-800/60">
        <div>
          <div className="text-sm font-semibold">{digest.low.length} routine filings hidden</div>
          <div className="text-xs text-slate-500 dark:text-slate-400">{text}</div>
        </div>
        <span className="text-slate-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5 px-1">
          {digest.low.map((event) => (
            <li key={event.id}>
              <button onClick={() => onOpen(event.id)} className="w-full text-left text-xs text-slate-500 dark:text-slate-400">
                <span className="font-semibold text-slate-700 dark:text-slate-300">{event.symbol}</span> · {stripCount(event.headline)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function SectionTitle({ children }) {
  return <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{children}</h2>
}

export function Loading() {
  return (
    <div className="space-y-3 px-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-200 dark:bg-slate-800" />
      ))}
    </div>
  )
}

export function ErrorBox({ message }) {
  return (
    <div className="mx-4 rounded-2xl bg-rose-50 p-4 text-sm text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-900">
      Couldn't load: {message}. Is the backend running?
    </div>
  )
}

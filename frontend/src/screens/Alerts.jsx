import { useEffect, useState } from 'react'
import { getAlerts, getSettings } from '../api'
import { pctColor, shortDate, typeLabel } from '../format'
import { ErrorBox, Loading } from './Today'

const RANGES = [7, 30, 45]

export default function Alerts({ onOpen, onSettings }) {
  const [days, setDays] = useState(7)
  const [data, setData] = useState(null)
  const [settings, setSettings] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getSettings().then((s) => setSettings(s.settings)).catch(() => {})
  }, [])

  useEffect(() => {
    setData(null)
    setError(null)
    getAlerts(days).then(setData).catch((e) => setError(e.message))
  }, [days])

  // group by date, newest first
  const groups = []
  if (data) {
    for (const alert of data.alerts) {
      const last = groups[groups.length - 1]
      if (last && last.date === alert.date) last.items.push(alert)
      else groups.push({ date: alert.date, items: [alert] })
    }
  }

  return (
    <div>
      <header className="px-4 pt-6 pb-3">
        <h1 className="text-2xl font-bold tracking-tight">Price & volume</h1>
        {settings && (
          <button onClick={onSettings} className="mt-0.5 text-left text-sm text-slate-500 dark:text-slate-400">
            Moves beyond ±{settings.price_move_pct}% or volume above {settings.volume_multiple}× the {settings.volume_window_days}-day average ·{' '}
            <span className="text-sky-700 dark:text-sky-400">change</span>
          </button>
        )}
        {data && (
          <p className="mt-1 text-xs text-slate-400">
            As of {shortDate(data.data_as_of.prices)} close · last {days} days up to the latest data
          </p>
        )}
      </header>

      <div className="flex gap-2 px-4 pb-3">
        {RANGES.map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={
              'rounded-full px-3.5 py-1.5 text-sm font-medium ' +
              (days === d
                ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                : 'bg-white text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-800')
            }
          >
            {d} days
          </button>
        ))}
      </div>

      {error && <ErrorBox message={error} />}
      {!data && !error && <Loading />}
      {data && data.alerts.length === 0 && (
        <p className="px-4 text-sm text-slate-500">No unusual moves in this period.</p>
      )}
      {data && (
        <div className="space-y-5 px-4 pb-8">
          {groups.map((group) => (
            <section key={group.date}>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{shortDate(group.date)}</h2>
              <div className="divide-y divide-slate-100 rounded-2xl bg-white ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
                {group.items.map((alert) => (
                  <AlertRow key={alert.symbol + alert.date} alert={alert} onOpen={onOpen} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

function AlertRow({ alert, onOpen }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-bold">{alert.symbol}</div>
        <div className="truncate text-xs text-slate-500 dark:text-slate-400">{alert.name}</div>
        {alert.linked.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {alert.linked.map((link) => (
              <button
                key={link.event_id}
                onClick={() => onOpen(link.event_id)}
                className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-800 dark:bg-sky-950 dark:text-sky-300"
              >
                ← {typeLabel(link.type)} filed {link.when}
              </button>
            ))}
          </div>
        ) : (
          <div className="mt-1 text-[11px] text-slate-400">
            {alert.routine_links > 0 ? 'Only routine filings in the 3 days before' : 'No filing in the 3 days before'}
          </div>
        )}
      </div>
      <div className="text-right">
        <div className={'tabular text-base font-semibold ' + (alert.price_alert ? pctColor(alert.pct_change) : 'text-slate-500')}>
          {alert.pct_change > 0 ? '+' : ''}
          {alert.pct_change}%
        </div>
        <div className={'tabular text-xs ' + (alert.volume_alert ? 'font-semibold text-amber-600 dark:text-amber-400' : 'text-slate-400')}>
          {alert.volume_ratio}× vol
        </div>
      </div>
    </div>
  )
}

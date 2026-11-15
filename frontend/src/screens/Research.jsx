import { useEffect, useRef, useState } from 'react'
import { getResearch, getSettings } from '../api'
import { SectionTitle } from './Today'

// Pull side: research on any NSE ticker. The hero is "promised vs delivered";
// the numbers are compact cards; every citation opens a sheet with the verbatim quote.

const PREBUILT = ['TCS', 'ASIANPAINT', 'PIDILITIND', 'IRCTC', 'COALINDIA']
const POLL_MS = 4000

const VERDICT_STYLE = {
  met: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200',
  'on track': 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-900',
  partly: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
  missed: 'bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-200',
  behind: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-900',
  pending: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  "can't tell": 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
}
const VERDICT_ORDER = ['met', 'on track', 'partly', 'behind', 'missed', 'pending', "can't tell"]
const MOVE_GLYPH = { reiterated: '=', raised: '↑', lowered: '↓', changed: '~' }
const MOVE_STYLE = {
  raised: 'text-emerald-600 dark:text-emerald-400',
  lowered: 'text-rose-600 dark:text-rose-400',
  reiterated: 'text-slate-400',
  changed: 'text-amber-600 dark:text-amber-400',
}

function verdictStyle(verdict) {
  return VERDICT_STYLE[verdict] || VERDICT_STYLE.pending
}

function formatValue(value, unit) {
  if (value === null || value === undefined || value === 'n/a') return 'n/a'
  if (typeof value !== 'number') return String(value)
  if (unit === 'Rs cr') return '₹' + Math.round(value).toLocaleString('en-IN') + ' cr'
  if (unit === '%') return (Number.isInteger(value) ? value : value.toFixed(1)) + '%'
  if (unit === 'x') return value + 'x'
  if (unit === 'days') return Math.round(value) + ' days'
  return value.toLocaleString('en-IN') + (unit ? ' ' + unit : '')
}

export default function Research({ ticker }) {
  if (!ticker) return <ResearchHome />
  return <ResearchPage ticker={ticker} />
}

// ---------- the search screen ----------

function ResearchHome() {
  const [query, setQuery] = useState('')
  const [portfolio, setPortfolio] = useState([])

  useEffect(() => {
    getSettings()
      .then((d) => setPortfolio(d.portfolio.map((c) => c.symbol)))
      .catch(() => setPortfolio([]))
  }, [])

  function go(symbol) {
    const clean = symbol.trim().toUpperCase().replace(/[^A-Z0-9&-]/g, '')
    if (clean) window.location.hash = '#/research/' + encodeURIComponent(clean)
  }

  return (
    <div className="px-4 pt-6 pb-8">
      <div className="text-xs font-semibold tracking-[0.2em] text-sky-700 dark:text-sky-400">FINN</div>
      <h1 className="mt-1 text-2xl font-bold tracking-tight">Research</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">Any NSE company. Primary sources only: filings, transcripts, screener tables.</p>

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          go(query)
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value.toUpperCase())}
          placeholder="NSE symbol, e.g. HAVELLS"
          autoCapitalize="characters"
          autoCorrect="off"
          className="min-w-0 flex-1 rounded-xl bg-white px-4 py-3 text-sm font-semibold tracking-wide ring-1 ring-slate-200 placeholder:font-normal placeholder:text-slate-400 focus:ring-2 focus:ring-sky-500 focus:outline-none dark:bg-slate-900 dark:ring-slate-800"
        />
        <button type="submit" className="rounded-xl bg-sky-700 px-4 text-sm font-semibold text-white">
          Go
        </button>
      </form>

      <section className="mt-6">
        <SectionTitle>Ready now</SectionTitle>
        <ChipRow symbols={PREBUILT} onPick={go} />
        <p className="mt-1.5 text-xs text-slate-500">Pre-built. Loads in a second.</p>
      </section>

      {portfolio.length > 0 && (
        <section className="mt-6">
          <SectionTitle>Portfolio</SectionTitle>
          <ChipRow symbols={portfolio.filter((s) => !PREBUILT.includes(s))} onPick={go} />
          <p className="mt-1.5 text-xs text-slate-500">Built on first open: numbers in seconds, the rest in a few minutes.</p>
        </section>
      )}
    </div>
  )
}

function ChipRow({ symbols, onPick }) {
  return (
    <div className="flex flex-wrap gap-2">
      {symbols.map((s) => (
        <button
          key={s}
          onClick={() => onPick(s)}
          className="rounded-full bg-white px-3.5 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-200 dark:ring-slate-800"
        >
          {s}
        </button>
      ))}
    </div>
  )
}

// ---------- one company ----------

function needsPolling(data) {
  if (!data) return false
  if (data.status === 'building') return true
  return Object.values(data.stages || {}).some((s) => s.status === 'running' || s.status === 'pending')
}

function ResearchPage({ ticker }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [sheet, setSheet] = useState(null) // what the bottom sheet shows
  const timer = useRef(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    setSheet(null)
    window.scrollTo(0, 0)

    function load() {
      getResearch(ticker)
        .then((d) => {
          if (cancelled) return
          setData(d)
          if (needsPolling(d)) timer.current = setTimeout(load, POLL_MS)
        })
        .catch((e) => {
          if (!cancelled) setError(e.message)
        })
    }
    load()
    return () => {
      cancelled = true
      if (timer.current) clearTimeout(timer.current)
    }
  }, [ticker])

  const financials = data && data.sections.financials
  const promises = data && data.sections.promises
  const transcripts = data && data.sections.transcripts

  return (
    <div className="pb-8">
      <div className="sticky top-0 z-10 flex items-center justify-between bg-slate-100/90 px-4 py-3 backdrop-blur dark:bg-slate-950/90">
        <a href="#/research" className="text-sm font-medium text-sky-700 dark:text-sky-400">← Research</a>
        {data && data.status === 'building' && (
          <span className="flex items-center gap-2 text-xs text-slate-500">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-sky-500 border-t-transparent" /> building
          </span>
        )}
      </div>

      {error && <NotFound ticker={ticker} message={error} />}
      {!data && !error && <HeaderSkeleton ticker={ticker} />}

      {data && (
        <div className="space-y-6 px-4">
          <Header ticker={ticker} data={data} financials={financials} />

          {data.status === 'error' && <CalmCard tone="rose" title="Could not reach the data source" text={data.progress} />}

          <section>
            <SectionTitle>Promised vs delivered</SectionTitle>
            {promises ? (
              <Scorecard promises={promises} onCite={setSheet} />
            ) : (
              <StageState stage={data.stages.promises} guidance={data.stages.guidance} progress={data.progress} status={data.status} />
            )}
          </section>

          {financials ? (
            <section>
              <SectionTitle>Numbers · screener</SectionTitle>
              <div className="space-y-3">
                {financials.sections.map((s) => (
                  <NumbersCard key={s.id} section={s} finance={financials.finance} onSource={setSheet} />
                ))}
              </div>
            </section>
          ) : (
            <section>
              <SectionTitle>Numbers</SectionTitle>
              <StageState stage={data.stages.financials} progress={data.progress} status={data.status} />
            </section>
          )}

          <section>
            <SectionTitle>Sources</SectionTitle>
            {transcripts ? <Sources transcripts={transcripts} financials={financials} /> : <StageState stage={data.stages.transcripts} progress={data.progress} status={data.status} />}
          </section>

          <p className="text-center text-[11px] text-slate-400">
            Every number and quote is from a primary source: screener tables, concall transcripts, exchange filings. Nothing from news or outside knowledge.
          </p>
        </div>
      )}

      {sheet && <Sheet item={sheet} onClose={() => setSheet(null)} />}
    </div>
  )
}

function Header({ ticker, data, financials }) {
  return (
    <header className="pt-1">
      <div className="flex items-baseline gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{ticker}</h1>
        {financials && (
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
            {financials.statement}
          </span>
        )}
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-300">{data.name || (financials && financials.name) || ''}</p>
      <p className="text-xs text-slate-400">
        {data.as_of ? 'As of ' + data.as_of.slice(0, 16) : ''}
        {data.status === 'building' ? ' · ' + data.progress : ''}
      </p>
    </header>
  )
}

function HeaderSkeleton({ ticker }) {
  return (
    <div className="space-y-4 px-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{ticker}</h1>
        <p className="text-sm text-slate-500">Fetching screener and the last 5 calls…</p>
      </div>
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-28 animate-pulse rounded-2xl bg-slate-200 dark:bg-slate-800" />
      ))}
    </div>
  )
}

function NotFound({ ticker, message }) {
  return (
    <div className="px-4">
      <h1 className="text-2xl font-bold tracking-tight">{ticker}</h1>
      <div className="mt-3 rounded-2xl bg-white p-4 text-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        <div className="font-semibold">Nothing to research here</div>
        <p className="mt-1 text-slate-600 dark:text-slate-300">{message}</p>
        <a href="#/research" className="mt-3 inline-block text-sm font-medium text-sky-700 dark:text-sky-400">Try another symbol →</a>
      </div>
    </div>
  )
}

// What a section shows while its stage isn't done: skeleton, quota pause, or an error.
function StageState({ stage, guidance, progress, status }) {
  const s = stage ? stage.status : 'pending'
  if (s === 'waiting_quota' || (guidance && guidance.status === 'waiting_quota')) {
    const message = (stage && stage.message) || (guidance && guidance.message) || ''
    return (
      <CalmCard
        tone="amber"
        title="Paused: the free LLM quota for today is used up"
        text={'The numbers and transcripts are here. The reading of the calls resumes by itself after the daily reset (about 13:30 IST). ' + (message ? '' : '')}
      />
    )
  }
  if (s === 'error') {
    return (
      <CalmCard
        tone="amber"
        title="The AI service was busy"
        text={(stage && stage.message) || 'Reopen this page in about 10 minutes and this part is retried.'}
      />
    )
  }
  if (status === 'error') return null
  return (
    <div className="rounded-2xl bg-white p-4 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
        <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-sky-500 border-t-transparent" />
        {progress || 'Working…'}
      </div>
      <div className="mt-3 space-y-2">
        <div className="h-4 w-3/4 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
      </div>
      <p className="mt-3 text-xs text-slate-400">Reading the last 5 earnings calls takes a few minutes the first time. Checked every 4 s.</p>
    </div>
  )
}

function CalmCard({ tone, title, text }) {
  const styles = {
    amber: 'bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-100 dark:ring-amber-900',
    rose: 'bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950 dark:text-rose-100 dark:ring-rose-900',
  }
  return (
    <div className={'rounded-2xl p-4 text-sm ring-1 ' + styles[tone]}>
      <div className="font-semibold">{title}</div>
      <p className="mt-1 text-xs opacity-80">{text}</p>
    </div>
  )
}

// ---------- hero: promised vs delivered ----------

function Scorecard({ promises, onCite }) {
  const counts = promises.scorecard.counts || {}
  return (
    <div className="space-y-3">
      <div className="rounded-2xl bg-slate-900 p-4 text-white shadow-sm dark:bg-white dark:text-slate-900">
        <div className="text-[11px] font-semibold uppercase tracking-wider opacity-60">
          {promises.scorecard.promises} promises · {promises.scorecard.threads} threads · last {promises.transcripts.length} calls
        </div>
        <p className="mt-1 text-sm font-medium leading-snug">{promises.scorecard.credibility}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {VERDICT_ORDER.filter((v) => counts[v]).map((v) => (
            <span key={v} className={'rounded-full px-2 py-0.5 text-[11px] font-semibold ' + verdictStyle(v)}>
              {counts[v]} {v}
            </span>
          ))}
        </div>
      </div>
      {promises.threads.map((t) => (
        <ThreadCard key={t.key} thread={t} onCite={onCite} />
      ))}
    </div>
  )
}

function ThreadCard({ thread, onCite }) {
  const moves = {}
  for (const m of thread.movement) moves[m.to_quarter + '|' + m.to] = m.change
  // actuals: the evidence rows the arithmetic used (fall back to the thread's transcript evidence)
  // (the same evidence row appears under several promises as separate copies: dedupe by content)
  const seen = new Set()
  let used = []
  for (const p of thread.promises) {
    for (const e of p.comparison.used || []) {
      const key = e.source === 'transcript' ? e.call_quarter + '|' + e.page + '|' + e.value_text : e.table + '|' + e.column
      if (seen.has(key)) continue
      seen.add(key)
      used.push(e)
    }
  }
  if (used.length === 0) used = thread.evidence.filter((e) => e.source === 'transcript').slice(-3)
  used = used.slice(-6)

  return (
    <article className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-bold tracking-tight">{thread.metric}</h3>
        <span className={'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ' + verdictStyle(thread.verdict)}>{thread.verdict}</span>
      </div>

      <div className="mt-3">
        <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">What they said</div>
        <ol className="mt-1 space-y-1">
          {thread.promises.map((p, i) => {
            const change = moves[p.call_quarter + '|' + p.target_text]
            return (
              <li key={i} className="flex items-center gap-2 text-sm">
                <button
                  onClick={() => onCite(citation(p, thread.metric))}
                  className="shrink-0 rounded-md bg-sky-50 px-1.5 py-0.5 text-[11px] font-semibold text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-900"
                >
                  {p.call_quarter} p.{p.page}
                </button>
                <span className="min-w-0 flex-1 truncate">
                  {p.target_text}
                  <span className="text-slate-400"> · {p.period}</span>
                </span>
                {change && (
                  <span className={'shrink-0 text-xs font-semibold ' + MOVE_STYLE[change]} title={change}>
                    {MOVE_GLYPH[change]} {change}
                  </span>
                )}
              </li>
            )
          })}
          {thread.dropped && (
            <li className="text-xs text-amber-700 dark:text-amber-300">Not mentioned on the latest call ({thread.newest_call}).</li>
          )}
        </ol>
      </div>

      {used.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">What happened</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {used.map((e, i) =>
              e.source === 'transcript' ? (
                <button
                  key={i}
                  onClick={() => onCite(citation(e, thread.metric, true))}
                  className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700"
                >
                  <span className="font-semibold">{e.call_quarter}</span> p.{e.page} · {e.value_text}
                </button>
              ) : (
                <button
                  key={i}
                  onClick={() => onCite({ kind: 'screener', label: thread.metric, value: e.value + (e.unit || ''), table: e.table, row: e.row, column: e.column })}
                  className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700"
                >
                  <span className="font-semibold">screener</span> {e.column} · {e.value}
                  {e.unit}
                </button>
              ),
            )}
          </div>
        </div>
      )}

      <p className="mt-3 text-sm leading-snug text-slate-700 dark:text-slate-200">{thread.sentence}</p>
    </article>
  )
}

function citation(item, metric, isActual) {
  return {
    kind: 'quote',
    title: (isActual ? 'Reported · ' : 'Promise · ') + metric,
    quote: item.quote,
    speaker: item.speaker,
    quarter: item.call_quarter,
    callDate: item.call_date,
    page: item.page,
    url: item.url,
    target: isActual ? item.value_text : item.target_text + (item.period ? ' · ' + item.period : ''),
  }
}

// ---------- numbers ----------

function NumbersCard({ section, onSource }) {
  const metrics = section.metrics.filter((m) => m.value !== 'n/a' && m.value !== null && m.value !== undefined)
  return (
    <article className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <h3 className="text-sm font-bold tracking-tight">{section.title}</h3>
      <p className="mt-1 text-sm leading-snug text-slate-700 dark:text-slate-200">{section.takeaway}</p>
      {section.id === 'trajectory' && section.series && <Sparkline series={section.series} />}
      {section.id === 'cash_quality' && section.series && <CashBars series={section.series} />}
      <div className="mt-3 grid grid-cols-2 gap-1.5">
        {metrics.map((m, i) => (
          <button
            key={i}
            onClick={() => onSource({ kind: 'screener', label: m.label, value: formatValue(m.value, m.unit), period: m.period, table: m.source.table, row: m.source.row, column: m.source.column, url: m.source.url })}
            className="rounded-xl bg-slate-50 px-2.5 py-2 text-left dark:bg-slate-800/60"
          >
            <div className="truncate text-[10px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{m.label}</div>
            <div className="tabular text-sm font-semibold leading-tight">{formatValue(m.value, m.unit)}</div>
            <div className="text-[10px] text-slate-400">{m.period}</div>
          </button>
        ))}
      </div>
    </article>
  )
}

// Revenue (filled line) and profit (thin line), each scaled to its own range. Inline SVG, no library.
function Sparkline({ series }) {
  const years = series.years || []
  const revenue = series.revenue || []
  const profit = series.net_profit || []
  if (years.length < 2) return null
  const W = 320
  const H = 72
  const pad = 4
  function path(values) {
    const clean = values.map((v) => (typeof v === 'number' ? v : null))
    const present = clean.filter((v) => v !== null)
    if (present.length < 2) return ''
    const min = Math.min(...present)
    const max = Math.max(...present)
    const span = max - min || 1
    return clean
      .map((v, i) => {
        if (v === null) return null
        const x = pad + (i / (clean.length - 1)) * (W - 2 * pad)
        const y = H - pad - ((v - min) / span) * (H - 2 * pad)
        return x.toFixed(1) + ',' + y.toFixed(1)
      })
      .filter(Boolean)
      .join(' ')
  }
  const revenuePath = path(revenue)
  const profitPath = path(profit)
  const last = revenue.length - 1
  return (
    <div className="mt-3">
      <svg viewBox={'0 0 ' + W + ' ' + H} className="h-[72px] w-full" role="img" aria-label="Revenue and profit by financial year">
        {revenuePath && (
          <polygon
            points={revenuePath + ' ' + (W - pad) + ',' + (H - pad) + ' ' + pad + ',' + (H - pad)}
            className="fill-sky-200/60 dark:fill-sky-900/40"
          />
        )}
        {revenuePath && <polyline points={revenuePath} fill="none" strokeWidth="2" className="stroke-sky-600 dark:stroke-sky-400" />}
        {profitPath && <polyline points={profitPath} fill="none" strokeWidth="1.5" strokeDasharray="3 3" className="stroke-emerald-600 dark:stroke-emerald-400" />}
      </svg>
      <div className="flex justify-between text-[10px] text-slate-400">
        <span>{years[0]}</span>
        <span>
          <span className="text-sky-600 dark:text-sky-400">— {series.revenue_name || 'Revenue'}</span>
          <span className="ml-2 text-emerald-600 dark:text-emerald-400">- - Profit</span>
        </span>
        <span>
          {years[last]}
          {typeof revenue[last] === 'number' ? ' · ₹' + Math.round(revenue[last]).toLocaleString('en-IN') + ' cr' : ''}
        </span>
      </div>
    </div>
  )
}

// CFO / PAT per year as small bars (1.0x = profits fully converted to cash).
function CashBars({ series }) {
  const years = series.years || []
  const ratios = series.cfo_to_pat || []
  if (years.length === 0) return null
  const max = Math.max(1.5, ...ratios.filter((r) => typeof r === 'number'))
  return (
    <div className="mt-3 flex items-end gap-1.5">
      {years.map((y, i) => {
        const r = ratios[i]
        const h = typeof r === 'number' ? Math.max(4, Math.min(44, (r / max) * 44)) : 4
        const good = typeof r === 'number' && r >= 0.9
        return (
          <div key={y} className="flex flex-1 flex-col items-center gap-1">
            <div className="tabular text-[10px] text-slate-500">{typeof r === 'number' ? r.toFixed(1) + 'x' : '—'}</div>
            <div className={'w-full rounded-sm ' + (good ? 'bg-emerald-400/80' : 'bg-amber-400/80')} style={{ height: h + 'px' }} />
            <div className="text-[10px] text-slate-400">{y}</div>
          </div>
        )
      })}
    </div>
  )
}

// ---------- sources ----------

function Sources({ transcripts, financials }) {
  return (
    <div className="divide-y divide-slate-100 rounded-2xl bg-white ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
      {transcripts.transcripts.map((t) => (
        <div key={t.url} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
          <div className="min-w-0">
            <div className="font-semibold">
              {t.quarter} <span className="font-normal text-slate-500">earnings call</span>
            </div>
            <div className="text-xs text-slate-400">
              {t.call_date ? 'held ' + t.call_date : 'date not stated'} · {t.n_pages} pages{t.scanned ? ' · scanned' : ''} · via {t.source}
            </div>
          </div>
          <a href={t.url} target="_blank" rel="noreferrer" className="shrink-0 text-xs text-sky-700 dark:text-sky-400">
            PDF ↗
          </a>
        </div>
      ))}
      {transcripts.missing.map((m) => (
        <div key={m.quarter} className="px-4 py-2.5 text-sm">
          <div className="font-semibold text-slate-500">{m.quarter} <span className="font-normal">· missing</span></div>
          <div className="text-xs text-slate-400">{m.reason}</div>
        </div>
      ))}
      {financials && (
        <div className="flex items-center justify-between px-4 py-2.5 text-sm">
          <div>
            <div className="font-semibold">screener.in</div>
            <div className="text-xs text-slate-400">{financials.statement} tables · fetched {financials.fetched_on}</div>
          </div>
          <a href={financials.url} target="_blank" rel="noreferrer" className="text-xs text-sky-700 dark:text-sky-400">
            Open ↗
          </a>
        </div>
      )}
    </div>
  )
}

// ---------- the bottom sheet (citations and screener sources) ----------

function Sheet({ item, onClose }) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-slate-900/50" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-t-3xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-2xl dark:bg-slate-900"
      >
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-slate-300 dark:bg-slate-700" />
        {item.kind === 'quote' ? <QuoteSheet item={item} /> : <SourceSheet item={item} />}
        <button onClick={onClose} className="mt-4 w-full rounded-xl bg-slate-100 py-2.5 text-sm font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          Close
        </button>
      </div>
    </div>
  )
}

function QuoteSheet({ item }) {
  const pdf = item.url ? item.url + '#page=' + item.page : null
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{item.title}</div>
      <div className="mt-1 text-sm font-semibold">{item.target}</div>
      <blockquote className="mt-3 border-l-2 border-sky-500 pl-3 text-sm leading-relaxed text-slate-800 dark:text-slate-100">“{item.quote}”</blockquote>
      <div className="mt-3 text-xs text-slate-500">
        <span className="font-semibold text-slate-700 dark:text-slate-300">{item.speaker || 'Management'}</span>
        {' · ' + item.quarter + ' earnings call'}
        {item.callDate ? ', ' + item.callDate : ''}
        {' · page ' + item.page}
      </div>
      {pdf && (
        <a href={pdf} target="_blank" rel="noreferrer" className="mt-3 inline-block text-sm font-medium text-sky-700 dark:text-sky-400">
          Open PDF, p. {item.page} ↗
        </a>
      )}
      <p className="mt-2 text-[11px] text-slate-400">Quote checked verbatim against the PDF page by the app before being shown.</p>
    </div>
  )
}

function SourceSheet({ item }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Source · screener.in</div>
      <div className="mt-1 text-sm font-semibold">{item.label}</div>
      <div className="tabular mt-1 text-2xl font-bold">{item.value}</div>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-slate-400">Table</dt>
        <dd className="text-slate-700 dark:text-slate-200">{item.table}</dd>
        <dt className="text-slate-400">Row</dt>
        <dd className="text-slate-700 dark:text-slate-200">{item.row}</dd>
        <dt className="text-slate-400">Column</dt>
        <dd className="text-slate-700 dark:text-slate-200">{item.column}</dd>
        {item.period && (
          <>
            <dt className="text-slate-400">Period</dt>
            <dd className="text-slate-700 dark:text-slate-200">{item.period}</dd>
          </>
        )}
      </dl>
      {item.url && (
        <a href={item.url} target="_blank" rel="noreferrer" className="mt-3 inline-block text-sm font-medium text-sky-700 dark:text-sky-400">
          Open on screener ↗
        </a>
      )}
      <p className="mt-2 text-[11px] text-slate-400">Ratios such as CAGR, D/E and CFO/PAT are computed by the app from these table cells.</p>
    </div>
  )
}

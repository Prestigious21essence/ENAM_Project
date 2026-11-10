import { useState } from 'react'
import { initials } from '../format'
import { CardFooter, CardHeader, MarketLine, WhyLine } from './parts'

const CHANGE_BADGES = {
  joining: { text: 'Joining', color: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200' },
  leaving: { text: 'Leaving', color: 'bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-200' },
  role_change: { text: 'New role', color: 'bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200' },
  reappointed: { text: 'Re-appointed', color: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300' },
}

function Person({ change }) {
  const [open, setOpen] = useState(false)
  const badge = CHANGE_BADGES[change.change] || CHANGE_BADGES.role_change
  const bio = change.bio || ''
  const longBio = bio.length > 140
  return (
    <div className="flex gap-3 py-2.5">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white dark:bg-slate-700">
        {initials(change.name)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold">{change.name}</span>
          <span className={'rounded-full px-2 py-0.5 text-[11px] font-semibold ' + badge.color}>{badge.text}</span>
        </div>
        <div className="text-xs text-slate-600 dark:text-slate-300">{change.role}</div>
        {(change.effective_date || change.reason) && (
          <div className="mt-0.5 text-xs text-slate-500">
            {change.effective_date ? 'From ' + change.effective_date : ''}
            {change.effective_date && change.reason ? ' · ' : ''}
            {change.reason}
          </div>
        )}
        {bio && (
          <p className="mt-1.5 text-sm leading-snug text-slate-700 dark:text-slate-300">
            {open || !longBio ? bio : bio.slice(0, 140) + '… '}
            {longBio && (
              <button onClick={() => setOpen(!open)} className="text-xs font-medium text-sky-700 dark:text-sky-400">
                {open ? ' less' : 'more'}
              </button>
            )}
          </p>
        )}
        {bio && change.bio_source && change.bio_source !== 'this filing' && (
          <a href={change.bio_source} target="_blank" rel="noreferrer" className="mt-0.5 block text-[11px] text-slate-400 underline">
            bio from the company's earlier filing ↗
          </a>
        )}
      </div>
    </div>
  )
}

export default function MgmtCard({ event, onOpen }) {
  const [showAll, setShowAll] = useState(false)
  const changes = event.card.changes || []
  // Top people (CEO/MD/CFO/Chairman) first
  const top = changes.filter((c) => c.seniority === 'top')
  const rest = changes.filter((c) => c.seniority !== 'top')
  const ordered = top.concat(rest)
  const visible = showAll ? ordered : ordered.slice(0, Math.max(2, top.length))
  const hidden = ordered.length - visible.length
  return (
    <article className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <CardHeader event={event} label="Leadership change" onOpen={onOpen} />
      <div className="mt-1 divide-y divide-slate-100 dark:divide-slate-800">
        {visible.map((change, i) => (
          <Person key={change.name + i} change={change} />
        ))}
      </div>
      {hidden > 0 && (
        <button onClick={() => setShowAll(true)} className="mt-1 text-xs font-medium text-sky-700 dark:text-sky-400">
          + {hidden} more {hidden === 1 ? 'change' : 'changes'}
        </button>
      )}
      <WhyLine reason={event.reason} />
      <MarketLine market={event.market} />
      <CardFooter event={event} onOpen={onOpen} />
    </article>
  )
}

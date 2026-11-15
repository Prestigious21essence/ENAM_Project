import { useEffect, useState } from 'react'
import { onWakeChange } from './api'
import Alerts from './screens/Alerts'
import EventDetail from './screens/EventDetail'
import Research from './screens/Research'
import Settings from './screens/Settings'
import Today from './screens/Today'

// Tiny hash router: #/  #/alerts  #/research  #/research/<TICKER>  #/settings  #/event/<id>
function readRoute() {
  const hash = window.location.hash.replace(/^#/, '') || '/'
  if (hash.startsWith('/event/')) return { screen: 'event', id: decodeURIComponent(hash.slice(7)) }
  if (hash.startsWith('/research/')) return { screen: 'research', ticker: decodeURIComponent(hash.slice(10)).toUpperCase() }
  if (hash === '/research') return { screen: 'research', ticker: null }
  if (hash === '/alerts') return { screen: 'alerts' }
  if (hash === '/settings') return { screen: 'settings' }
  return { screen: 'today' }
}

const TABS = [
  { screen: 'today', label: 'Today', hash: '#/', icon: '◉' },
  { screen: 'alerts', label: 'Alerts', hash: '#/alerts', icon: '↯' },
  { screen: 'research', label: 'Research', hash: '#/research', icon: '⌕' },
  { screen: 'settings', label: 'Settings', hash: '#/settings', icon: '⚙' },
]

export default function App() {
  const [route, setRoute] = useState(readRoute())

  const [waking, setWaking] = useState(false)

  useEffect(() => {
    onWakeChange(setWaking)
    return () => onWakeChange(null)
  }, [])

  useEffect(() => {
    function onHashChange() {
      setRoute(readRoute())
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  function openEvent(id) {
    window.location.hash = '#/event/' + encodeURIComponent(id)
  }

  function goBack() {
    if (window.history.length > 1) window.history.back()
    else window.location.hash = '#/'
  }

  return (
    <div className="mx-auto min-h-screen max-w-md pb-20">
      {waking && <WakingBanner />}
      {route.screen === 'today' && <Today onOpen={openEvent} />}
      {route.screen === 'alerts' && <Alerts onOpen={openEvent} onSettings={() => (window.location.hash = '#/settings')} />}
      {route.screen === 'settings' && <Settings />}
      {route.screen === 'research' && <Research ticker={route.ticker} />}
      {route.screen === 'event' && <EventDetail id={route.id} onBack={goBack} onOpen={openEvent} />}

      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
        <div className="mx-auto flex max-w-md">
          {TABS.map((tab) => {
            const active = route.screen === tab.screen
            return (
              <a
                key={tab.screen}
                href={tab.hash}
                className={'flex flex-1 flex-col items-center py-2 text-[11px] font-medium ' + (active ? 'text-sky-700 dark:text-sky-400' : 'text-slate-400')}
              >
                <span className="text-lg leading-none">{tab.icon}</span>
                {tab.label}
              </a>
            )
          })}
        </div>
      </nav>
    </div>
  )
}

// Shown while the first request is slow: the free server sleeps when idle.
function WakingBanner() {
  return (
    <div className="sticky top-0 z-30 mx-4 mt-3 flex items-center gap-3 rounded-2xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200 dark:bg-amber-950 dark:text-amber-100 dark:ring-amber-900">
      <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-amber-400 border-t-transparent" />
      <div>
        <div className="font-semibold">Waking up the server…</div>
        <div className="text-xs text-amber-800/80 dark:text-amber-200/80">
          The free server sleeps when idle. The first load can take up to a minute; after that it's instant.
        </div>
      </div>
    </div>
  )
}

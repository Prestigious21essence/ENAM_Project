import { useEffect, useState } from 'react'
import Alerts from './screens/Alerts'
import EventDetail from './screens/EventDetail'
import Settings from './screens/Settings'
import Today from './screens/Today'

// Tiny hash router: #/  #/alerts  #/settings  #/event/<id>
function readRoute() {
  const hash = window.location.hash.replace(/^#/, '') || '/'
  if (hash.startsWith('/event/')) return { screen: 'event', id: decodeURIComponent(hash.slice(7)) }
  if (hash === '/alerts') return { screen: 'alerts' }
  if (hash === '/settings') return { screen: 'settings' }
  return { screen: 'today' }
}

const TABS = [
  { screen: 'today', label: 'Today', hash: '#/', icon: '◉' },
  { screen: 'alerts', label: 'Alerts', hash: '#/alerts', icon: '↯' },
  { screen: 'settings', label: 'Settings', hash: '#/settings', icon: '⚙' },
]

export default function App() {
  const [route, setRoute] = useState(readRoute())

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
      {route.screen === 'today' && <Today onOpen={openEvent} />}
      {route.screen === 'alerts' && <Alerts onOpen={openEvent} onSettings={() => (window.location.hash = '#/settings')} />}
      {route.screen === 'settings' && <Settings />}
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

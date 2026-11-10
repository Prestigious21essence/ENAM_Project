import { useEffect, useState } from 'react'
import { getDigest, getSettings, saveSettings } from '../api'
import { typeLabel } from '../format'
import { ErrorBox, Loading, SectionTitle } from './Today'

const NUMBER_FIELDS = [
  { key: 'price_move_pct', label: 'Price move', unit: '%', step: 0.5, help: 'Alert when a stock moves more than this in a day' },
  { key: 'volume_multiple', label: 'Volume spike', unit: '×', step: 0.5, help: 'Alert when volume is this many times its recent average' },
  { key: 'results_move_pct', label: 'Results surprise', unit: '%', step: 5, help: 'Results reach the top only if profit moved this much year on year (or the stock reacted)' },
]

export default function Settings() {
  const [data, setData] = useState(null)
  const [form, setForm] = useState(null)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getSettings()
      .then((d) => {
        setData(d)
        setForm(d.settings)
      })
      .catch((e) => setError(e.message))
  }, [])

  function setNumber(key, value) {
    setForm({ ...form, [key]: value })
    setMessage(null)
  }

  function toggleCategory(category) {
    let chosen = form.alert_categories.slice()
    if (chosen.includes(category)) chosen = chosen.filter((c) => c !== category)
    else chosen.push(category)
    setForm({ ...form, alert_categories: chosen })
    setMessage(null)
  }

  async function save() {
    setSaving(true)
    setMessage(null)
    try {
      const changes = { alert_categories: form.alert_categories }
      for (const field of NUMBER_FIELDS) changes[field.key] = Number(form[field.key])
      await saveSettings(changes)
      const season = await getDigest(45 * 24)
      setMessage('Saved. Over the season that means ' + season.high.length + ' top items and ' + season.alerts.length + ' price/volume alerts.')
    } catch (e) {
      setMessage('Not saved: ' + e.message)
    }
    setSaving(false)
  }

  if (error) return <div className="pt-6"><ErrorBox message={error} /></div>
  if (!form) return <div className="pt-6"><Loading /></div>

  return (
    <div className="px-4 pt-6 pb-8">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">You decide what "unusual" means.</p>

      <section className="mt-5">
        <SectionTitle>Thresholds</SectionTitle>
        <div className="divide-y divide-slate-100 rounded-2xl bg-white ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
          {NUMBER_FIELDS.map((field) => (
            <div key={field.key} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{field.label}</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">{field.help}</div>
              </div>
              <div className="flex items-center gap-1">
                <Stepper onClick={() => setNumber(field.key, Math.max(0, Number(form[field.key]) - field.step))}>−</Stepper>
                <div className="tabular w-14 text-center text-sm font-semibold">
                  {Number(form[field.key])}
                  {field.unit}
                </div>
                <Stepper onClick={() => setNumber(field.key, Number(form[field.key]) + field.step)}>+</Stepper>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-5">
        <SectionTitle>What can reach the top</SectionTitle>
        <div className="flex flex-wrap gap-2">
          {data.all_categories.map((category) => {
            const on = form.alert_categories.includes(category)
            return (
              <button
                key={category}
                onClick={() => toggleCategory(category)}
                className={
                  'rounded-full px-3 py-1.5 text-sm font-medium ' +
                  (on
                    ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                    : 'bg-white text-slate-500 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800')
                }
              >
                {on ? '✓ ' : ''}
                {typeLabel(category)}
              </button>
            )
          })}
        </div>
        <p className="mt-2 text-xs text-slate-500">Turned-off kinds still appear under "Worth a look", just never at the top.</p>
      </section>

      <button
        onClick={save}
        disabled={saving}
        className="mt-6 w-full rounded-xl bg-sky-700 py-3 text-sm font-semibold text-white disabled:opacity-60"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
      {message && <p className="mt-2 text-center text-sm text-slate-600 dark:text-slate-300">{message}</p>}

      <section className="mt-8">
        <SectionTitle>Portfolio ({data.portfolio.length})</SectionTitle>
        <div className="grid grid-cols-2 gap-2">
          {data.portfolio.map((company) => (
            <div key={company.symbol} className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
              <div className="text-sm font-bold">{company.symbol}</div>
              <div className="truncate text-xs text-slate-500">{company.sector}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function Stepper({ onClick, children }) {
  return (
    <button onClick={onClick} className="h-8 w-8 rounded-full bg-slate-100 text-lg leading-none font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
      {children}
    </button>
  )
}

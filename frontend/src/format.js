// Small display helpers shared by all screens.

export const TYPE_LABELS = {
  results: 'Results',
  'M&A': 'M&A',
  management_change: 'Leadership',
  fund_raise: 'Fund raise',
  litigation: 'Legal',
  credit_rating: 'Rating',
  dividend: 'Dividend',
  capex: 'Capex',
  press_release: 'News',
  earnings_call: 'Earnings call',
  investor_meetings: 'Investor meet',
  unclassified: 'Paperwork',
  postal_ballot: 'Postal ballot',
  agm_egm: 'AGM / EGM',
  pledging: 'Pledge',
  insider_trading: 'Insider trade',
  bonus_split: 'Bonus / split',
}

// Tailwind classes for the little type pill on each card
export const TYPE_COLORS = {
  results: 'bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200',
  'M&A': 'bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200',
  management_change: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
  fund_raise: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200',
  litigation: 'bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-200',
}
const DEFAULT_TYPE_COLOR = 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'

export function typeLabel(type) {
  return TYPE_LABELS[type] || type
}

export function typeColor(type) {
  return TYPE_COLORS[type] || DEFAULT_TYPE_COLOR
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2026-11-05 18:51" or "2026-11-05" -> "5 Nov"
export function shortDate(text) {
  if (!text) return ''
  const month = Number(text.slice(5, 7))
  const day = Number(text.slice(8, 10))
  return day + ' ' + MONTHS[month - 1]
}

// 20337.4 -> "20,337"
export function crore(value) {
  return Math.round(value).toLocaleString('en-IN')
}

export function signedPct(value) {
  if (value === null || value === undefined) return 'n/a'
  const sign = value > 0 ? '+' : ''
  return sign + value.toFixed(1) + '%'
}

// green for up, red for down, grey for missing
export function pctColor(value) {
  if (value === null || value === undefined) return 'text-slate-400'
  if (value > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (value < 0) return 'text-rose-600 dark:text-rose-400'
  return 'text-slate-500'
}

// Quarter-end date as printed in the PDF ("30.09.2026", "September 30, 2026") -> "Q2 FY27"
export function quarterLabel(printed) {
  if (!printed) return 'Quarterly results'
  const text = printed.toLowerCase()
  let month = 0
  const names = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
  for (let i = 0; i < names.length; i++) {
    if (text.includes(names[i])) month = i + 1
  }
  const numbers = text.match(/\d+/g) || []
  let year = 0
  for (const n of numbers) {
    if (n.length === 4) year = Number(n)
  }
  if (month === 0 && numbers.length >= 3) month = Number(numbers[1])     // 30.09.2026
  if (month === 0 || year === 0) return 'Quarterly results'
  // Indian financial year starts in April: Jun = Q1, Sep = Q2, Dec = Q3, Mar = Q4
  const quarter = { 6: 1, 9: 2, 12: 3, 3: 4 }[month]
  const fiscalYear = month <= 3 ? year : year + 1
  if (!quarter) return 'Quarterly results'
  return 'Q' + quarter + ' FY' + String(fiscalYear).slice(2)
}

export function initials(name) {
  const parts = (name || '?').replace(/[.,]/g, ' ').split(' ').filter((p) => p.length > 1)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0][0].toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

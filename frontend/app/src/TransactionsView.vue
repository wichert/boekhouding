<script setup>
import { Modal } from 'bootstrap'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  path: { type: String, default: () => window.location.pathname },
  search: { type: String, default: () => window.location.search },
  hash: { type: String, default: () => window.location.hash },
  navigate: {
    type: Function,
    default: (url) => {
      window.history.pushState({}, '', url)
    },
  },
})

const FILTER_DEBOUNCE_MS = 150
let accountSearchTimer = null
let detailFilterTimer = null
let bookingFilterTimer = null

const loadingYears = ref(true)
const loading = ref(false)
const error = ref('')
const availableYears = ref([])
const defaultYear = ref('2026')
const activeYear = ref('')

function emptyPayload() {
  return {
    metadata: {},
    accounts: [],
    allAccounts: [],
    accountsById: {},
    transactions: [],
    journalOptions: [],
    supplierOptions: [],
    accountOptions: [],
    yearOptions: [],
  }
}

const payload = ref(emptyPayload())

// Account Overview search (with 150ms debounce)
const accountSearchInput = ref('')
const accountSearchQuery = ref('')

// Account Detail filters (with 150ms debounce)
function defaultDetailFilters() {
  return {
    text: '',
    amountMin: '',
    amountMax: '',
    dateFrom: '',
    dateTo: '',
  }
}

const detailFilterDraft = ref(defaultDetailFilters())
const detailFilters = ref(defaultDetailFilters())

// Bookings view filters (with 150ms debounce)
function defaultBookingFilters() {
  return {
    text: '',
    amountMode: 'transaction',
    amountMin: '',
    amountMax: '',
    dateFrom: '',
    dateTo: '',
  }
}

const bookingFilterDraft = ref(defaultBookingFilters())
const bookingFilters = ref(defaultBookingFilters())

// Transaction Detail Modal state
const selectedTransactionId = ref('')
const txModalEl = ref(null)
let txModal = null
let suppressHashClose = false
let lastModalTriggerEl = null
const accountDetailFrom = ref('')

const accountIdFromPath = computed(() => {
  const match = (props.path || '').match(/^\/transactions\/accounts\/([^/]+)$/)
  return match ? decodeURIComponent(match[1]) : ''
})

const isAccountDetailView = computed(() => Boolean(accountIdFromPath.value))
const isAccountsOverviewView = computed(() => props.path === '/transactions/accounts')
const isBookingsView = computed(() => props.path === '/transactions/bookings')
const isBalanceView = computed(() => !isAccountDetailView.value && !isAccountsOverviewView.value && !isBookingsView.value)
const cameFromBookings = computed(() => accountDetailFrom.value === 'bookings')
const cameFromAccounts = computed(() => accountDetailFrom.value === 'accounts')
const cameFromBalance = computed(() => !cameFromBookings.value && !cameFromAccounts.value)

function currentSearchParams() {
  return new URLSearchParams(window.location.search)
}

function bookingQueryParams(filtersObj = bookingFilters.value) {
  return {
    q: (filtersObj.text || '').trim(),
    amount_mode: filtersObj.amountMode === 'line' ? 'line' : '',
    amount_min: filtersObj.amountMin !== '' && filtersObj.amountMin !== null ? String(filtersObj.amountMin) : '',
    amount_max: filtersObj.amountMax !== '' && filtersObj.amountMax !== null ? String(filtersObj.amountMax) : '',
    from_date: filtersObj.dateFrom || '',
    to_date: filtersObj.dateTo || '',
  }
}

function syncBookingFiltersFromParams(params) {
  const synced = {
    text: params.get('q') || '',
    amountMode: params.get('amount_mode') === 'line' ? 'line' : 'transaction',
    amountMin: params.get('amount_min') ?? '',
    amountMax: params.get('amount_max') ?? '',
    dateFrom: params.get('from_date') || '',
    dateTo: params.get('to_date') || '',
  }
  bookingFilterDraft.value = { ...synced }
  bookingFilters.value = { ...synced }
}

function syncFromUrlSearch() {
  const params = currentSearchParams()
  if (isAccountsOverviewView.value) {
    const q = params.get('q') || ''
    accountSearchInput.value = q
    accountSearchQuery.value = q
  } else if (isBookingsView.value) {
    syncBookingFiltersFromParams(params)
  }
  accountDetailFrom.value = params.get('from') || ''
  const yearParam = params.get('year') || defaultYear.value
  if (yearParam && yearParam !== activeYear.value && availableYears.value.some((y) => y.year === yearParam)) {
    loadTransactionsForYear(yearParam)
  }
}

function onPopState() {
  syncFromUrlSearch()
}

window.addEventListener('popstate', onPopState)

onBeforeUnmount(() => {
  window.removeEventListener('popstate', onPopState)
  clearTimeout(accountSearchTimer)
  clearTimeout(detailFilterTimer)
  clearTimeout(bookingFilterTimer)
  txModal?.dispose()
})

async function fetchJson(url) {
  const response = await fetch(url)
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

function buildUrlWithParams(targetPath, extraParams = {}, targetHash = '') {
  const params = new URLSearchParams()
  const year = extraParams.year !== undefined ? extraParams.year : activeYear.value
  if (year) params.set('year', year)
  if (extraParams.q) params.set('q', extraParams.q)
  if (extraParams.amount_mode === 'line') params.set('amount_mode', 'line')
  if (extraParams.amount_min !== undefined && extraParams.amount_min !== '') params.set('amount_min', String(extraParams.amount_min))
  if (extraParams.amount_max !== undefined && extraParams.amount_max !== '') params.set('amount_max', String(extraParams.amount_max))
  if (extraParams.from_date) params.set('from_date', extraParams.from_date)
  if (extraParams.to_date) params.set('to_date', extraParams.to_date)
  if (extraParams.from) params.set('from', extraParams.from)
  const query = params.toString()
  return `${targetPath}${query ? `?${query}` : ''}${targetHash}`
}

async function loadTransactionsForYear(year) {
  if (!year) return
  activeYear.value = year
  loading.value = true
  error.value = ''
  try {
    const data = await fetchJson(`/api/audit/transactions/${encodeURIComponent(year)}`)
    if (activeYear.value === year) {
      payload.value = data
      await syncModalFromHash(props.hash)
    }
  } catch (err) {
    if (activeYear.value === year) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  } finally {
    if (activeYear.value === year) {
      loading.value = false
    }
  }
}

onMounted(async () => {
  const params = currentSearchParams()
  const initialQuery = params.get('q') || ''
  if (isAccountsOverviewView.value) {
    accountSearchInput.value = initialQuery
    accountSearchQuery.value = initialQuery
  } else if (isBookingsView.value) {
    syncBookingFiltersFromParams(params)
  }
  accountDetailFrom.value = params.get('from') || ''

  try {
    const data = await fetchJson('/api/audit/years')
    availableYears.value = data.years || []
    defaultYear.value = data.defaultYear || availableYears.value[0]?.year || '2026'
    const requestedYear = params.get('year') || ''
    const validRequested = availableYears.value.some((item) => item.year === requestedYear) ? requestedYear : ''
    const initialYear = validRequested || defaultYear.value
    if (!params.get('year')) {
      window.history.replaceState(
        {},
        '',
        buildUrlWithParams(
          props.path || '/transactions',
          {
            year: initialYear,
            q: isAccountsOverviewView.value ? initialQuery : '',
            ...(isBookingsView.value ? bookingQueryParams(bookingFilters.value) : {}),
            from: isAccountDetailView.value ? accountDetailFrom.value : '',
          },
          props.hash || '',
        ),
      )
    }
    await loadTransactionsForYear(initialYear)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingYears.value = false
  }
})

function onYearSelectChange(event) {
  const newYear = event.target.value
  if (!newYear || newYear === activeYear.value) return
  if (selectedTransactionId.value) {
    suppressHashClose = true
    closeTransactionModal()
    selectedTransactionId.value = ''
  }
  detailFilterDraft.value.dateFrom = ''
  detailFilterDraft.value.dateTo = ''
  detailFilters.value.dateFrom = ''
  detailFilters.value.dateTo = ''
  bookingFilterDraft.value.dateFrom = ''
  bookingFilterDraft.value.dateTo = ''
  bookingFilters.value.dateFrom = ''
  bookingFilters.value.dateTo = ''
  const targetUrl = buildUrlWithParams(
    props.path || '/transactions',
    {
      year: newYear,
      q: isAccountsOverviewView.value ? accountSearchQuery.value.trim() : '',
      ...(isBookingsView.value ? bookingQueryParams(bookingFilters.value) : {}),
      from: isAccountDetailView.value ? accountDetailFrom.value : '',
    },
    '',
  )
  props.navigate(targetUrl)
  loadTransactionsForYear(newYear)
}

function onAccountSearchInput() {
  clearTimeout(accountSearchTimer)
  accountSearchTimer = setTimeout(() => {
    accountSearchQuery.value = accountSearchInput.value
    const targetUrl = buildUrlWithParams('/transactions/accounts', {
      year: activeYear.value,
      q: accountSearchQuery.value.trim(),
    })
    window.history.replaceState({}, '', targetUrl)
  }, FILTER_DEBOUNCE_MS)
}

function clearAccountSearch() {
  clearTimeout(accountSearchTimer)
  accountSearchInput.value = ''
  accountSearchQuery.value = ''
  const targetUrl = buildUrlWithParams('/transactions/accounts', { year: activeYear.value })
  window.history.replaceState({}, '', targetUrl)
}

function scheduleDetailFilters({ immediate = false } = {}) {
  clearTimeout(detailFilterTimer)
  const run = () => {
    detailFilters.value = { ...detailFilterDraft.value }
  }
  if (immediate) run()
  else detailFilterTimer = setTimeout(run, FILTER_DEBOUNCE_MS)
}

function resetDetailFilters() {
  clearTimeout(detailFilterTimer)
  detailFilterDraft.value = defaultDetailFilters()
  detailFilters.value = defaultDetailFilters()
}

function scheduleBookingFilters({ immediate = false } = {}) {
  clearTimeout(bookingFilterTimer)
  const run = () => {
    bookingFilters.value = { ...bookingFilterDraft.value }
    if (isBookingsView.value) {
      const targetUrl = buildUrlWithParams(
        '/transactions/bookings',
        {
          year: activeYear.value,
          ...bookingQueryParams(bookingFilters.value),
        },
        window.location.hash || '',
      )
      window.history.replaceState({}, '', targetUrl)
    }
  }
  if (immediate) run()
  else bookingFilterTimer = setTimeout(run, FILTER_DEBOUNCE_MS)
}

function resetBookingFilters() {
  clearTimeout(bookingFilterTimer)
  bookingFilterDraft.value = defaultBookingFilters()
  bookingFilters.value = defaultBookingFilters()
  if (isBookingsView.value) {
    const targetUrl = buildUrlWithParams(
      '/transactions/bookings',
      { year: activeYear.value, ...bookingQueryParams() },
      window.location.hash || '',
    )
    window.history.replaceState({}, '', targetUrl)
  }
}

watch(accountIdFromPath, () => {
  resetDetailFilters()
})

watch(
  () => props.search,
  () => {
    syncFromUrlSearch()
  },
)

watch(
  () => props.path,
  (newPath) => {
    const params = currentSearchParams()
    accountDetailFrom.value = params.get('from') || ''
    if (isAccountsOverviewView.value) {
      const q = params.get('q') || ''
      accountSearchInput.value = q
      accountSearchQuery.value = q
    } else if (isBookingsView.value) {
      syncBookingFiltersFromParams(params)
    }
    const yearParam = params.get('year')
    if (yearParam && yearParam !== activeYear.value && availableYears.value.some((y) => y.year === yearParam)) {
      loadTransactionsForYear(yearParam)
    } else if (!yearParam && activeYear.value) {
      window.history.replaceState(
        {},
        '',
        buildUrlWithParams(
          newPath || '/transactions',
          {
            year: activeYear.value,
            q: isAccountsOverviewView.value ? accountSearchQuery.value.trim() : '',
            ...(isBookingsView.value ? bookingQueryParams(bookingFilters.value) : {}),
            from: isAccountDetailView.value ? accountDetailFrom.value : '',
          },
          window.location.hash || '',
        ),
      )
    }
  },
)

const transactions = computed(() => payload.value.transactions || [])
const transactionsById = computed(() => {
  const map = new Map()
  for (const tx of transactions.value) {
    if (tx.transactionID) map.set(String(tx.transactionID), tx)
    if (tx.transactionKey) map.set(String(tx.transactionKey), tx)
  }
  return map
})

const metadata = computed(() => payload.value.metadata || {})
const header = computed(() => metadata.value.header || {})

const activeYearOption = computed(() =>
  availableYears.value.find((item) => item.year === activeYear.value) || null,
)

function yearOptionLabel(option) {
  const fileName = option.fileName || (option.filePath ? String(option.filePath).split('/').pop() : '')
  return fileName ? `${option.year} (${fileName})` : option.year
}

function accountTypeLabel(type) {
  if (type === 'Blns') return 'Balans'
  if (type === 'WenV') return 'W&V'
  return type || ''
}

function accountTypeBadgeClass(type) {
  if (type === 'Blns') return 'text-bg-light border text-secondary'
  if (type === 'WenV') return 'text-bg-light border text-primary'
  return 'text-bg-light border text-body-secondary'
}

const activeAccounts = computed(() => {
  if (Array.isArray(payload.value.accounts) && payload.value.accounts.length) {
    return payload.value.accounts.filter((account) => account.isActive !== false)
  }
  return []
})

const filteredAccounts = computed(() => {
  const query = accountSearchQuery.value.trim().toLowerCase()
  if (!query) return activeAccounts.value
  return activeAccounts.value.filter(
    (account) =>
      String(account.id || '').toLowerCase().includes(query) ||
      String(account.description || '').toLowerCase().includes(query),
  )
})

const overviewTotals = computed(() => {
  let transactionCount = 0
  let openingBalance = 0
  let totalDebit = 0
  let totalCredit = 0
  let currentBalance = 0
  for (const account of filteredAccounts.value) {
    transactionCount += Number(account.transactionCount || 0)
    openingBalance += Number(account.openingBalance || 0)
    totalDebit += Number(account.totalDebit || 0)
    totalCredit += Number(account.totalCredit || 0)
    currentBalance += Number(account.currentBalance || 0)
  }
  return {
    transactionCount,
    openingBalance: Math.round(openingBalance * 100) / 100,
    totalDebit: Math.round(totalDebit * 100) / 100,
    totalCredit: Math.round(totalCredit * 100) / 100,
    currentBalance: Math.round(currentBalance * 100) / 100,
  }
})

const nonZeroAccounts = computed(() =>
  activeAccounts.value.filter((account) => Math.abs(Number(account.currentBalance || 0)) >= 0.005),
)

function buildBalanceSection({ key, title, debitSubtitle, creditSubtitle, debitAccounts, creditAccounts, diffLabel, diffAmount }) {
  const debitTotal = Math.round(debitAccounts.reduce((sum, item) => sum + item.displayAmount, 0) * 100) / 100
  const creditTotal = Math.round(creditAccounts.reduce((sum, item) => sum + item.displayAmount, 0) * 100) / 100
  const difference = Math.round((debitTotal - creditTotal) * 100) / 100
  const isBalanced = Math.abs(difference) < 0.005
  return {
    key,
    title,
    debitSubtitle,
    creditSubtitle,
    debitAccounts,
    creditAccounts,
    totalAccountCount: debitAccounts.length + creditAccounts.length,
    debitTotal,
    creditTotal,
    difference,
    isBalanced,
    diffLabel,
    diffAmount: diffAmount !== undefined ? diffAmount(debitTotal, creditTotal) : difference,
  }
}

const balanceSections = computed(() => {
  const balansDebit = []
  const balansCredit = []
  const wenvDebit = []
  const wenvCredit = []

  for (const account of nonZeroAccounts.value) {
    const balance = Number(account.currentBalance || 0)
    const firstDigit = String(account.id || '').trim().charAt(0)
    if (account.type === 'Blns') {
      if (balance > 0) {
        balansDebit.push({ ...account, displayAmount: balance })
      } else if (balance < 0) {
        balansCredit.push({ ...account, displayAmount: -balance })
      }
    } else if (account.type === 'WenV') {
      if (['4', '5', '6', '7'].includes(firstDigit)) {
        wenvDebit.push({ ...account, displayAmount: balance })
      } else if (firstDigit === '8') {
        wenvCredit.push({ ...account, displayAmount: -balance })
      } else if (balance > 0) {
        wenvDebit.push({ ...account, displayAmount: balance })
      } else if (balance < 0) {
        wenvCredit.push({ ...account, displayAmount: -balance })
      }
    } else {
      if (balance > 0) {
        balansDebit.push({ ...account, displayAmount: balance })
      } else if (balance < 0) {
        balansCredit.push({ ...account, displayAmount: -balance })
      }
    }
  }

  return [
    buildBalanceSection({
      key: 'balans',
      title: 'Balans',
      debitSubtitle: 'Activa / debetzijde',
      creditSubtitle: 'Passiva / creditzijde',
      debitAccounts: balansDebit,
      creditAccounts: balansCredit,
      diffLabel: 'Saldo verschil',
      diffAmount: (debitTotal, creditTotal) => Math.round((debitTotal - creditTotal) * 100) / 100,
    }),
    buildBalanceSection({
      key: 'wenv',
      title: 'Winst en Verlies',
      debitSubtitle: wenvDebit.some((a) => !['4', '5', '6', '7'].includes(String(a.id).trim().charAt(0)))
        ? 'Kosten (4–7, 9)'
        : 'Kosten (4–7)',
      creditSubtitle: wenvCredit.some((a) => String(a.id).trim().charAt(0) !== '8')
        ? 'Opbrengsten (8, 9)'
        : 'Opbrengsten (8)',
      debitAccounts: wenvDebit,
      creditAccounts: wenvCredit,
      diffLabel: 'Resultaat',
      diffAmount: (debitTotal, creditTotal) => Math.round((creditTotal - debitTotal) * 100) / 100,
    }),
  ]
})

function sectionDiffBadgeClass(section) {
  if (section.key === 'wenv' && section.diffAmount > 0) {
    return 'text-bg-success-subtle text-success-emphasis border border-success-subtle'
  }
  if (section.key === 'wenv' && section.diffAmount < 0) {
    return 'text-bg-danger-subtle text-danger-emphasis border border-danger-subtle'
  }
  return 'text-bg-warning-subtle text-warning-emphasis border border-warning-subtle'
}

const currentAccount = computed(() => {
  const id = accountIdFromPath.value
  if (!id) return null
  const fromActive = (payload.value.accounts || []).find((acc) => String(acc.id) === id)
  if (fromActive) return fromActive
  const fromAll = (payload.value.allAccounts || []).find((acc) => String(acc.id) === id)
  if (fromAll) return fromAll
  const meta = payload.value.accountsById?.[id]
  if (meta) {
    return {
      id: meta.id || id,
      description: meta.description || '',
      type: meta.type || '',
      leadCode: meta.leadCode || '',
      openingDebit: 0,
      openingCredit: 0,
      openingBalance: 0,
      totalDebit: 0,
      totalCredit: 0,
      currentBalance: 0,
      transactionCount: 0,
      isActive: false,
      lines: [],
    }
  }
  return null
})

const accountLines = computed(() => currentAccount.value?.lines || [])

const hasActiveDetailFilters = computed(() => {
  const f = detailFilters.value
  return Boolean(
    f.text.trim() ||
      f.amountMin !== '' ||
      f.amountMax !== '' ||
      f.dateFrom ||
      f.dateTo,
  )
})

const filteredAccountLines = computed(() => {
  const f = detailFilters.value
  const query = f.text.trim().toLowerCase()
  const minAmount = f.amountMin === '' || f.amountMin === null ? null : Number(f.amountMin)
  const maxAmount = f.amountMax === '' || f.amountMax === null ? null : Number(f.amountMax)
  const dateFrom = f.dateFrom || ''
  const dateTo = f.dateTo || ''

  return accountLines.value.filter((line) => {
    const date = line.effectiveDate || line.transactionDate || ''
    if (dateFrom && (!date || date < dateFrom)) return false
    if (dateTo && (!date || date > dateTo)) return false

    const impact = Number(
      line.impactAmount !== undefined
        ? line.impactAmount
        : Math.max(Math.abs(Number(line.debitAmount || 0)), Math.abs(Number(line.creditAmount || 0))),
    )
    if (minAmount !== null && Number.isFinite(minAmount) && impact < minAmount) return false
    if (maxAmount !== null && Number.isFinite(maxAmount) && impact > maxAmount) return false

    if (query) {
      const searchable = [
        line.description,
        line.documentID,
        line.supplierName,
        line.custSupID,
        line.transactionID,
        line.journalDescription,
        line.journalID,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (!searchable.includes(query)) return false
    }

    return true
  })
})

const filteredAccountDebitTotal = computed(() =>
  filteredAccountLines.value.reduce((sum, line) => sum + Number(line.debitAmount || 0), 0),
)

const filteredAccountCreditTotal = computed(() =>
  filteredAccountLines.value.reduce((sum, line) => sum + Number(line.creditAmount || 0), 0),
)

function transactionEffectiveDate(tx) {
  return tx.transactionDate || tx.minEffectiveDate || tx.maxEffectiveDate || ''
}

function compareTransactionIds(aId, bId) {
  const aStr = String(aId || '').trim()
  const bStr = String(bId || '').trim()
  const aNum = Number(aStr)
  const bNum = Number(bStr)
  const aIsNum = aStr !== '' && Number.isFinite(aNum)
  const bIsNum = bStr !== '' && Number.isFinite(bNum)
  if (aIsNum && bIsNum) {
    if (aNum !== bNum) return aNum - bNum
  } else if (aIsNum !== bIsNum) {
    return aIsNum ? -1 : 1
  }
  return aStr.localeCompare(bStr)
}

const sortedTransactions = computed(() => {
  return [...transactions.value].sort((a, b) => {
    const dateA = transactionEffectiveDate(a)
    const dateB = transactionEffectiveDate(b)
    if (dateA !== dateB) return dateA.localeCompare(dateB)
    return compareTransactionIds(a.transactionID, b.transactionID)
  })
})

function bookingDescription(tx) {
  let parts = Array.isArray(tx.distinctDescriptions) && tx.distinctDescriptions.length
    ? tx.distinctDescriptions
    : []
  if (!parts.length) {
    const seen = new Set()
    for (const line of tx.lines || []) {
      const desc = String(line.description || '').trim()
      const key = desc.toLowerCase().replace(/\s+/g, ' ')
      if (desc && !seen.has(key)) {
        seen.add(key)
        parts.push(desc)
      }
    }
  }
  if (parts.length > 0) {
    let displayed = parts.slice(0, 2)
    const query = bookingFilters.value.text.trim().toLowerCase()
    if (query && parts.length > 2) {
      const matchingPart = parts.slice(2).find((part) => part.toLowerCase().includes(query))
      if (matchingPart) {
        displayed = [parts[0], matchingPart]
      }
    }
    return displayed.join(' · ') + (parts.length > 2 ? ` (+${parts.length - 2})` : '')
  }
  return tx.descriptionSummary || tx.journalDescription || `Transactie ${tx.transactionID}`
}

function lineMatchesAmountRange(line, lineMin, lineMax, hasLineMin, hasLineMax) {
  const lineImpact = Math.max(
    Math.abs(Number(line.debitAmount || 0)),
    Math.abs(Number(line.creditAmount || 0)),
  )
  if (hasLineMin && hasLineMax) {
    return lineImpact >= lineMin && lineImpact <= lineMax
  }
  if (hasLineMin) {
    return lineImpact >= lineMin
  }
  return lineMax === 0 ? lineImpact === 0 : lineImpact > 0 && lineImpact <= lineMax
}

function setBookingAmountMode(mode) {
  if (bookingFilterDraft.value.amountMode === mode) return
  bookingFilterDraft.value.amountMode = mode
  scheduleBookingFilters({ immediate: true })
}

const hasActiveBookingFilters = computed(() => {
  const f = bookingFilters.value
  return Boolean(
    f.text.trim() ||
      f.amountMin !== '' ||
      f.amountMax !== '' ||
      f.dateFrom ||
      f.dateTo,
  )
})

function amountMatchesRange(value, minVal, maxVal) {
  if (minVal !== null && Number.isFinite(minVal) && value < minVal) return false
  if (maxVal !== null && Number.isFinite(maxVal) && value > maxVal) return false
  return true
}

const filteredBookings = computed(() => {
  const f = bookingFilters.value
  const query = f.text.trim().toLowerCase()
  const amountMode = f.amountMode === 'line' ? 'line' : 'transaction'
  const minVal = f.amountMin === '' || f.amountMin === null ? null : Number(f.amountMin)
  const maxVal = f.amountMax === '' || f.amountMax === null ? null : Number(f.amountMax)
  const dateFrom = f.dateFrom || ''
  const dateTo = f.dateTo || ''
  const hasMin = minVal !== null && Number.isFinite(minVal)
  const hasMax = maxVal !== null && Number.isFinite(maxVal)

  return sortedTransactions.value.filter((tx) => {
    if (dateFrom || dateTo) {
      const primaryDate = transactionEffectiveDate(tx)
      const lineDates = (tx.lines || []).map((l) => l.effectiveDate).filter(Boolean)
      const candidateDates = Array.from(new Set([primaryDate, ...lineDates].filter(Boolean)))
      const dateMatches = candidateDates.some((d) => {
        if (dateFrom && d < dateFrom) return false
        if (dateTo && d > dateTo) return false
        return true
      })
      if (!dateMatches) return false
    }

    if (hasMin || hasMax) {
      if (amountMode === 'line') {
        const lines = tx.lines || []
        const anyLineMatches = lines.some((line) =>
          lineMatchesAmountRange(line, minVal, maxVal, hasMin, hasMax),
        )
        if (!anyLineMatches) return false
      } else {
        const debitTotal = Math.abs(Number(tx.debitTotal || 0))
        const creditTotal = Math.abs(Number(tx.creditTotal || 0))
        const txAmount = Number(
          tx.transactionAmount !== undefined
            ? tx.transactionAmount
            : Math.max(debitTotal, creditTotal),
        )
        const candidateTxAmounts = [txAmount, debitTotal, creditTotal]
        if (!candidateTxAmounts.some((amt) => amountMatchesRange(amt, hasMin ? minVal : null, hasMax ? maxVal : null))) {
          return false
        }
      }
    }

    if (query) {
      if (typeof tx.textSearch === 'string' && tx.textSearch.length > 0) {
        if (!tx.textSearch.includes(query)) return false
      } else {
        const txFields = [
          tx.descriptionSummary,
          tx.journalDescription,
          tx.journalID,
          tx.transactionID,
          ...(tx.supplierNames || []),
          ...(tx.supplierIDs || []),
        ]
        const lineFields = []
        for (const line of tx.lines || []) {
          if (line.description) lineFields.push(line.description)
          if (line.documentID) lineFields.push(line.documentID)
          if (line.accountDescription) lineFields.push(line.accountDescription)
          if (line.accountID) lineFields.push(line.accountID)
          if (line.supplierName) lineFields.push(line.supplierName)
          if (line.custSupID) lineFields.push(line.custSupID)
        }
        const searchable = [...txFields, ...lineFields].filter(Boolean).join(' ').toLowerCase()
        if (!searchable.includes(query)) return false
      }
    }

    return true
  })
})

const filteredBookingsDebitTotal = computed(() =>
  Math.round(filteredBookings.value.reduce((sum, tx) => sum + Number(tx.debitTotal || 0), 0) * 100) / 100,
)

const filteredBookingsCreditTotal = computed(() =>
  Math.round(filteredBookings.value.reduce((sum, tx) => sum + Number(tx.creditTotal || 0), 0) * 100) / 100,
)

function resolveFromSource(options = {}) {
  if (options.from) return options.from
  if (options.fromBalance === true) return 'balance'
  if (options.fromBalance === false) return 'accounts'
  if (isBookingsView.value || cameFromBookings.value) return 'bookings'
  if (isAccountsOverviewView.value || cameFromAccounts.value) return 'accounts'
  return 'balance'
}

function openAccount(accountId, options = {}) {
  if (!accountId) return
  const fromValue = resolveFromSource(options)
  const targetUrl = buildUrlWithParams(`/transactions/accounts/${encodeURIComponent(accountId)}`, {
    year: activeYear.value,
    from: fromValue,
  })
  if (`${window.location.pathname}${window.location.search}` === targetUrl) return
  accountDetailFrom.value = fromValue
  props.navigate(targetUrl)
}

function onAccountLinkClick(event, accountId, options = {}) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
    event.stopPropagation()
    return
  }
  event.preventDefault()
  event.stopPropagation()
  openAccount(accountId, options)
}

function goToAccountsOverview() {
  accountDetailFrom.value = ''
  const targetUrl = buildUrlWithParams('/transactions/accounts', {
    year: activeYear.value,
    q: accountSearchQuery.value.trim(),
  })
  if (`${window.location.pathname}${window.location.search}` === targetUrl) return
  props.navigate(targetUrl)
}

function goToBalanceView() {
  accountDetailFrom.value = ''
  const targetUrl = buildUrlWithParams('/transactions', {
    year: activeYear.value,
  })
  if (`${window.location.pathname}${window.location.search}` === targetUrl) return
  props.navigate(targetUrl)
}

function goToBookingsView() {
  accountDetailFrom.value = ''
  const targetUrl = buildUrlWithParams('/transactions/bookings', {
    year: activeYear.value,
    ...bookingQueryParams(),
  })
  if (`${window.location.pathname}${window.location.search}` === targetUrl) return
  props.navigate(targetUrl)
}

function goBackToOverview() {
  if (cameFromBookings.value) {
    goToBookingsView()
  } else if (cameFromBalance.value) {
    goToBalanceView()
  } else {
    goToAccountsOverview()
  }
}

const selectedTransaction = computed(() => {
  if (!selectedTransactionId.value) return null
  return transactionsById.value.get(String(selectedTransactionId.value)) || null
})

function ensureModalInstance() {
  if (!txModal && txModalEl.value) {
    txModal = new Modal(txModalEl.value, { backdrop: true, focus: true })
    txModalEl.value.addEventListener('hidden.bs.modal', () => {
      selectedTransactionId.value = ''
      if (window.location.hash.startsWith('#tx-') && !suppressHashClose) {
        window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`)
        window.dispatchEvent(new HashChangeEvent('hashchange'))
      }
      if (!suppressHashClose && lastModalTriggerEl && document.contains(lastModalTriggerEl)) {
        lastModalTriggerEl.focus()
      }
      lastModalTriggerEl = null
      suppressHashClose = false
    })
  }
}

async function openTransaction(transactionId, { updateHash = true } = {}) {
  if (!transactionId) return
  if (document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
    lastModalTriggerEl = document.activeElement
  }
  selectedTransactionId.value = String(transactionId)
  await nextTick()
  ensureModalInstance()
  txModal?.show()
  const targetHash = `#tx-${encodeURIComponent(transactionId)}`
  if (updateHash && window.location.hash !== targetHash) {
    window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}${targetHash}`)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  }
}

function closeTransactionModal() {
  txModal?.hide()
}

function navigateToAccountFromModal(accountId) {
  if (!accountId) return
  if (String(accountId) === accountIdFromPath.value) {
    closeTransactionModal()
    return
  }
  suppressHashClose = true
  txModal?.hide()
  selectedTransactionId.value = ''
  window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`)
  openAccount(accountId)
  window.scrollTo({ top: 0, behavior: 'instant' })
}

function onModalAccountLinkClick(event, accountId) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
    return
  }
  event.preventDefault()
  navigateToAccountFromModal(accountId)
}

async function syncModalFromHash(hashValue) {
  const match = (hashValue || '').match(/^#tx-(.+)$/)
  if (match) {
    const txId = decodeURIComponent(match[1])
    if (transactionsById.value.has(String(txId))) {
      await openTransaction(txId, { updateHash: false })
    } else {
      if (selectedTransactionId.value) {
        suppressHashClose = true
        closeTransactionModal()
        selectedTransactionId.value = ''
      }
      window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`)
    }
  } else if (selectedTransactionId.value) {
    suppressHashClose = true
    closeTransactionModal()
    selectedTransactionId.value = ''
  }
}

watch(
  () => props.hash,
  (newHash) => {
    syncModalFromHash(newHash)
  },
)

function formatMoney(value) {
  const number = Number(value || 0)
  return new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' }).format(number)
}

function balanceTextClass(amount, { muteZero = false } = {}) {
  const num = Number(amount || 0)
  if (num < 0) return 'text-danger'
  if (muteZero && num === 0) return 'text-body-secondary fw-normal'
  return ''
}

function formatVat(vat) {
  if (!vat || (!vat.vatCode && !vat.vatPercentage)) return '—'
  if (vat.vatCode && vat.vatPercentage) return `${vat.vatCode} (${vat.vatPercentage}%)`
  return vat.vatCode || `${vat.vatPercentage}%`
}
</script>

<template>
  <div>
    <!-- Loading / Error states -->
    <div v-if="loadingYears" class="py-4 text-body-secondary">Beschikbare auditbestanden laden…</div>
    <div v-else-if="error && !loading" class="alert alert-danger" role="alert">{{ error }}</div>

    <!-- ACCOUNT DETAIL VIEW (/transactions/accounts/:accountId) -->
    <section v-else-if="isAccountDetailView">
      <div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
        <div>
          <div class="d-flex flex-wrap align-items-center gap-2 mb-1 d-print-none tx-detail-nav">
            <a
              v-if="cameFromBookings"
              :href="buildUrlWithParams('/transactions/bookings', { year: activeYear, ...bookingQueryParams() })"
              class="btn btn-sm btn-outline-secondary"
              @click.prevent="goToBookingsView"
            >
              ← Terug naar boekingen
            </a>
            <a
              v-else-if="cameFromBalance"
              :href="buildUrlWithParams('/transactions', { year: activeYear })"
              class="btn btn-sm btn-outline-secondary"
              @click.prevent="goToBalanceView"
            >
              ← Terug naar balans
            </a>
            <a
              v-else
              :href="buildUrlWithParams('/transactions/accounts', { year: activeYear, q: accountSearchQuery.trim() })"
              class="btn btn-sm btn-outline-secondary"
              @click.prevent="goToAccountsOverview"
            >
              ← Terug naar rekeningenoverzicht
            </a>
            <a
              v-if="!cameFromBalance"
              :href="buildUrlWithParams('/transactions', { year: activeYear })"
              class="btn btn-sm btn-link text-decoration-none text-body-secondary"
              @click.prevent="goToBalanceView"
            >
              Balans
            </a>
            <a
              v-if="!cameFromAccounts"
              :href="buildUrlWithParams('/transactions/accounts', { year: activeYear, q: accountSearchQuery.trim() })"
              class="btn btn-sm btn-link text-decoration-none text-body-secondary"
              @click.prevent="goToAccountsOverview"
            >
              Rekeningenoverzicht
            </a>
            <a
              v-if="!cameFromBookings"
              :href="buildUrlWithParams('/transactions/bookings', { year: activeYear, ...bookingQueryParams() })"
              class="btn btn-sm btn-link text-decoration-none text-body-secondary"
              @click.prevent="goToBookingsView"
            >
              Boekingen
            </a>
          </div>
          <h1 class="h3 mb-1 d-flex align-items-center gap-2 flex-wrap">
            <span class="font-monospace">{{ accountIdFromPath }}</span>
            <span>·</span>
            <span>{{ currentAccount?.description || 'Rekening niet gevonden' }}</span>
            <span
              v-if="currentAccount?.type"
              class="badge fs-6 fw-normal"
              :class="accountTypeBadgeClass(currentAccount.type)"
            >
              {{ accountTypeLabel(currentAccount.type) }}
            </span>
          </h1>
          <p class="text-body-secondary small mb-0">
            <template v-if="header.companyName">{{ header.companyName }} · </template>
            Boekjaar {{ activeYear }}
            <template v-if="activeYearOption?.fileName"> · {{ activeYearOption.fileName }}</template>
          </p>
        </div>

        <!-- Compact Audit File Switcher Dropdown -->
        <div class="d-flex align-items-center gap-2 bg-body border rounded px-2 py-1 shadow-sm d-print-none audit-file-filter">
          <label for="auditYearSelectDetail" class="form-label mb-0 small text-body-secondary text-nowrap">
            Auditbestand
          </label>
          <select
            id="auditYearSelectDetail"
            :value="activeYear"
            class="form-select form-select-sm w-auto"
            aria-label="Selecteer boekjaar of auditbestand"
            @change="onYearSelectChange"
          >
            <option v-for="option in availableYears" :key="option.year" :value="option.year">
              {{ yearOptionLabel(option) }}
            </option>
          </select>
        </div>
      </div>

      <p v-if="loading" class="text-body-secondary">Rekeninggegevens voor {{ activeYear }} laden…</p>

      <div v-else-if="!currentAccount" class="alert alert-warning">
        Rekening <strong>{{ accountIdFromPath }}</strong> komt niet voor in boekjaar {{ activeYear }}.
      </div>

      <template v-else>
        <!-- Summary Cards -->
        <div class="row g-3 mb-3">
          <div class="col-6 col-md">
            <div class="card h-100 shadow-sm">
              <div class="card-body py-2 px-3">
                <div class="text-body-secondary small">Beginbalans</div>
                <div
                  class="fs-5 fw-semibold font-monospace"
                  :class="balanceTextClass(currentAccount.openingBalance, { muteZero: true })"
                >
                  {{ formatMoney(currentAccount.openingBalance) }}
                </div>
              </div>
            </div>
          </div>
          <div class="col-6 col-md">
            <div class="card h-100 shadow-sm">
              <div class="card-body py-2 px-3">
                <div class="text-body-secondary small">Totaal debet</div>
                <div class="fs-5 fw-semibold font-monospace">{{ formatMoney(currentAccount.totalDebit) }}</div>
              </div>
            </div>
          </div>
          <div class="col-6 col-md">
            <div class="card h-100 shadow-sm">
              <div class="card-body py-2 px-3">
                <div class="text-body-secondary small">Totaal credit</div>
                <div class="fs-5 fw-semibold font-monospace">{{ formatMoney(currentAccount.totalCredit) }}</div>
              </div>
            </div>
          </div>
          <div class="col-6 col-md">
            <div class="card h-100 shadow-sm border-primary-subtle">
              <div class="card-body py-2 px-3">
                <div class="text-body-secondary small">Huidig saldo</div>
                <div
                  class="fs-5 fw-bold font-monospace"
                  :class="balanceTextClass(currentAccount.currentBalance)"
                >
                  {{ formatMoney(currentAccount.currentBalance) }}
                </div>
              </div>
            </div>
          </div>
          <div class="col-6 col-md">
            <div class="card h-100 shadow-sm">
              <div class="card-body py-2 px-3">
                <div class="text-body-secondary small">Transacties</div>
                <div class="fs-5 fw-semibold">{{ currentAccount.transactionCount }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Debounced Filter Bar -->
        <form class="card mb-3 shadow-sm d-print-none tx-filter-form" @submit.prevent>
          <div class="card-body py-2 px-3">
            <div class="row g-2 align-items-end">
              <div class="col-12 col-md-4 col-lg-3">
                <label for="detailFilterText" class="form-label small mb-1">Omschrijving</label>
                <input
                  id="detailFilterText"
                  v-model="detailFilterDraft.text"
                  type="search"
                  class="form-control form-control-sm"
                  placeholder="Omschrijving, document, relatie of ID"
                  @input="scheduleDetailFilters()"
                />
              </div>
              <div class="col-6 col-md-2">
                <label for="detailFilterAmountMin" class="form-label small mb-1">Vanaf bedrag</label>
                <input
                  id="detailFilterAmountMin"
                  v-model="detailFilterDraft.amountMin"
                  type="number"
                  step="0.01"
                  min="0"
                  class="form-control form-control-sm"
                  placeholder="0,00"
                  @input="scheduleDetailFilters()"
                />
              </div>
              <div class="col-6 col-md-2">
                <label for="detailFilterAmountMax" class="form-label small mb-1">Tot bedrag</label>
                <input
                  id="detailFilterAmountMax"
                  v-model="detailFilterDraft.amountMax"
                  type="number"
                  step="0.01"
                  min="0"
                  class="form-control form-control-sm"
                  placeholder="Max"
                  @input="scheduleDetailFilters()"
                />
              </div>
              <div class="col-6 col-md-2">
                <label for="detailFilterDateFrom" class="form-label small mb-1">Vanaf datum</label>
                <input
                  id="detailFilterDateFrom"
                  v-model="detailFilterDraft.dateFrom"
                  type="date"
                  :min="header.startDate || (activeYear ? `${activeYear}-01-01` : undefined)"
                  :max="header.endDate || (activeYear ? `${activeYear}-12-31` : undefined)"
                  class="form-control form-control-sm"
                  @input="scheduleDetailFilters()"
                  @change="scheduleDetailFilters({ immediate: true })"
                />
              </div>
              <div class="col-6 col-md-2">
                <label for="detailFilterDateTo" class="form-label small mb-1">T/m datum</label>
                <input
                  id="detailFilterDateTo"
                  v-model="detailFilterDraft.dateTo"
                  type="date"
                  :min="header.startDate || (activeYear ? `${activeYear}-01-01` : undefined)"
                  :max="header.endDate || (activeYear ? `${activeYear}-12-31` : undefined)"
                  class="form-control form-control-sm"
                  @input="scheduleDetailFilters()"
                  @change="scheduleDetailFilters({ immediate: true })"
                />
              </div>
              <div class="col-12 col-lg-1 d-grid">
                <button
                  type="button"
                  class="btn btn-sm btn-outline-secondary"
                  :disabled="!hasActiveDetailFilters"
                  @click="resetDetailFilters"
                >
                  Reset
                </button>
              </div>
            </div>
          </div>
        </form>

        <!-- Result Summary -->
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
          <p class="fw-semibold mb-0">
            {{ filteredAccountLines.length }} van {{ accountLines.length }} transactieregels
            <span class="text-body-secondary fw-normal">
              · debet {{ formatMoney(filteredAccountDebitTotal) }} · credit {{ formatMoney(filteredAccountCreditTotal) }}
            </span>
          </p>
          <span class="text-body-secondary small d-print-none">Klik op een regel om de volledige transactie te bekijken.</span>
        </div>

        <!-- Chronological Transactions Table -->
        <div class="table-responsive bg-body border rounded shadow-sm">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th style="width: 7.5rem">Datum</th>
                <th style="width: 9rem">Transactie</th>
                <th>Omschrijving</th>
                <th class="text-end" style="width: 9rem">Debet</th>
                <th class="text-end" style="width: 9rem">Credit</th>
                <th class="text-end" style="width: 10rem">Cumulatief saldo</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-if="!hasActiveDetailFilters && (currentAccount.openingBalance !== 0 || currentAccount.openingDebit !== 0 || currentAccount.openingCredit !== 0)"
                class="table-light text-body-secondary"
              >
                <td class="font-monospace small">—</td>
                <td><span class="badge text-bg-secondary">Beginbalans</span></td>
                <td>Beginbalans boekjaar {{ activeYear }}</td>
                <td class="text-end font-monospace">
                  {{ currentAccount.openingDebit ? formatMoney(currentAccount.openingDebit) : '—' }}
                </td>
                <td class="text-end font-monospace">
                  {{ currentAccount.openingCredit ? formatMoney(currentAccount.openingCredit) : '—' }}
                </td>
                <td
                  class="text-end font-monospace fw-semibold"
                  :class="balanceTextClass(currentAccount.openingBalance)"
                >
                  {{ formatMoney(currentAccount.openingBalance) }}
                </td>
              </tr>
              <tr
                v-for="line in filteredAccountLines"
                :key="`${line.transactionKey}-${line.recordID}`"
                class="clickable-row"
                tabindex="0"
                role="button"
                @click="openTransaction(line.transactionID)"
                @keydown.enter.prevent="openTransaction(line.transactionID)"
                @keydown.space.prevent="openTransaction(line.transactionID)"
              >
                <td class="font-monospace text-nowrap">{{ line.effectiveDate || line.transactionDate }}</td>
                <td class="text-nowrap">
                  <span class="font-monospace fw-semibold">{{ line.transactionID }}</span>
                  <span v-if="line.journalID" class="text-body-secondary small ms-1">({{ line.journalID }})</span>
                </td>
                <td>
                  <div>{{ line.description || '—' }}</div>
                  <div v-if="line.supplierName || line.documentID" class="text-body-secondary small">
                    <span v-if="line.supplierName">{{ line.supplierName }}</span>
                    <span v-if="line.supplierName && line.documentID"> · </span>
                    <span v-if="line.documentID">Doc: {{ line.documentID }}</span>
                  </div>
                </td>
                <td class="text-end font-monospace text-nowrap">
                  {{ line.debitAmount ? formatMoney(line.debitAmount) : '—' }}
                </td>
                <td class="text-end font-monospace text-nowrap">
                  {{ line.creditAmount ? formatMoney(line.creditAmount) : '—' }}
                </td>
                <td
                  class="text-end font-monospace fw-semibold text-nowrap"
                  :class="balanceTextClass(line.cumulativeBalance)"
                >
                  {{ formatMoney(line.cumulativeBalance) }}
                </td>
              </tr>
              <tr v-if="!filteredAccountLines.length">
                <td colspan="6" class="text-body-secondary py-3">
                  {{
                    hasActiveDetailFilters
                      ? 'Geen transactieregels gevonden voor de geselecteerde filters.'
                      : 'Geen mutaties in dit boekjaar.'
                  }}
                </td>
              </tr>
            </tbody>
            <tfoot v-if="filteredAccountLines.length" class="table-light fw-semibold">
              <tr>
                <td colspan="3">
                  Totaal ({{ filteredAccountLines.length }} {{ filteredAccountLines.length === 1 ? 'regel' : 'regels' }})
                </td>
                <td class="text-end font-monospace text-nowrap">{{ formatMoney(filteredAccountDebitTotal) }}</td>
                <td class="text-end font-monospace text-nowrap">{{ formatMoney(filteredAccountCreditTotal) }}</td>
                <td
                  class="text-end font-monospace text-nowrap"
                  :class="!hasActiveDetailFilters ? balanceTextClass(currentAccount.currentBalance) : ''"
                >
                  {{ hasActiveDetailFilters ? '—' : formatMoney(currentAccount.currentBalance) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </template>
    </section>

    <!-- BALANCE VIEW (/transactions), ACCOUNTS OVERVIEW (/transactions/accounts) & BOOKINGS VIEW (/transactions/bookings) -->
    <section v-else>
      <div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
        <div>
          <h1 class="h3 mb-1">
            {{ isBalanceView ? 'Balans & Winst en Verlies' : isBookingsView ? 'Boekingen' : 'Grootboekrekeningen' }}
          </h1>
          <p class="text-body-secondary mb-0">
            <template v-if="header.companyName">{{ header.companyName }} · </template>
            Boekjaar {{ activeYear }}
            <template v-if="isBalanceView">
              <span class="d-print-none balance-account-count-summary">
                · {{ nonZeroAccounts.length }} rekeningen met saldo
              </span>
            </template>
            <template v-else-if="isBookingsView">
              · {{ sortedTransactions.length }} boekingen
              <template v-if="activeYearOption?.fileName"> · {{ activeYearOption.fileName }}</template>
            </template>
            <template v-else>
              · {{ activeAccounts.length }} actieve rekeningen · {{ transactions.length }} transacties
            </template>
          </p>
        </div>

        <div class="d-flex flex-wrap align-items-center gap-2 d-print-none tx-view-controls">
          <!-- Segmented View Switcher -->
          <nav aria-label="Weergave boekhouding" class="tx-view-switcher">
            <div class="nav nav-pills bg-body border rounded p-1 shadow-sm">
              <a
                :href="buildUrlWithParams('/transactions', { year: activeYear })"
                class="nav-link py-1 px-3 small fw-semibold"
                :class="{ active: isBalanceView }"
                :aria-current="isBalanceView ? 'page' : undefined"
                @click.prevent="goToBalanceView"
              >
                Balans
              </a>
              <a
                :href="buildUrlWithParams('/transactions/accounts', { year: activeYear, q: accountSearchQuery.trim() })"
                class="nav-link py-1 px-3 small fw-semibold"
                :class="{ active: isAccountsOverviewView }"
                :aria-current="isAccountsOverviewView ? 'page' : undefined"
                @click.prevent="goToAccountsOverview"
              >
                Rekeningen
              </a>
              <a
                :href="buildUrlWithParams('/transactions/bookings', { year: activeYear, ...bookingQueryParams() })"
                class="nav-link py-1 px-3 small fw-semibold"
                :class="{ active: isBookingsView }"
                :aria-current="isBookingsView ? 'page' : undefined"
                @click.prevent="goToBookingsView"
              >
                Boekingen
              </a>
            </div>
          </nav>

          <!-- Compact Audit File Switcher Dropdown -->
          <div class="d-flex align-items-center gap-2 bg-body border rounded px-2 py-1 shadow-sm audit-file-filter">
            <label for="auditYearSelectOverview" class="form-label mb-0 small text-body-secondary text-nowrap">
              Auditbestand
            </label>
            <select
              id="auditYearSelectOverview"
              :value="activeYear"
              class="form-select form-select-sm w-auto"
              aria-label="Selecteer boekjaar of auditbestand"
              @change="onYearSelectChange"
            >
              <option v-for="option in availableYears" :key="option.year" :value="option.year">
                {{ yearOptionLabel(option) }}
              </option>
            </select>
          </div>
        </div>
      </div>

      <p v-if="loading" class="text-body-secondary">Boekhouding voor {{ activeYear }} laden…</p>

      <!-- BALANCE & PROFIT/LOSS VIEW (/transactions/balance) -->
      <template v-else-if="isBalanceView">
        <div
          v-for="section in balanceSections"
          :key="section.key"
          class="mb-4 balance-section"
          :data-section="section.key"
        >
          <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2 pb-1 border-bottom balance-section-header">
            <div class="d-flex align-items-center gap-2 flex-wrap">
              <h2 class="h4 mb-0">{{ section.title }}</h2>
              <span class="badge text-bg-light border text-body-secondary fw-normal d-print-none balance-section-count">
                {{ section.totalAccountCount }} {{ section.totalAccountCount === 1 ? 'rekening' : 'rekeningen' }}
              </span>
            </div>
            <div class="d-flex flex-wrap align-items-center gap-3 small">
              <span class="d-print-none balance-section-totals">
                <span class="text-body-secondary">Totaal debet:</span>
                <strong class="font-monospace ms-1">{{ formatMoney(section.debitTotal) }}</strong>
              </span>
              <span class="d-print-none balance-section-totals">
                <span class="text-body-secondary">Totaal credit:</span>
                <strong class="font-monospace ms-1">{{ formatMoney(section.creditTotal) }}</strong>
              </span>
              <span
                v-if="!section.isBalanced"
                class="badge fw-semibold font-monospace"
                :class="sectionDiffBadgeClass(section)"
              >
                {{ section.diffLabel }}: {{ formatMoney(section.diffAmount) }}
              </span>
              <span
                v-else
                class="badge text-bg-success-subtle text-success-emphasis border border-success-subtle fw-normal d-print-none balance-equilibrium-badge"
              >
                In evenwicht
              </span>
            </div>
          </div>

          <div class="row g-3 balance-columns">
            <!-- Debet Column -->
            <div class="col-12 col-lg-6 balance-column">
              <div class="card shadow-sm h-100 d-flex flex-column balance-card">
                <div class="card-header bg-body-tertiary d-flex justify-content-between align-items-center py-2 px-3">
                  <div>
                    <span class="fw-semibold">Debet</span>
                    <span v-if="section.debitSubtitle" class="text-body-secondary small ms-2">
                      · {{ section.debitSubtitle }}
                    </span>
                  </div>
                  <div class="d-flex align-items-center gap-2 d-print-none balance-card-header-summary">
                    <span class="badge text-bg-light border text-body-secondary fw-normal">
                      {{ section.debitAccounts.length }} {{ section.debitAccounts.length === 1 ? 'rekening' : 'rekeningen' }}
                    </span>
                    <span
                      class="font-monospace fw-semibold small"
                      :class="balanceTextClass(section.debitTotal)"
                    >
                      {{ formatMoney(section.debitTotal) }}
                    </span>
                  </div>
                </div>
                <div class="table-responsive flex-grow-1">
                  <table class="table table-hover table-sm align-middle mb-0 balance-table">
                    <thead class="table-light">
                      <tr>
                        <th class="ps-3 balance-col-code">Rekening</th>
                        <th>Omschrijving</th>
                        <th class="text-end pe-3 balance-col-amount">Saldo</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="item in section.debitAccounts"
                        :key="item.id"
                        class="clickable-row"
                        tabindex="0"
                        role="button"
                        @click="openAccount(item.id, { fromBalance: true })"
                        @keydown.enter.prevent="openAccount(item.id, { fromBalance: true })"
                        @keydown.space.prevent="openAccount(item.id, { fromBalance: true })"
                      >
                        <td class="ps-3 font-monospace fw-semibold">
                          <a
                            :href="buildUrlWithParams(`/transactions/accounts/${encodeURIComponent(item.id)}`, { year: activeYear, from: 'balance' })"
                            class="text-decoration-none fw-bold font-monospace"
                            tabindex="-1"
                            @click="onAccountLinkClick($event, item.id, { fromBalance: true })"
                          >
                            {{ item.id }}
                          </a>
                        </td>
                        <td>{{ item.description || item.id }}</td>
                        <td
                          class="text-end pe-3 font-monospace fw-semibold text-nowrap"
                          :class="balanceTextClass(item.displayAmount)"
                        >
                          {{ formatMoney(item.displayAmount) }}
                        </td>
                      </tr>
                      <tr v-if="!section.debitAccounts.length">
                        <td colspan="3" class="text-body-secondary py-3 ps-3">Geen rekeningen aan de debetzijde.</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div class="card-footer bg-body-tertiary fw-semibold d-flex justify-content-between align-items-center py-2 px-3 mt-auto border-top">
                  <span>
                    Totaal debet <span class="d-print-none balance-footer-count">({{ section.debitAccounts.length }} {{ section.debitAccounts.length === 1 ? 'rekening' : 'rekeningen' }})</span>
                  </span>
                  <span
                    class="font-monospace text-nowrap"
                    :class="balanceTextClass(section.debitTotal)"
                  >
                    {{ formatMoney(section.debitTotal) }}
                  </span>
                </div>
              </div>
            </div>

            <!-- Credit Column -->
            <div class="col-12 col-lg-6 balance-column">
              <div class="card shadow-sm h-100 d-flex flex-column balance-card">
                <div class="card-header bg-body-tertiary d-flex justify-content-between align-items-center py-2 px-3">
                  <div>
                    <span class="fw-semibold">Credit</span>
                    <span v-if="section.creditSubtitle" class="text-body-secondary small ms-2">
                      · {{ section.creditSubtitle }}
                    </span>
                  </div>
                  <div class="d-flex align-items-center gap-2 d-print-none balance-card-header-summary">
                    <span class="badge text-bg-light border text-body-secondary fw-normal">
                      {{ section.creditAccounts.length }} {{ section.creditAccounts.length === 1 ? 'rekening' : 'rekeningen' }}
                    </span>
                    <span
                      class="font-monospace fw-semibold small"
                      :class="balanceTextClass(section.creditTotal)"
                    >
                      {{ formatMoney(section.creditTotal) }}
                    </span>
                  </div>
                </div>
                <div class="table-responsive flex-grow-1">
                  <table class="table table-hover table-sm align-middle mb-0 balance-table">
                    <thead class="table-light">
                      <tr>
                        <th class="ps-3 balance-col-code">Rekening</th>
                        <th>Omschrijving</th>
                        <th class="text-end pe-3 balance-col-amount">Saldo</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="item in section.creditAccounts"
                        :key="item.id"
                        class="clickable-row"
                        tabindex="0"
                        role="button"
                        @click="openAccount(item.id, { fromBalance: true })"
                        @keydown.enter.prevent="openAccount(item.id, { fromBalance: true })"
                        @keydown.space.prevent="openAccount(item.id, { fromBalance: true })"
                      >
                        <td class="ps-3 font-monospace fw-semibold">
                          <a
                            :href="buildUrlWithParams(`/transactions/accounts/${encodeURIComponent(item.id)}`, { year: activeYear, from: 'balance' })"
                            class="text-decoration-none fw-bold font-monospace"
                            tabindex="-1"
                            @click="onAccountLinkClick($event, item.id, { fromBalance: true })"
                          >
                            {{ item.id }}
                          </a>
                        </td>
                        <td>{{ item.description || item.id }}</td>
                        <td
                          class="text-end pe-3 font-monospace fw-semibold text-nowrap"
                          :class="balanceTextClass(item.displayAmount)"
                        >
                          {{ formatMoney(item.displayAmount) }}
                        </td>
                      </tr>
                      <tr v-if="!section.creditAccounts.length">
                        <td colspan="3" class="text-body-secondary py-3 ps-3">Geen rekeningen aan de creditzijde.</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div class="card-footer bg-body-tertiary fw-semibold d-flex justify-content-between align-items-center py-2 px-3 mt-auto border-top">
                  <span>
                    Totaal credit <span class="d-print-none balance-footer-count">({{ section.creditAccounts.length }} {{ section.creditAccounts.length === 1 ? 'rekening' : 'rekeningen' }})</span>
                  </span>
                  <span
                    class="font-monospace text-nowrap"
                    :class="balanceTextClass(section.creditTotal)"
                  >
                    {{ formatMoney(section.creditTotal) }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- BOOKINGS VIEW (/transactions/bookings) -->
      <template v-else-if="isBookingsView">
        <!-- Debounced Filter Bar -->
        <form class="card mb-3 shadow-sm d-print-none tx-filter-form" @submit.prevent>
          <div class="card-body py-2 px-3">
            <div class="row g-2 align-items-end">
              <div class="col-12 col-md-6 col-xl-3">
                <label for="bookingFilterText" class="form-label small mb-1 text-nowrap">Zoek in omschrijving</label>
                <input
                  id="bookingFilterText"
                  v-model="bookingFilterDraft.text"
                  type="search"
                  class="form-control form-control-sm"
                  placeholder="Omschrijving, relatie, document, rekening of ID"
                  @input="scheduleBookingFilters()"
                />
              </div>
              <div class="col-12 col-sm-4 col-md-6 col-xl-2">
                <label class="form-label small mb-1 text-nowrap d-block">Filter bedrag op</label>
                <div class="btn-group btn-group-sm w-100" role="group" aria-label="Filter bedrag op transactie of regel">
                  <button
                    type="button"
                    class="btn"
                    :class="bookingFilterDraft.amountMode !== 'line' ? 'btn-primary' : 'btn-outline-secondary'"
                    :aria-pressed="bookingFilterDraft.amountMode !== 'line'"
                    @click="setBookingAmountMode('transaction')"
                  >
                    Transactie
                  </button>
                  <button
                    type="button"
                    class="btn"
                    :class="bookingFilterDraft.amountMode === 'line' ? 'btn-primary' : 'btn-outline-secondary'"
                    :aria-pressed="bookingFilterDraft.amountMode === 'line'"
                    @click="setBookingAmountMode('line')"
                  >
                    Regel
                  </button>
                </div>
              </div>
              <div class="col-6 col-sm-4 col-md-3 col-xl-1">
                <label for="bookingFilterAmountMin" class="form-label small mb-1 text-nowrap">Vanaf bedrag</label>
                <input
                  id="bookingFilterAmountMin"
                  v-model="bookingFilterDraft.amountMin"
                  type="number"
                  step="0.01"
                  min="0"
                  class="form-control form-control-sm"
                  placeholder="0,00"
                  @input="scheduleBookingFilters()"
                />
              </div>
              <div class="col-6 col-sm-4 col-md-3 col-xl-1">
                <label for="bookingFilterAmountMax" class="form-label small mb-1 text-nowrap">Tot bedrag</label>
                <input
                  id="bookingFilterAmountMax"
                  v-model="bookingFilterDraft.amountMax"
                  type="number"
                  step="0.01"
                  min="0"
                  class="form-control form-control-sm"
                  placeholder="Max"
                  @input="scheduleBookingFilters()"
                />
              </div>
              <div class="col-6 col-md-3 col-xl-2">
                <label for="bookingFilterDateFrom" class="form-label small mb-1 text-nowrap">Vanaf datum</label>
                <input
                  id="bookingFilterDateFrom"
                  v-model="bookingFilterDraft.dateFrom"
                  type="date"
                  :min="header.startDate || (activeYear ? `${activeYear}-01-01` : undefined)"
                  :max="header.endDate || (activeYear ? `${activeYear}-12-31` : undefined)"
                  class="form-control form-control-sm"
                  @input="scheduleBookingFilters()"
                  @change="scheduleBookingFilters({ immediate: true })"
                />
              </div>
              <div class="col-6 col-md-3 col-xl-2">
                <label for="bookingFilterDateTo" class="form-label small mb-1 text-nowrap">T/m datum</label>
                <input
                  id="bookingFilterDateTo"
                  v-model="bookingFilterDraft.dateTo"
                  type="date"
                  :min="header.startDate || (activeYear ? `${activeYear}-01-01` : undefined)"
                  :max="header.endDate || (activeYear ? `${activeYear}-12-31` : undefined)"
                  class="form-control form-control-sm"
                  @input="scheduleBookingFilters()"
                  @change="scheduleBookingFilters({ immediate: true })"
                />
              </div>
              <div class="col-12 col-xl-1 d-grid">
                <button
                  type="button"
                  class="btn btn-sm btn-outline-secondary"
                  :disabled="!hasActiveBookingFilters"
                  @click="resetBookingFilters"
                >
                  Reset
                </button>
              </div>
            </div>
          </div>
        </form>

        <!-- Result Summary -->
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
          <p class="fw-semibold mb-0">
            {{ filteredBookings.length }} van {{ sortedTransactions.length }} boekingen
            <span class="text-body-secondary fw-normal">
              · debet {{ formatMoney(filteredBookingsDebitTotal) }} · credit {{ formatMoney(filteredBookingsCreditTotal) }}
            </span>
          </p>
          <span class="text-body-secondary small d-print-none">Klik op een boeking om de volledige transactie te bekijken.</span>
        </div>

        <!-- Chronological Bookings Table -->
        <div class="table-responsive bg-body border rounded shadow-sm">
          <table class="table table-hover table-sm align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th style="width: 7.5rem">Datum</th>
                <th>Omschrijving</th>
                <th class="text-end" style="width: 9.5rem">Debet</th>
                <th class="text-end" style="width: 9.5rem">Credit</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="transaction in filteredBookings"
                :key="transaction.transactionKey || transaction.transactionID"
                class="clickable-row"
                tabindex="0"
                role="button"
                @click="openTransaction(transaction.transactionID)"
                @keydown.enter.prevent="openTransaction(transaction.transactionID)"
                @keydown.space.prevent="openTransaction(transaction.transactionID)"
              >
                <td class="font-monospace text-nowrap">
                  {{ transaction.transactionDate || transaction.minEffectiveDate || '—' }}
                </td>
                <td>{{ bookingDescription(transaction) }}</td>
                <td
                  class="text-end font-monospace text-nowrap"
                  :class="balanceTextClass(transaction.debitTotal)"
                >
                  {{ formatMoney(transaction.debitTotal) }}
                </td>
                <td
                  class="text-end font-monospace text-nowrap"
                  :class="balanceTextClass(transaction.creditTotal)"
                >
                  {{ formatMoney(transaction.creditTotal) }}
                </td>
              </tr>
              <tr v-if="!filteredBookings.length">
                <td colspan="4" class="text-body-secondary py-3">
                  {{
                    hasActiveBookingFilters
                      ? 'Geen boekingen gevonden voor de geselecteerde filters.'
                      : 'Geen boekingen in dit boekjaar.'
                  }}
                </td>
              </tr>
            </tbody>
            <tfoot v-if="filteredBookings.length" class="table-light fw-semibold">
              <tr>
                <td colspan="2">
                  Totaal ({{ filteredBookings.length }} {{ filteredBookings.length === 1 ? 'boeking' : 'boekingen' }})
                </td>
                <td
                  class="text-end font-monospace text-nowrap"
                  :class="balanceTextClass(filteredBookingsDebitTotal)"
                >
                  {{ formatMoney(filteredBookingsDebitTotal) }}
                </td>
                <td
                  class="text-end font-monospace text-nowrap"
                  :class="balanceTextClass(filteredBookingsCreditTotal)"
                >
                  {{ formatMoney(filteredBookingsCreditTotal) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </template>

      <template v-else>
        <!-- Search bar with 150ms debounce -->
        <form class="row g-2 align-items-end mb-3 d-print-none tx-filter-form" @submit.prevent>
          <div class="col-sm-8 col-md-6 col-lg-5">
            <label for="accountSearchInput" class="form-label small mb-1">Zoek grootboekrekening</label>
            <div class="input-group">
              <input
                id="accountSearchInput"
                v-model="accountSearchInput"
                type="search"
                class="form-control"
                placeholder="Zoek op rekeningnummer of omschrijving…"
                @input="onAccountSearchInput"
              />
              <button
                v-if="accountSearchInput"
                type="button"
                class="btn btn-outline-secondary"
                @click="clearAccountSearch"
              >
                Wissen
              </button>
            </div>
          </div>
        </form>

        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
          <p class="fw-semibold mb-0">{{ filteredAccounts.length }} rekeningen gevonden</p>
          <span class="text-body-secondary small d-print-none">Klik op een grootboekrekening voor alle mutaties en het verloop.</span>
        </div>

        <div class="table-responsive bg-body border rounded shadow-sm">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th style="width: 7rem">Rekening</th>
                <th>Omschrijving</th>
                <th class="text-end" style="width: 7.5rem">Transacties</th>
                <th class="text-end" style="width: 9.5rem">Beginbalans</th>
                <th class="text-end" style="width: 9.5rem">Totaal debet</th>
                <th class="text-end" style="width: 9.5rem">Totaal credit</th>
                <th class="text-end" style="width: 9.5rem">Huidig saldo</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="account in filteredAccounts"
                :key="account.id"
                class="clickable-row"
                tabindex="0"
                role="button"
                @click="openAccount(account.id)"
                @keydown.enter.prevent="openAccount(account.id)"
                @keydown.space.prevent="openAccount(account.id)"
              >
                <td class="font-monospace fw-semibold">
                  <a
                    :href="buildUrlWithParams(`/transactions/accounts/${encodeURIComponent(account.id)}`, { year: activeYear, from: 'accounts' })"
                    class="text-decoration-none fw-bold font-monospace"
                    tabindex="-1"
                    @click="onAccountLinkClick($event, account.id, { fromBalance: false })"
                  >
                    {{ account.id }}
                  </a>
                </td>
                <td>
                  <span>{{ account.description || account.id }}</span>
                  <span
                    v-if="account.type"
                    class="badge ms-2 fw-normal"
                    :class="accountTypeBadgeClass(account.type)"
                  >
                    {{ accountTypeLabel(account.type) }}
                  </span>
                </td>
                <td class="text-end font-monospace">{{ account.transactionCount }}</td>
                <td
                  class="text-end font-monospace"
                  :class="balanceTextClass(account.openingBalance, { muteZero: true })"
                >
                  {{ formatMoney(account.openingBalance) }}
                </td>
                <td class="text-end font-monospace">{{ formatMoney(account.totalDebit) }}</td>
                <td class="text-end font-monospace">{{ formatMoney(account.totalCredit) }}</td>
                <td
                  class="text-end font-monospace fw-semibold"
                  :class="balanceTextClass(account.currentBalance, { muteZero: true })"
                >
                  {{ formatMoney(account.currentBalance) }}
                </td>
              </tr>
              <tr v-if="!filteredAccounts.length">
                <td colspan="7" class="text-body-secondary py-3">Geen actieve grootboekrekeningen gevonden.</td>
              </tr>
            </tbody>
            <tfoot v-if="filteredAccounts.length" class="table-light fw-semibold">
              <tr>
                <td colspan="2">Totaal ({{ filteredAccounts.length }} rekeningen)</td>
                <td class="text-end font-monospace">{{ overviewTotals.transactionCount }}</td>
                <td
                  class="text-end font-monospace"
                  :class="balanceTextClass(overviewTotals.openingBalance)"
                >
                  {{ formatMoney(overviewTotals.openingBalance) }}
                </td>
                <td class="text-end font-monospace">{{ formatMoney(overviewTotals.totalDebit) }}</td>
                <td class="text-end font-monospace">{{ formatMoney(overviewTotals.totalCredit) }}</td>
                <td
                  class="text-end font-monospace"
                  :class="balanceTextClass(overviewTotals.currentBalance)"
                >
                  {{ formatMoney(overviewTotals.currentBalance) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </template>
    </section>

    <!-- TRANSACTION DETAIL MODAL -->
    <div
      ref="txModalEl"
      class="modal invoice-modal"
      tabindex="-1"
      aria-labelledby="txModalTitle"
      aria-hidden="true"
    >
      <div class="modal-dialog modal-dialog-scrollable modal-xl">
        <div class="modal-content">
          <div class="modal-header">
            <h2 id="txModalTitle" class="modal-title h5">
              <template v-if="selectedTransaction">
                Transactie <span class="font-monospace">{{ selectedTransaction.transactionID }}</span>
                <span v-if="selectedTransaction.journalDescription" class="badge text-bg-secondary ms-2 fw-normal">
                  {{ selectedTransaction.journalID }} · {{ selectedTransaction.journalDescription }}
                </span>
              </template>
              <template v-else>Transactie</template>
            </h2>
            <button type="button" class="btn-close" aria-label="Sluiten" @click="closeTransactionModal"></button>
          </div>
          <div class="modal-body">
            <template v-if="selectedTransaction">
              <div class="row g-3 mb-3">
                <div class="col-6 col-md-2">
                  <div class="text-body-secondary small">Datum</div>
                  <div class="fw-semibold font-monospace">{{ selectedTransaction.transactionDate || '—' }}</div>
                </div>
                <div class="col-6 col-md-2">
                  <div class="text-body-secondary small">Transactie ID</div>
                  <div class="fw-semibold font-monospace">{{ selectedTransaction.transactionID }}</div>
                </div>
                <div class="col-6 col-md-2">
                  <div class="text-body-secondary small">Periode</div>
                  <div class="fw-semibold">{{ selectedTransaction.period || '—' }}</div>
                </div>
                <div class="col-6 col-md-2">
                  <div class="text-body-secondary small">Dagboek / Journaal</div>
                  <div class="fw-semibold">
                    {{ selectedTransaction.journalID }}
                    <template v-if="selectedTransaction.journalDescription">
                      · {{ selectedTransaction.journalDescription }}
                    </template>
                  </div>
                </div>
                <div class="col-6 col-md-2">
                  <div class="text-body-secondary small">Totaal debet</div>
                  <div class="fw-semibold font-monospace">{{ formatMoney(selectedTransaction.debitTotal) }}</div>
                </div>
                <div class="col-6 col-md-2">
                  <div class="text-body-secondary small">Totaal credit</div>
                  <div class="fw-semibold font-monospace">{{ formatMoney(selectedTransaction.creditTotal) }}</div>
                </div>
              </div>

              <h3 class="h6 mb-2">Transactieregels ({{ (selectedTransaction.lines || []).length }})</h3>
              <div class="table-responsive border rounded">
                <table class="table table-sm align-middle mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Datum</th>
                      <th>Rekening</th>
                      <th>Relatie / Leverancier</th>
                      <th>Document</th>
                      <th>Omschrijving</th>
                      <th class="text-end">Debet</th>
                      <th class="text-end">Credit</th>
                      <th>BTW</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="line in selectedTransaction.lines || []"
                      :key="line.recordID"
                      :class="{ 'table-primary': accountIdFromPath && String(line.accountID) === accountIdFromPath }"
                    >
                      <td class="font-monospace text-nowrap">
                        {{ line.effectiveDate || selectedTransaction.transactionDate }}
                      </td>
                      <td>
                        <a
                          v-if="line.accountID"
                          :href="buildUrlWithParams(`/transactions/accounts/${encodeURIComponent(line.accountID)}`, { year: activeYear, from: resolveFromSource() })"
                          class="btn btn-link btn-sm p-0 text-start"
                          @click="onModalAccountLinkClick($event, line.accountID)"
                        >
                          <span class="font-monospace fw-semibold">{{ line.accountID }}</span>
                          <span v-if="line.accountDescription" class="text-body-secondary ms-1">
                            · {{ line.accountDescription }}
                          </span>
                        </a>
                        <span v-else>—</span>
                      </td>
                      <td>{{ line.supplierName || line.custSupID || '—' }}</td>
                      <td class="font-monospace">{{ line.documentID || '—' }}</td>
                      <td>{{ line.description || '—' }}</td>
                      <td class="text-end font-monospace text-nowrap">
                        {{ line.debitAmount ? formatMoney(line.debitAmount) : '—' }}
                      </td>
                      <td class="text-end font-monospace text-nowrap">
                        {{ line.creditAmount ? formatMoney(line.creditAmount) : '—' }}
                      </td>
                      <td class="text-nowrap">{{ formatVat(line.vat) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

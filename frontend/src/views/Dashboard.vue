<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { ipOnly, verNewer } from '../ip'
import UChart from '../components/UChart.vue'

const props = defineProps({ hosts: Array, hostId: Number })
const emit = defineEmits(['update:hostId'])

const range = ref('1h')
const hist = ref(null)
const live = ref(null)
const err = ref('')
const agent = ref(null)     // { ips, version, ... } from the host's metrics agent
const sys = ref(null)       // { ui, latest, update_available } — web UI self-version
const updating = ref('')    // '' | 'ui' | 'agent' | 'router'
const updateMsg = ref('')
const checking = ref(false) // "Check now" (force GitHub re-fetch) in flight
let liveTimer = null
let histTimer = null

const ranges = [
  { id: '1h', label: '1h' },
  { id: '6h', label: '6h' },
  { id: '24h', label: '24h' },
  { id: '48h', label: '2d' },
]

function fmtBytes(v, suffix = '') {
  if (v == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}${suffix}`
}
function fmtUptime(s) {
  if (s == null) return '—'
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`
}
function pct(used, total) {
  return total ? Math.round((used / total) * 100) : null
}

async function loadHistory() {
  if (!props.hostId) return
  try {
    hist.value = await api.history(props.hostId, range.value)
    err.value = ''
  } catch (e) { err.value = e.message }
}
async function loadLive() {
  if (!props.hostId) return
  try { live.value = await api.live(props.hostId) } catch (e) { err.value = e.message }
}
async function loadAgent() {
  agent.value = null
  if (!props.hostId) return
  try { agent.value = await api.agentInfo(props.hostId) } catch { /* agent down: hide panel */ }
}
async function loadVersion() {
  try { sys.value = await api.version() } catch { /* offline: no update prompt */ }
}
async function checkNow() {
  checking.value = true
  updateMsg.value = ''
  try {
    sys.value = await api.version(true) // force: skip the backend's 1h release cache
  } catch (e) { updateMsg.value = 'Check failed: ' + e.message } finally { checking.value = false }
}

const agentUpdate = computed(() =>
  !!(sys.value?.latest && agent.value?.version && verNewer(sys.value.latest, agent.value.version)))

const routerVersion = computed(() => live.value?.status?.version || null)
const routerUpdate = computed(() =>
  !!(sys.value?.router_latest && routerVersion.value && verNewer(sys.value.router_latest, routerVersion.value)))

async function doUpdateUi() {
  if (!confirm('Update the web UI to ' + sys.value.latest + '? It will restart itself.')) return
  updating.value = 'ui'
  try {
    await api.updateUi()
    updateMsg.value = 'Web UI is updating — it will restart. Reload this page in ~30–60s.'
  } catch (e) { updateMsg.value = 'Update failed: ' + e.message; updating.value = '' }
}
async function doUpdateAgent() {
  if (!confirm('Update the agent on this host to ' + sys.value.latest + '?')) return
  updating.value = 'agent'
  try {
    await api.updateAgent(props.hostId)
    updateMsg.value = 'Agent is updating — it will restart. Version refreshes shortly.'
    setTimeout(() => { loadAgent(); updating.value = '' }, 15000)
  } catch (e) { updateMsg.value = 'Update failed: ' + e.message; updating.value = '' }
}
async function doUpdateRouter() {
  if (!confirm('Update sni-router on this host to ' + sys.value.router_latest +
               '? It re-execs into the new binary — active connections drop.')) return
  updating.value = 'router'
  try {
    await api.updateRouter(props.hostId)
    updateMsg.value = 'sni-router update requested — it re-execs to apply. Version refreshes shortly.'
    setTimeout(() => { loadLive(); updating.value = '' }, 15000)
  } catch (e) { updateMsg.value = 'Update failed: ' + e.message; updating.value = '' }
}

const cpuData = computed(() => hist.value ? [hist.value.ts, hist.value.cpu_pct] : [[]])
const memData = computed(() => {
  if (!hist.value) return [[]]
  const p = hist.value.mem_used.map((u, i) => pct(u, hist.value.mem_total[i]))
  return [hist.value.ts, p]
})
const netData = computed(() => hist.value ? [hist.value.ts, hist.value.net_rx_rate, hist.value.net_tx_rate] : [[]])
const connData = computed(() => hist.value ? [hist.value.ts, hist.value.conns_active] : [[]])

const hasData = computed(() => hist.value && hist.value.ts.length > 1)

// Tiles from latest sample + live status
const L = computed(() => live.value?.latest || {})
const tiles = computed(() => [
  { label: 'CPU', value: L.value.cpu_pct != null ? L.value.cpu_pct + ' %' : '—', accent: '#818cf8' },
  { label: 'Memory', value: L.value.mem_total ? `${fmtBytes(L.value.mem_used)} / ${pct(L.value.mem_used, L.value.mem_total)}%` : '—', accent: '#34d399' },
  { label: 'Disk', value: L.value.disk_total ? `${fmtBytes(L.value.disk_used)} / ${pct(L.value.disk_used, L.value.disk_total)}%` : '—', accent: '#f59e0b' },
  { label: 'Active conns', value: L.value.conns_active ?? '—', accent: '#a855f7' },
  { label: 'Uptime', value: fmtUptime(live.value?.status?.uptime_secs), accent: '#22d3ee' },
  { label: 'Version', value: live.value?.status?.version || '—', accent: '#f472b6' },
])

watch(() => props.hostId, () => { hist.value = null; live.value = null; loadHistory(); loadLive(); loadAgent() })
watch(range, loadHistory)

onMounted(() => {
  loadHistory(); loadLive(); loadAgent(); loadVersion()
  liveTimer = setInterval(loadLive, 5000)
  histTimer = setInterval(loadHistory, 15000)
})
onBeforeUnmount(() => { clearInterval(liveTimer); clearInterval(histTimer) })
</script>

<template>
  <div>
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <h1 class="text-2xl font-semibold tracking-tight text-slate-100">Dashboard</h1>
        <span v-if="live" class="flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 text-xs">
          <span class="dot" :class="live.reachable ? 'dot-ok' : 'dot-bad'"></span>
          <span class="text-slate-400">{{ live.reachable ? 'reachable' : 'unreachable' }}</span>
        </span>
      </div>
      <div class="segment">
        <button v-for="r in ranges" :key="r.id"
          class="segment-btn" :class="{ 'segment-btn--active': range === r.id }"
          @click="range = r.id">{{ r.label }}</button>
      </div>
    </div>

    <p v-if="err" class="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ err }}</p>
    <p v-if="!hosts.length" class="text-slate-500">No hosts. Add one in the Hosts tab.</p>

    <template v-else>
      <!-- Tiles -->
      <div class="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div v-for="t in tiles" :key="t.label" class="card card-hover overflow-hidden !p-0">
          <div class="h-0.5 w-full" :style="{ background: `linear-gradient(90deg, ${t.accent}, transparent)` }"></div>
          <div class="p-3.5">
            <div class="label mb-1.5">{{ t.label }}</div>
            <div v-if="!live" class="skeleton h-6 w-16"></div>
            <div v-else class="tabular text-lg font-semibold text-slate-100">{{ t.value }}</div>
          </div>
        </div>
      </div>

      <p v-if="!hasData" class="mb-4 text-sm text-slate-500">
        Collecting data… charts fill in as the poller samples this host (every 5s).
        Drag on a chart to zoom; double-click to reset.
      </p>

      <!-- Charts -->
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <UChart title="CPU usage" :data="cpuData"
          :series="[{ label: 'CPU %', stroke: '#818cf8', fill: 'rgba(129,140,248,.16)' }]"
          :yfmt="(v) => (v == null ? '—' : v + '%')" />
        <UChart title="Memory usage" :data="memData"
          :series="[{ label: 'Mem %', stroke: '#34d399', fill: 'rgba(52,211,153,.16)' }]"
          :yfmt="(v) => (v == null ? '—' : v + '%')" />
        <UChart title="Network I/O" :data="netData"
          :series="[{ label: 'In', stroke: '#22d3ee' }, { label: 'Out', stroke: '#f59e0b' }]"
          :yfmt="(v) => fmtBytes(v, '/s')" />
        <UChart title="Active connections" :data="connData"
          :series="[{ label: 'Conns', stroke: '#a855f7', fill: 'rgba(168,85,247,.16)' }]"
          :yfmt="(v) => (v == null ? '—' : v)" />
      </div>

      <!-- System: versions/update + available IPs -->
      <div class="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div class="card">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-sm font-semibold uppercase tracking-wider text-slate-400">Software version</h3>
            <button class="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-slate-400 transition-colors hover:bg-[var(--surface-2)] hover:text-slate-200 disabled:opacity-50"
              :disabled="checking" @click="checkNow" title="Re-check GitHub for the latest releases now">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'animate-spin': checking }"><path d="M23 4v6h-6M1 20v-6h6" /><path d="M3.5 9a9 9 0 0114.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0020.5 15" /></svg>
              {{ checking ? 'Checking…' : 'Check now' }}
            </button>
          </div>
          <div class="flex items-center justify-between gap-3 border-b border-[var(--border)] py-2.5">
            <div>
              <div class="text-sm font-medium text-slate-200">Web UI</div>
              <div class="text-xs text-slate-500">
                installed {{ sys?.ui || '—' }}<span v-if="sys?.latest"> · latest {{ sys.latest }}</span>
              </div>
            </div>
            <button v-if="sys?.update_available" class="btn-primary !py-1.5" :disabled="!!updating"
              @click="doUpdateUi">{{ updating === 'ui' ? 'Updating…' : 'Update' }}</button>
            <span v-else-if="sys" class="rounded-md bg-emerald-500/10 px-2 py-1 text-xs text-emerald-400">up to date</span>
          </div>
          <div class="flex items-center justify-between gap-3 border-b border-[var(--border)] py-2.5">
            <div>
              <div class="text-sm font-medium text-slate-200">Agent (this host)</div>
              <div class="text-xs text-slate-500">
                {{ agent?.version ? 'installed ' + agent.version : 'agent offline / not reporting' }}
                <span v-if="agent?.version && sys?.latest"> · latest {{ sys.latest }}</span>
              </div>
            </div>
            <button v-if="agentUpdate" class="btn-primary !py-1.5" :disabled="!!updating"
              @click="doUpdateAgent">{{ updating === 'agent' ? 'Updating…' : 'Update' }}</button>
            <span v-else-if="agent?.version" class="rounded-md bg-emerald-500/10 px-2 py-1 text-xs text-emerald-400">up to date</span>
          </div>
          <div class="flex items-center justify-between gap-3 py-2.5">
            <div>
              <div class="text-sm font-medium text-slate-200">sni-router (this host)</div>
              <div class="text-xs text-slate-500">
                {{ routerVersion ? 'installed ' + routerVersion : 'router offline / no version' }}
                <span v-if="sys?.router_latest"> · latest {{ sys.router_latest }}</span>
              </div>
            </div>
            <button v-if="routerUpdate" class="btn-primary !py-1.5" :disabled="!!updating"
              @click="doUpdateRouter">{{ updating === 'router' ? 'Updating…' : 'Update' }}</button>
            <span v-else-if="routerVersion" class="rounded-md bg-emerald-500/10 px-2 py-1 text-xs text-emerald-400">up to date</span>
          </div>
          <p v-if="updateMsg" class="mt-2 rounded-xl border border-[var(--accent-strong)]/20 bg-[var(--accent-strong)]/10 px-3 py-2 text-sm text-[var(--accent)]">{{ updateMsg }}</p>
        </div>

        <div class="card">
          <h3 class="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
            IP addresses available on this server
          </h3>
          <div v-if="agent?.ips?.length" class="flex flex-wrap gap-2">
            <span v-for="c in agent.ips" :key="c"
              class="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 font-mono text-sm text-slate-300">{{ ipOnly(c) }}</span>
          </div>
          <p v-else class="text-sm text-slate-500">No agent data — install/enable the metrics agent on this host.</p>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import UChart from '../components/UChart.vue'

const props = defineProps({ hosts: Array, hostId: Number })
const emit = defineEmits(['update:hostId'])

const range = ref('1h')
const hist = ref(null)
const live = ref(null)
const err = ref('')
let liveTimer = null
let histTimer = null

const ranges = [
  { id: '1h', label: '1 hour' },
  { id: '6h', label: '6 hours' },
  { id: '24h', label: '24 hours' },
  { id: '48h', label: '2 days' },
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
  { label: 'CPU', value: L.value.cpu_pct != null ? L.value.cpu_pct + ' %' : '—' },
  { label: 'Memory', value: L.value.mem_total ? `${fmtBytes(L.value.mem_used)} / ${pct(L.value.mem_used, L.value.mem_total)}%` : '—' },
  { label: 'Disk', value: L.value.disk_total ? `${fmtBytes(L.value.disk_used)} / ${pct(L.value.disk_used, L.value.disk_total)}%` : '—' },
  { label: 'Active conns', value: L.value.conns_active ?? '—' },
  { label: 'Uptime', value: fmtUptime(live.value?.status?.uptime_secs) },
  { label: 'Version', value: live.value?.status?.version || '—' },
])

watch(() => props.hostId, () => { hist.value = null; live.value = null; loadHistory(); loadLive() })
watch(range, loadHistory)

onMounted(() => {
  loadHistory(); loadLive()
  liveTimer = setInterval(loadLive, 5000)
  histTimer = setInterval(loadHistory, 15000)
})
onBeforeUnmount(() => { clearInterval(liveTimer); clearInterval(histTimer) })
</script>

<template>
  <div>
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-semibold text-slate-100">Dashboard</h1>
      <div class="flex items-center gap-3">
        <span v-if="live" class="flex items-center gap-2 text-sm">
          <span class="h-2.5 w-2.5 rounded-full" :class="live.reachable ? 'bg-emerald-500' : 'bg-red-500'"></span>
          <span class="text-slate-400">{{ live.reachable ? 'reachable' : 'unreachable' }}</span>
        </span>
        <select class="input w-auto" :value="hostId" @change="emit('update:hostId', Number($event.target.value))">
          <option v-for="h in hosts" :key="h.id" :value="h.id">{{ h.name }}</option>
        </select>
        <div class="flex overflow-hidden rounded-lg border border-slate-700">
          <button v-for="r in ranges" :key="r.id"
            class="px-3 py-2 text-sm transition-colors"
            :class="range === r.id ? 'bg-brand text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'"
            @click="range = r.id">{{ r.label }}</button>
        </div>
      </div>
    </div>

    <p v-if="err" class="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ err }}</p>
    <p v-if="!hosts.length" class="text-slate-500">No hosts. Add one in the Hosts tab.</p>

    <template v-else>
      <!-- Tiles -->
      <div class="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div v-for="t in tiles" :key="t.label" class="card">
          <div class="label">{{ t.label }}</div>
          <div class="text-lg font-semibold text-slate-100">{{ t.value }}</div>
        </div>
      </div>

      <p v-if="!hasData" class="mb-4 text-sm text-slate-500">
        Collecting data… charts fill in as the poller samples this host (every 5s).
        Drag on a chart to zoom; double-click to reset.
      </p>

      <!-- Charts -->
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <UChart title="CPU usage" :data="cpuData"
          :series="[{ label: 'CPU %', stroke: '#6366f1', fill: 'rgba(99,102,241,.15)' }]"
          :yfmt="(v) => (v == null ? '—' : v + '%')" />
        <UChart title="Memory usage" :data="memData"
          :series="[{ label: 'Mem %', stroke: '#10b981', fill: 'rgba(16,185,129,.15)' }]"
          :yfmt="(v) => (v == null ? '—' : v + '%')" />
        <UChart title="Network I/O" :data="netData"
          :series="[{ label: 'In', stroke: '#38bdf8' }, { label: 'Out', stroke: '#f59e0b' }]"
          :yfmt="(v) => fmtBytes(v, '/s')" />
        <UChart title="Active connections" :data="connData"
          :series="[{ label: 'Conns', stroke: '#a78bfa', fill: 'rgba(167,139,250,.15)' }]"
          :yfmt="(v) => (v == null ? '—' : v)" />
      </div>
    </template>
  </div>
</template>

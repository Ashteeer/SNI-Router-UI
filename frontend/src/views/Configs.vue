<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'
import jsyaml from 'js-yaml'
import { api } from '../api'
import { cidrRange } from '../ip'
import Editor from '../components/Editor.vue'
import VisualConfig from '../components/VisualConfig.vue'

const props = defineProps({ hosts: Array, hostId: Number })
const emit = defineEmits(['update:hostId'])

const subtab = ref('visual')
const model = ref(null)
const yamlText = ref('')
const parseErr = ref('')
const loadErr = ref('')
const result = ref(null)
const busy = ref('')
const ips = ref([])
let applying = false

// Drop null/undefined so an absent section (e.g. `tls`) round-trips as *nothing*
// rather than the literal `tls: null`, which sni-router would reject on save.
function clean(v) {
  if (Array.isArray(v)) return v.map(clean).filter((x) => x != null)
  if (v && typeof v === 'object') {
    const out = {}
    for (const [k, val] of Object.entries(v)) {
      const c = clean(val)
      if (c != null) out[k] = c
    }
    return out
  }
  return v
}
function dump(m) {
  return jsyaml.dump(clean(m) ?? {}, { lineWidth: -1, noRefs: true, sortKeys: false })
}

function applyText(text) {
  try {
    const parsed = jsyaml.load(text) || {}
    applying = true
    model.value = parsed
    parseErr.value = ''
    nextTick(() => { applying = false })
  } catch (e) {
    parseErr.value = e.message
  }
}

async function load() {
  result.value = null
  loadErr.value = ''
  model.value = null
  if (!props.hostId) return
  try {
    const text = await api.getConfig(props.hostId)
    yamlText.value = text
    applyText(text)
    // re-emit through the null-stripping dumper so the manual view starts clean
    if (!parseErr.value && model.value) yamlText.value = dump(model.value)
  } catch (e) {
    loadErr.value = e.message
  }
}

async function loadIps() {
  ips.value = []
  if (!props.hostId) return
  try {
    const a = await api.agentInfo(props.hostId)
    ips.value = a.ips || []
  } catch { /* agent may be down — just hide the IP hint */ }
}

// user edits in the manual editor -> parse into the model
function onEditorInput(text) {
  yamlText.value = text
  applyText(text)
}

// visual edits mutate the model -> re-serialize to the editor (null-stripped)
watch(model, () => {
  if (applying || !model.value) return
  try {
    yamlText.value = dump(model.value)
  } catch { /* keep last good text */ }
}, { deep: true })

watch(() => props.hostId, () => { load(); loadIps() })
onMounted(() => { load(); loadIps() })

async function save() {
  busy.value = 'save'
  result.value = null
  try {
    result.value = { ok: true, ...(await api.putConfig(props.hostId, yamlText.value)) }
  } catch (e) {
    result.value = { ok: false, ...(e.data && typeof e.data === 'object' ? e.data : { error: e.message }) }
  } finally {
    busy.value = ''
  }
}

async function restart() {
  if (!confirm('Restart the router? Active connections may drop.')) return
  busy.value = 'restart'
  result.value = null
  try {
    result.value = { ok: true, ...(await api.restart(props.hostId)) }
  } catch (e) {
    result.value = { ok: false, error: e.message }
  } finally {
    busy.value = ''
  }
}

const currentHost = () => props.hosts.find((h) => h.id === props.hostId)
</script>

<template>
  <div>
    <div v-if="ips.length" class="card mb-4 !py-3">
      <div class="label mb-1.5">IP addresses available on this server</div>
      <div class="flex flex-wrap gap-2">
        <span v-for="c in ips" :key="c"
          class="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 font-mono text-sm text-slate-300">{{ cidrRange(c) }}</span>
      </div>
    </div>

    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <h1 class="text-2xl font-semibold tracking-tight text-slate-100">Config</h1>
        <div class="segment">
          <button class="segment-btn" :class="{ 'segment-btn--active': subtab === 'visual' }"
            @click="subtab = 'visual'">Visual</button>
          <button class="segment-btn" :class="{ 'segment-btn--active': subtab === 'manual' }"
            @click="subtab = 'manual'">Manual</button>
        </div>
      </div>
      <div class="flex flex-1 items-center justify-end gap-2 sm:flex-none">
        <button class="btn-ghost" :disabled="!!busy" @click="load">Reload</button>
        <button class="btn-primary" :disabled="busy || !!parseErr" @click="save">
          {{ busy === 'save' ? 'Saving…' : 'Save' }}
        </button>
        <button class="btn-danger" :disabled="busy || !currentHost()?.has_token" @click="restart"
          :title="currentHost()?.has_token ? '' : 'Needs an API token'">
          {{ busy === 'restart' ? 'Restarting…' : 'Restart' }}
        </button>
      </div>
    </div>

    <p v-if="loadErr" class="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ loadErr }}</p>
    <p v-if="parseErr" class="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-sm text-amber-400">
      YAML parse error: {{ parseErr }} — the visual view is paused until it's valid.
    </p>

    <!-- Save/restart result -->
    <div v-if="result" class="mb-4 rounded-xl border px-3 py-2 text-sm"
         :class="result.ok ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400' : 'border-red-500/20 bg-red-500/10 text-red-400'">
      <template v-if="result.ok">
        Applied: <b>{{ result.applied || 'ok' }}</b>
        <span v-if="result.downtime !== undefined"> · downtime: {{ result.downtime }}</span>
      </template>
      <template v-else>
        <div>{{ result.error || 'validation failed' }}</div>
        <ul v-if="result.errors" class="mt-1 list-disc pl-5">
          <li v-for="(er, i) in result.errors" :key="i"><code>{{ er.path }}</code>: {{ er.message }}</li>
        </ul>
      </template>
    </div>

    <p v-if="!hosts.length" class="text-slate-500">No hosts. Add one in the Hosts tab.</p>

    <div v-else>
      <VisualConfig v-show="subtab === 'visual'" :model="model" />
      <div v-show="subtab === 'manual'" class="h-[70vh]">
        <Editor :model-value="yamlText" @update:model-value="onEditorInput" />
      </div>
    </div>
  </div>
</template>

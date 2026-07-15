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
    <div v-if="ips.length" class="card mb-4 py-3">
      <div class="label mb-1">IP addresses available on this server</div>
      <div class="flex flex-wrap gap-x-4 gap-y-1 font-mono text-sm text-slate-300">
        <span v-for="c in ips" :key="c">{{ cidrRange(c) }}</span>
      </div>
    </div>

    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <select class="input w-auto" :value="hostId"
          @change="emit('update:hostId', Number($event.target.value))">
          <option v-for="h in hosts" :key="h.id" :value="h.id">{{ h.name }}</option>
        </select>
        <div class="flex overflow-hidden rounded-lg border border-slate-700">
          <button class="px-3 py-2 text-sm"
            :class="subtab === 'visual' ? 'bg-brand text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'"
            @click="subtab = 'visual'">Visual</button>
          <button class="px-3 py-2 text-sm"
            :class="subtab === 'manual' ? 'bg-brand text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'"
            @click="subtab = 'manual'">Manual</button>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn-ghost" :disabled="!!busy" @click="load">Reload</button>
        <button class="btn-primary" :disabled="busy || !!parseErr" @click="save">
          {{ busy === 'save' ? 'Saving…' : 'Save' }}
        </button>
        <button class="btn-danger" :disabled="busy || !currentHost()?.has_token" @click="restart"
          :title="currentHost()?.has_token ? '' : 'Needs an API token'">
          {{ busy === 'restart' ? 'Restarting…' : 'Restart Service' }}
        </button>
      </div>
    </div>

    <p v-if="loadErr" class="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{{ loadErr }}</p>
    <p v-if="parseErr" class="mb-4 rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-400">
      YAML parse error: {{ parseErr }} — the visual view is paused until it's valid.
    </p>

    <!-- Save/restart result -->
    <div v-if="result" class="mb-4 rounded-lg px-3 py-2 text-sm"
         :class="result.ok ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'">
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

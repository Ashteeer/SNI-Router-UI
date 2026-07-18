<script setup>
// Mode-aware forms over the parsed config object. Mutates `model` in place;
// the parent watches it deeply and re-serializes to YAML (kept in sync with
// the manual editor). See config.md for the field-applicability matrix.
import { ref, watch, onBeforeUnmount } from 'vue'
import { api } from '../api'
import InfoTip from './InfoTip.vue'

const props = defineProps({ model: Object, hostId: Number })

const MODES = ['passthrough', 'terminate', 'terminate_tcp', 'redirect_https']
const PROXY = ['none', 'v1', 'v2']
const BALANCE = ['round_robin', 'least_conn']

// field applicability by mode
const uses = {
  servers: (m) => m !== 'redirect_https',
  proxy_protocol: (m) => m === 'passthrough' || m === 'terminate_tcp',
  balance: (m) => m !== 'redirect_https',
  health_check: (m) => m !== 'redirect_https',
  fast_open: (m) => m !== 'redirect_https',
  tls: (m) => m === 'terminate' || m === 'terminate_tcp',
  backend_tls: (m) => m === 'terminate',
  headers: (m) => m === 'terminate',
  http2: (m) => m === 'terminate',
  http_rules: (m) => m === 'terminate' || m === 'redirect_https',
}

// short, plain-language help for each timeout (config.md §5)
const TIMEOUT_HINTS = {
  handshake: 'Max seconds a client TLS handshake may take before the connection is dropped.',
  connect: 'Max seconds to open the TCP connection to a backend server.',
  idle: 'Close a connection after this many seconds with no data in either direction.',
  keepalive: 'Reaps connections whose peer vanished without a FIN — a NAT rebind or dead VPN client. 0 disables it.',
  health_interval: 'How often (seconds) the backend TCP health probe runs.',
  drain: 'On reload/restart, how long to let existing connections finish before they are closed.',
}

function ensure(obj, key, val) {
  if (obj[key] == null) obj[key] = val
  return obj[key]
}

// Optional ints (backlog, fast_open_qlen, timeouts) share one rule: an empty
// field means "omit and take the router's default", never `0` — which is a hard
// error for these (listen(0) accepts nothing; qlen 0 turns TFO off).
// `keepalive: 0` is the one legitimate zero, and typing it still works.
function setNum(obj, key, v) {
  if (v === '' || v == null) delete obj[key]
  else obj[key] = Number(v)
}

// listeners
function addListener() {
  ensure(props.model, 'listeners', [])
  props.model.listeners.push({ name: 'listener', bind: [''], proto: 'tcp', routes: [] })
}
function delListener(i) { props.model.listeners.splice(i, 1) }
// backlog / fast_open / fast_open_qlen are tcp-only: fast_open on udp is a hard
// error, the other two earn "ignored" warnings. Drop all three with the proto.
function setProto(l, p) {
  l.proto = p
  if (p !== 'tcp') { delete l.fast_open; delete l.fast_open_qlen; delete l.backlog }
}
// fast_open_qlen without fast_open is a warning — untick clears it too.
function setFastOpen(l, on) {
  if (on) { l.fast_open = true; checkTfo() }
  else { delete l.fast_open; delete l.fast_open_qlen }
}

// --- host TFO sysctl status (#5) -------------------------------------------
// net.ipv4.tcp_fastopen is host-wide, so one status covers every listener. We
// only warn when we positively know it's off (checked && !enabled).
const tfo = ref(null)        // { value, enabled } | null (unknown / agent down)
const tfoBusy = ref(false)
const toast = ref(null)      // { msg, ok } | null
let toastTimer = null
function tfoOff() { return tfo.value != null && tfo.value.enabled === false }
async function checkTfo() {
  if (!props.hostId) return
  try { tfo.value = await api.tfoStatus(props.hostId) }
  catch { tfo.value = null } // agent unreachable — can't verify, so don't nag
}
async function enableTfo() {
  if (!props.hostId || tfoBusy.value) return
  tfoBusy.value = true
  try {
    tfo.value = await api.tfoEnable(props.hostId)
    if (tfo.value?.enabled) showToast('TCP Fast Open enabled on the host.')
    else showToast('Enable request sent, but TFO still reads off.', false)
  } catch (e) {
    showToast('Failed to enable TFO: ' + e.message, false)
  } finally { tfoBusy.value = false }
}
function showToast(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 4000)
}
// check the host's TFO sysctl once a config with an enabled listener TFO loads
watch(() => (props.model?.listeners || []).some((l) => l.fast_open),
  (has) => { if (has && tfo.value == null) checkTfo() }, { immediate: true })

// --- light observability: host kernel counters for accept-queue / TFO (#7) ---
const counters = ref(null) // { ListenOverflows, ListenDrops, TCPFastOpen*... } | null
async function checkCounters() {
  if (!props.hostId) return
  try { counters.value = await api.netstat(props.hostId) }
  catch { counters.value = null } // agent down — just hide the indicators
}
function obsClass(n) { return (n || 0) > 0 ? 'text-amber-400' : 'text-emerald-400' }
watch(() => (props.model?.listeners || []).length > 0,
  (has) => { if (has && counters.value == null) checkCounters() }, { immediate: true })
// Off == absent for a default-false bool: keep it out of the YAML entirely.
function setFlag(obj, key, on) {
  if (on) obj[key] = true
  else delete obj[key]
}
function addBind(l) { l.bind.push('') }
function addRoute(l) { ensure(l, 'routes', []).push({ sni: '*', backend: backendNames()[0] || '' }) }

// backends (map)
function backendNames() { return Object.keys(props.model.backends || {}) }
function addBackend() {
  ensure(props.model, 'backends', {})
  let n = 'backend', i = 1
  while (props.model.backends[n]) n = 'backend' + ++i
  props.model.backends[n] = { mode: 'passthrough', servers: [''] }
}
// Switching mode must also drop the fields the new mode doesn't use: a leftover
// `servers: ['']` from the passthrough default is a hard validation error on
// redirect_https (empty string isn't a valid IP:port), and the rest would only
// earn "field ignored for this mode" warnings.
function setMode(be, m) {
  be.mode = m
  for (const [k, applies] of Object.entries(uses)) if (!applies(m)) delete be[k]
  if (uses.servers(m)) ensure(be, 'servers', [''])
}
// Rename a backend WITHOUT moving it (rebuild the map in place, same key order)
// and cascade the new name to every route that referenced the old one.
function renameBackend(oldName, e) {
  const nn = e.target.value.trim()
  if (!nn || nn === oldName || props.model.backends[nn]) { e.target.value = oldName; return }
  const rebuilt = {}
  for (const [k, v] of Object.entries(props.model.backends)) rebuilt[k === oldName ? nn : k] = v
  props.model.backends = rebuilt
  for (const l of props.model.listeners || [])
    for (const r of l.routes || []) if (r.backend === oldName) r.backend = nn
}
function delBackend(name) { delete props.model.backends[name] }
function addServer(be) { ensure(be, 'servers', []).push('') }
// new rules default to a 404 catch-all (path "*") — a valid, common "deny the rest"
function addRule(be) {
  ensure(be, 'http_rules', []).push({ path: '*', action: 'respond', status: 404, body: 'not found\n', content_type: 'text/plain' })
}

// --- HTTP-rule presets: hide sni-router's action/status syntax behind simple types.
function ruleType(r) {
  if (r.action === 'redirect') return (r.status == null || r.status === 301) ? '301' : 'redirect'
  if (r.action === 'respond') return r.status === 404 ? '404' : 'respond'
  return r.action || 'forward'
}
function setRuleType(r, type) {
  const keepTo = r.to
  delete r.status; delete r.to; delete r.body; delete r.content_type
  if (type === '301') { r.action = 'redirect'; r.status = 301; r.to = keepTo || 'https' }
  else if (type === '404') { r.action = 'respond'; r.status = 404; r.body = 'not found\n'; r.content_type = 'text/plain' }
  else if (type === 'forward') { r.action = 'forward' }
  else if (type === 'respond') { r.action = 'respond'; r.status = 200 }
  else if (type === 'redirect') { r.action = 'redirect'; r.status = 302; r.to = keepTo || 'https' }
}

// --- TLS cert/key validation via the host agent (#9) -----------------------
// keyed by a caller-supplied id so several fields can show their own status.
const certs = ref({})
function setCert(key, val) { certs.value = { ...certs.value, [key]: val } }
async function checkCert(key, path) {
  path = (path || '').trim()
  if (!path) { const c = { ...certs.value }; delete c[key]; certs.value = c; return }
  if (!props.hostId) return
  setCert(key, { state: 'checking' })
  try {
    const r = await api.certCheck(props.hostId, path)
    let state = 'ok'
    if (!r.exists) state = 'missing'
    else if (!r.readable) state = 'unreadable'
    else if (r.is_cert === false) state = 'notcert'
    setCert(key, { state, ...r })
  } catch (e) {
    setCert(key, { state: 'error', error: e.message })
  }
}
function fmtDate(epoch) {
  if (!epoch) return ''
  return new Date(epoch * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
function certText(c, isKey = false) {
  if (!c) return ''
  switch (c.state) {
    case 'checking': return 'checking…'
    case 'missing': return '✗ not found on host'
    case 'unreadable': return '✗ exists but not readable'
    case 'notcert': return isKey ? '✓ found (readable)' : '⚠ not a valid certificate'
    case 'error': return 'check failed: ' + (c.error || '')
    case 'ok':
      if (isKey || c.is_cert === false) return '✓ found (readable)'
      if (c.days_left == null) return '✓ valid certificate'
      return `✓ expires ${fmtDate(c.expires_epoch)} — ${c.days_left} day${c.days_left === 1 ? '' : 's'} left`
    default: return ''
  }
}
function certClass(c, isKey = false) {
  if (!c) return ''
  if (c.state === 'checking') return 'text-slate-500'
  if (c.state === 'ok') return (!isKey && c.days_left != null && c.days_left < 14) ? 'text-amber-400' : 'text-emerald-400'
  if (c.state === 'notcert') return isKey ? 'text-emerald-400' : 'text-amber-400'
  return 'text-red-400'
}

// --- interactive pointer drag-reorder (#4) ---------------------------------
// The dragged card floats with the cursor (translateY) and a thin line shows
// where it will land. `kind`/`key` scope a drag so items never cross lists.
// `over` is the insertion index (0..n) among the current items.
const drag = ref(null) // { kind, key, from, over, el, startY, startScroll, dy }
let lastClientY = 0
let autoRaf = null

function dragDown(e, kind, from, key = null) {
  const el = e.currentTarget.closest('[data-dragitem]')
  if (!el) return
  e.preventDefault()
  lastClientY = e.clientY
  drag.value = { kind, key, from, over: from, el, startY: e.clientY, startScroll: window.scrollY, dy: 0 }
  window.addEventListener('pointermove', dragMove)
  window.addEventListener('pointerup', dragUp)
  autoRaf = requestAnimationFrame(autoScroll)
}
// recompute the float offset (document-relative, so the card stays under the cursor
// even while the page auto-scrolls) and the drop index from sibling midpoints.
function recompute() {
  const d = drag.value
  if (!d) return
  d.dy = (lastClientY + window.scrollY) - (d.startY + d.startScroll)
  const items = [...d.el.parentElement.querySelectorAll(':scope > [data-dragitem]')]
  let over = items.length
  for (let i = 0; i < items.length; i++) {
    const r = items[i].getBoundingClientRect()
    if (lastClientY < r.top + r.height / 2) { over = i; break }
  }
  d.over = over
  drag.value = { ...d }
}
function dragMove(e) {
  if (!drag.value) return
  lastClientY = e.clientY
  recompute()
}
// scroll the page when the cursor is near the top/bottom edge mid-drag (#4)
function autoScroll() {
  if (!drag.value) { autoRaf = null; return }
  const margin = 90, maxSpeed = 16, h = window.innerHeight
  let delta = 0
  if (lastClientY < margin) delta = -Math.ceil(maxSpeed * (1 - lastClientY / margin))
  else if (lastClientY > h - margin) delta = Math.ceil(maxSpeed * (1 - (h - lastClientY) / margin))
  if (delta) { window.scrollBy(0, delta); recompute() }
  autoRaf = requestAnimationFrame(autoScroll)
}
function dragUp() {
  window.removeEventListener('pointermove', dragMove)
  window.removeEventListener('pointerup', dragUp)
  if (autoRaf) { cancelAnimationFrame(autoRaf); autoRaf = null }
  const d = drag.value
  drag.value = null
  if (!d) return
  let to = d.over
  if (to > d.from) to -= 1 // account for pulling the source out first
  if (to === d.from) return
  if (d.kind === 'listener') moveArr(props.model.listeners, d.from, to)
  else if (d.kind === 'backend') moveBackend(d.from, to)
  else if (d.kind === 'route') moveArr(props.model.listeners[d.key].routes, d.from, to)
  else if (d.kind === 'rule') moveArr(props.model.backends[d.key].http_rules, d.from, to)
}
function dragStyle(kind, key, i) {
  const d = drag.value
  if (d && d.kind === kind && d.key === key && d.from === i)
    return { transform: `translateY(${d.dy}px)`, position: 'relative', zIndex: 40,
             opacity: 0.97, cursor: 'grabbing', boxShadow: '0 22px 44px -14px rgba(0,0,0,.75)' }
  return {}
}
// show the drop line at insertion index `index`, but not where the item already sits
function showLine(kind, key, index) {
  const d = drag.value
  return !!d && d.kind === kind && d.key === key && d.over === index &&
         index !== d.from && index !== d.from + 1
}
function moveArr(arr, from, to) {
  if (!arr || from === to || from < 0) return
  const [it] = arr.splice(from, 1)
  arr.splice(to, 0, it)
}
function moveBackend(from, to) {
  const names = Object.keys(props.model.backends || {})
  if (from === to || from < 0) return
  const [n] = names.splice(from, 1)
  names.splice(to, 0, n)
  const rebuilt = {}
  for (const k of names) rebuilt[k] = props.model.backends[k]
  props.model.backends = rebuilt // reassign a map property → deep watcher re-dumps
}
onBeforeUnmount(() => {
  window.removeEventListener('pointermove', dragMove)
  window.removeEventListener('pointerup', dragUp)
  if (autoRaf) cancelAnimationFrame(autoRaf)
})
</script>

<template>
  <div v-if="model" class="space-y-6">
    <Transition name="modal">
      <div v-if="toast" class="toast" :class="{ 'toast-err': !toast.ok }">{{ toast.msg }}</div>
    </Transition>

    <!-- Listeners -->
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-400">Listeners</h3>
        <button class="btn-ghost" @click="addListener">+ Listener</button>
      </div>
      <template v-for="(l, li) in model.listeners" :key="li">
        <div v-if="showLine('listener', null, li)" class="drop-line"></div>
        <div data-dragitem class="card mb-3" :style="dragStyle('listener', null, li)">
          <div class="mb-2 flex items-center gap-2">
            <span class="select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                  style="cursor: grab; touch-action: none"
                  @pointerdown="dragDown($event, 'listener', li)" title="Drag to reorder">⠿</span>
            <span class="text-xs uppercase tracking-wide text-slate-500">Listener {{ li + 1 }}</span>
          </div>
          <div class="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label class="label">Name</label>
              <input v-model="l.name" class="input" />
            </div>
            <div>
              <label class="label">Proto</label>
              <select :value="l.proto || 'tcp'" class="input" @change="setProto(l, $event.target.value)">
                <option value="tcp">tcp</option>
                <option value="udp">udp (QUIC)</option>
              </select>
            </div>
            <div class="flex items-end justify-end">
              <button class="btn-danger" @click="delListener(li)">Remove</button>
            </div>
          </div>

          <!-- accept queues + fast_open (TFO) — tcp only -->
          <template v-if="(l.proto || 'tcp') === 'tcp'">
            <div class="mb-3">
              <label class="label">Backlog (accept queue)</label>
              <input :value="l.backlog" type="number" min="1" class="input" placeholder="1024 (default)"
                     @input="setNum(l, 'backlog', $event.target.value)" />
              <p class="mt-1 text-xs text-slate-500">
                Connections whose handshake finished, waiting to be accepted. Leave empty for the
                default — it's sized for a reconnect burst. On overflow the kernel <b>drops SYNs</b>,
                so raise this one first if <code>nstat -az TcpExtListenOverflows</code> climbs.
                Clamped by <code>net.core.somaxconn</code>.
              </p>
              <p v-if="counters" class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
                <span :class="obsClass(counters.ListenOverflows)">● accept-queue overflows: {{ counters.ListenOverflows ?? 0 }}</span>
                <span class="text-slate-600">host-wide — raise backlog if this climbs</span>
                <button type="button" class="text-slate-500 hover:text-slate-300" @click="checkCounters" title="Refresh counters">↻</button>
              </p>
            </div>

            <div class="mb-3">
              <div class="flex items-center gap-1">
                <label class="flex items-center gap-2 text-sm text-slate-300">
                  <input :id="'tfo' + li" type="checkbox" :checked="!!l.fast_open"
                         @change="setFastOpen(l, $event.target.checked)" />
                  TCP Fast Open (accept client TFO)
                </label>
                <span v-if="l.fast_open && tfoOff()" class="tfo-wrap relative inline-flex">
                  <button type="button" class="tfo-warn" :disabled="tfoBusy" @click="enableTfo"
                          aria-label="Enable TCP Fast Open on the host">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                  </button>
                  <span class="infotip-pop tfo-tip">
                    {{ tfoBusy ? 'Enabling TFO on the host…' : 'TCP Fast Open is not enabled on this host (net.ipv4.tcp_fastopen ≠ 3). Click to enable it.' }}
                  </span>
                </span>
              </div>
              <p class="mt-1 text-xs text-slate-500">
                Lets a returning client send its ClientHello inside the SYN, saving one RTT.
                Needs <code>net.ipv4.tcp_fastopen = 3</code> on the host — otherwise the router
                still starts, TFO just stays inactive. Changing this restarts the listener.
              </p>
            </div>

            <div v-if="l.fast_open" class="mb-3 pl-6">
              <label class="label">fast_open_qlen (pending-SYN queue)</label>
              <input :value="l.fast_open_qlen" type="number" min="1" class="input" placeholder="1024 (default)"
                     @input="setNum(l, 'fast_open_qlen', $event.target.value)" />
              <p class="mt-1 text-xs text-slate-500">
                TFO connections whose data arrived before the handshake finished. Separate from the
                backlog. Overflow costs the client only a round trip (it falls back to a normal
                handshake), so this is far less urgent to tune — watch
                <code>nstat -az TcpExtTCPFastOpenListenOverflow</code>.
              </p>
              <p v-if="counters" class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
                <span :class="obsClass(counters.TCPFastOpenListenOverflow)">● TFO queue overflows: {{ counters.TCPFastOpenListenOverflow ?? 0 }}</span>
                <span v-if="counters.TCPFastOpenPassive != null" class="text-emerald-400">accepted: {{ counters.TCPFastOpenPassive }}</span>
                <span v-if="counters.TCPFastOpenPassiveFail" class="text-amber-400">failed: {{ counters.TCPFastOpenPassiveFail }}</span>
              </p>
            </div>
          </template>

          <label class="label">Bind (IP:port)</label>
          <div v-for="(b, bi) in l.bind" :key="bi" class="mb-2 flex gap-2">
            <input v-model="l.bind[bi]" class="input" placeholder="0.0.0.0:443" />
            <button class="btn-ghost" @click="l.bind.splice(bi, 1)">✕</button>
          </div>
          <button class="btn-ghost mb-3" @click="addBind(l)">+ bind</button>

          <label class="label">Routes (first match wins — drag ⠿ to reorder)</label>
          <template v-for="(r, ri) in l.routes" :key="ri">
            <div v-if="showLine('route', li, ri)" class="drop-line"></div>
            <div data-dragitem class="mb-2 flex items-center gap-2" :style="dragStyle('route', li, ri)">
              <span class="select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                    style="cursor: grab; touch-action: none"
                    @pointerdown="dragDown($event, 'route', ri, li)" title="Drag to reorder">⠿</span>
              <input v-model="r.sni" class="input" placeholder="*.example.com or *" />
              <select v-model="r.backend" class="input">
                <option v-for="n in backendNames()" :key="n" :value="n">{{ n }}</option>
              </select>
              <button class="btn-ghost" @click="l.routes.splice(ri, 1)">✕</button>
            </div>
          </template>
          <div v-if="showLine('route', li, (l.routes || []).length)" class="drop-line"></div>
          <button class="btn-ghost" @click="addRoute(l)">+ route</button>
        </div>
      </template>
      <div v-if="showLine('listener', null, (model.listeners || []).length)" class="drop-line"></div>
    </section>

    <!-- Backends -->
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-400">Backends</h3>
        <button class="btn-ghost" @click="addBackend">+ Backend</button>
      </div>
      <template v-for="(be, name, bi) in model.backends" :key="name">
        <div v-if="showLine('backend', null, bi)" class="drop-line"></div>
        <div data-dragitem class="card mb-3" :style="dragStyle('backend', null, bi)">
          <div class="mb-2 flex items-center gap-2">
            <span class="select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                  style="cursor: grab; touch-action: none"
                  @pointerdown="dragDown($event, 'backend', bi)" title="Drag to reorder">⠿</span>
            <span class="text-xs uppercase tracking-wide text-slate-500">Backend</span>
          </div>
          <div class="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label class="label">Name</label>
              <input :value="name" class="input" @change="renameBackend(name, $event)" />
            </div>
            <div>
              <label class="label">Mode</label>
              <select :value="be.mode" class="input" @change="setMode(be, $event.target.value)">
                <option v-for="m in MODES" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
            <div class="flex items-end justify-end">
              <button class="btn-danger" @click="delBackend(name)">Remove</button>
            </div>
          </div>

          <!-- servers -->
          <template v-if="uses.servers(be.mode)">
            <label class="label">Servers (IP:port)</label>
            <div v-for="(s, si) in be.servers" :key="si" class="mb-2 flex gap-2">
              <input v-model="be.servers[si]" class="input" placeholder="127.0.0.1:8080" />
              <button class="btn-ghost" @click="be.servers.splice(si, 1)">✕</button>
            </div>
            <button class="btn-ghost mb-3" @click="addServer(be)">+ server</button>
          </template>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div v-if="uses.proxy_protocol(be.mode)">
              <label class="label">PROXY protocol</label>
              <select v-model="be.proxy_protocol" class="input">
                <option v-for="p in PROXY" :key="p" :value="p">{{ p }}</option>
              </select>
            </div>
            <div v-if="uses.balance(be.mode)">
              <label class="label">Balance</label>
              <select v-model="be.balance" class="input">
                <option v-for="b in BALANCE" :key="b" :value="b">{{ b }}</option>
              </select>
            </div>
          </div>

          <div v-if="uses.health_check(be.mode)" class="mt-2 flex items-center gap-2">
            <input :id="'hc' + name" v-model="be.health_check" type="checkbox" />
            <label :for="'hc' + name" class="text-sm text-slate-300">Health check (TCP probe)</label>
          </div>
          <div v-if="uses.http2(be.mode)" class="mt-2 flex items-center gap-2">
            <input :id="'h2' + name" v-model="be.http2" type="checkbox" />
            <label :for="'h2' + name" class="text-sm text-slate-300">HTTP/2 (h2)</label>
          </div>
          <p v-if="uses.http2(be.mode) && be.http2" class="mt-1 pl-6 text-xs text-slate-500">
            Backend connections are pooled and reused, so a burst of h2 streams no longer means a
            burst of connects — nothing to configure. Watch
            <code>sni_router_h2_pool_hits_total</code> in <code>/metrics</code>. The backend is
            spoken to as plaintext HTTP/1.1, so this can't be combined with <code>backend_tls</code>.
          </p>

          <div v-if="uses.fast_open(be.mode)" class="mt-2">
            <label class="flex items-center gap-2 text-sm text-slate-300">
              <input :id="'befo' + name" type="checkbox" :checked="!!be.fast_open"
                     @change="setFlag(be, 'fast_open', $event.target.checked)" />
              TCP Fast Open to servers
            </label>
            <p class="mt-1 pl-6 text-xs text-slate-500">
              Saves one RTT when <b>connecting to</b> this backend's servers — separate from the
              listener's TFO, which accepts it from clients. Only worth it when the server is a
              <b>remote</b> hop (for <code>127.0.0.1</code> it buys nothing) <b>and</b> has TFO
              enabled itself; otherwise the kernel quietly falls back to a normal handshake.
            </p>
          </div>

          <!-- tls -->
          <template v-if="uses.tls(be.mode)">
            <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label class="label">TLS cert path</label>
                <input :value="be.tls?.cert" class="input" placeholder="(or use default_tls)"
                  @input="ensure(be, 'tls', {}).cert = $event.target.value"
                  @blur="checkCert('be:' + name + ':cert', be.tls?.cert)" />
                <p v-if="certs['be:' + name + ':cert']" class="mt-1 text-xs" :class="certClass(certs['be:' + name + ':cert'])">
                  {{ certText(certs['be:' + name + ':cert']) }}
                </p>
              </div>
              <div>
                <label class="label">TLS key path</label>
                <input :value="be.tls?.key" class="input" placeholder="(or use default_tls)"
                  @input="ensure(be, 'tls', {}).key = $event.target.value"
                  @blur="checkCert('be:' + name + ':key', be.tls?.key)" />
                <p v-if="certs['be:' + name + ':key']" class="mt-1 text-xs" :class="certClass(certs['be:' + name + ':key'], true)">
                  {{ certText(certs['be:' + name + ':key'], true) }}
                </p>
              </div>
            </div>
          </template>

          <!-- headers -->
          <template v-if="uses.headers(be.mode)">
            <label class="label mt-3">Injected headers</label>
            <div class="flex flex-wrap gap-4">
              <label v-for="h in ['x_real_ip', 'x_forwarded_for', 'x_forwarded_proto']" :key="h"
                     class="flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" :checked="be.headers?.[h]"
                  @change="ensure(be, 'headers', {})[h] = $event.target.checked" />
                {{ h }}
              </label>
            </div>
          </template>

          <!-- http_rules -->
          <template v-if="uses.http_rules(be.mode)">
            <label class="label mt-3">HTTP rules (first match wins — drag ⠿ to reorder)</label>
            <template v-for="(r, ri) in be.http_rules" :key="ri">
              <div v-if="showLine('rule', name, ri)" class="drop-line"></div>
              <div data-dragitem class="mb-2 rounded-lg border border-slate-800 p-2" :style="dragStyle('rule', name, ri)">
                <div class="flex items-center gap-2">
                  <span class="select-none text-lg leading-none text-slate-500 hover:text-slate-300"
                        style="cursor: grab; touch-action: none"
                        @pointerdown="dragDown($event, 'rule', ri, name)" title="Drag to reorder">⠿</span>
                  <input v-model="r.path" class="input" placeholder="*  (all paths)  or  /prefix" />
                  <select :value="ruleType(r)" @change="setRuleType(r, $event.target.value)" class="input w-52">
                    <option value="301">301 → https / custom port</option>
                    <option value="404">404 Not Found</option>
                    <option value="forward">forward (advanced)</option>
                    <option value="respond">respond (advanced)</option>
                    <option value="redirect">redirect (advanced)</option>
                  </select>
                  <button class="btn-ghost" @click="be.http_rules.splice(ri, 1)">✕</button>
                </div>
                <p class="mt-1 pl-8 text-xs text-slate-500">
                  Path is a <b>prefix</b> match: <code>/api</code> matches <code>/api</code> and <code>/api/…</code>.
                  For <b>all</b> paths use <code>*</code> — no trailing <code>*</code> after a slash needed.
                </p>

                <!-- 301 preset: only the target to fill -->
                <div v-if="ruleType(r) === '301'" class="mt-2 pl-8">
                  <input v-model="r.to" class="input" placeholder="https   ·   or   https://host:8443" />
                  <p class="mt-1 text-xs text-slate-500">
                    Sends <b>301</b> → <code>Location</code>. <code>https</code> upgrades to HTTPS on the
                    same host (:443); for a <b>custom port</b> enter a full URL, e.g. <code>https://host:8443</code>.
                  </p>
                </div>
                <!-- 404 preset: nothing to fill -->
                <p v-else-if="ruleType(r) === '404'" class="mt-2 pl-8 text-xs text-slate-500">
                  Returns <b>404</b> with body “not found”. Nothing else to configure.
                </p>
                <!-- forward: nothing to fill -->
                <p v-else-if="ruleType(r) === 'forward'" class="mt-2 pl-8 text-xs text-slate-500">
                  Forwards matching requests to this backend's servers.
                </p>
                <!-- respond (advanced) -->
                <div v-else-if="ruleType(r) === 'respond'" class="mt-2 grid grid-cols-2 gap-2 pl-8">
                  <input v-model.number="r.status" type="number" class="input" placeholder="status (e.g. 200)" />
                  <input v-model="r.content_type" class="input" placeholder="content_type (text/plain)" />
                  <input v-model="r.body" class="input col-span-2" placeholder="body" />
                </div>
                <!-- redirect (advanced) -->
                <div v-else class="mt-2 grid grid-cols-2 gap-2 pl-8">
                  <input v-model.number="r.status" type="number" class="input" placeholder="status (302 / 307 / 308)" />
                  <input v-model="r.to" class="input" placeholder="https or absolute URL" />
                </div>
              </div>
            </template>
            <div v-if="showLine('rule', name, (be.http_rules || []).length)" class="drop-line"></div>
            <button class="btn-ghost" @click="addRule(be)">+ rule</button>
          </template>
        </div>
      </template>
      <div v-if="showLine('backend', null, Object.keys(model.backends || {}).length)" class="drop-line"></div>
    </section>

    <!-- Global scalars -->
    <section class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div class="card">
        <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Timeouts (s)</h3>
        <div class="grid grid-cols-2 gap-3">
          <div v-for="k in ['handshake', 'connect', 'idle', 'keepalive', 'health_interval', 'drain']" :key="k">
            <label class="label flex items-center">{{ k }}<InfoTip :text="TIMEOUT_HINTS[k]" /></label>
            <input :value="model.timeouts?.[k]" type="number" class="input" placeholder="default"
              @input="setNum(ensure(model, 'timeouts', {}), k, $event.target.value)" />
          </div>
        </div>
        <p class="mt-2 text-xs text-slate-500">
          Empty = the router's default. <code>keepalive</code> (default 60) reaps connections whose
          peer vanished without a FIN — a NAT rebind, a dead VPN client. It matters here because
          passthrough splices in the kernel, so the router never sees the bytes and can't time them
          out itself; <code>0</code> disables it.
        </p>
      </div>
      <div class="card">
        <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Limits / Log / API</h3>
        <label class="label">max_conns_per_ip</label>
        <input :value="model.limits?.max_conns_per_ip" type="number" class="input mb-3"
          @input="ensure(model, 'limits', {}).max_conns_per_ip = Number($event.target.value)" />
        <label class="label">log.level</label>
        <select :value="model.log?.level" class="input mb-3"
          @change="ensure(model, 'log', {}).level = $event.target.value">
          <option v-for="lv in ['error', 'warn', 'info', 'debug', 'trace']" :key="lv" :value="lv">{{ lv }}</option>
        </select>
        <label class="label">api.bind (config + metrics + control)</label>
        <input :value="model.api?.bind" class="input mb-3" placeholder="0.0.0.0:9901"
          @input="ensure(model, 'api', {}).bind = $event.target.value" />
        <label class="label">api.token</label>
        <input :value="model.api?.token" class="input" placeholder="Bearer token"
          @input="ensure(model, 'api', {}).token = $event.target.value" />
      </div>
      <div class="card">
        <h3 class="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-400">Default TLS</h3>
        <p class="mb-3 text-xs text-slate-500">
          Shared cert for any <code>terminate</code> backend that has no <code>tls</code> of its own.
        </p>
        <label class="label">default_tls.cert path</label>
        <input :value="model.default_tls?.cert" class="input" placeholder="/etc/ssl/fullchain.pem"
          @input="ensure(model, 'default_tls', {}).cert = $event.target.value"
          @blur="checkCert('default:cert', model.default_tls?.cert)" />
        <p v-if="certs['default:cert']" class="mt-1 mb-3 text-xs" :class="certClass(certs['default:cert'])">
          {{ certText(certs['default:cert']) }}
        </p>
        <div v-else class="mb-3"></div>
        <label class="label">default_tls.key path</label>
        <input :value="model.default_tls?.key" class="input" placeholder="/etc/ssl/privkey.pem"
          @input="ensure(model, 'default_tls', {}).key = $event.target.value"
          @blur="checkCert('default:key', model.default_tls?.key)" />
        <p v-if="certs['default:key']" class="mt-1 text-xs" :class="certClass(certs['default:key'], true)">
          {{ certText(certs['default:key'], true) }}
        </p>
      </div>
    </section>
  </div>
</template>

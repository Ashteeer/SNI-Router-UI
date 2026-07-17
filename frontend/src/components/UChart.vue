<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import uPlot from 'uplot'

const props = defineProps({
  title: String,
  // data: [xsEpochSecs, ...ySeries]
  data: { type: Array, default: () => [[]] },
  // series: [{ label, stroke, fill }]
  series: { type: Array, default: () => [] },
  yfmt: { type: Function, default: (v) => (v == null ? '—' : v) },
  height: { type: Number, default: 200 },
})

const wrap = ref(null)
let plot = null
let ro = null
let zoomed = false // user drag-zoomed → keep their window across live data refreshes

function makeOpts(width) {
  return {
    width,
    height: props.height,
    padding: [12, 12, 0, 0],
    scales: { x: { time: true } },
    axes: [
      { stroke: '#8b93a7', grid: { stroke: 'rgba(255,255,255,0.055)', width: 1 }, ticks: { stroke: 'rgba(255,255,255,0.12)' } },
      {
        stroke: '#8b93a7',
        grid: { stroke: 'rgba(255,255,255,0.055)', width: 1 },
        ticks: { stroke: 'rgba(255,255,255,0.12)' },
        size: 60,
        values: (u, vals) => vals.map((v) => props.yfmt(v)),
      },
    ],
    series: [
      {},
      ...props.series.map((s) => ({
        label: s.label,
        stroke: s.stroke,
        fill: s.fill,
        width: 2,
        spanGaps: false,
        value: (u, v) => props.yfmt(v),
      })),
    ],
    cursor: { drag: { x: true, y: false }, points: { size: 6 } },
    legend: { live: true },
    hooks: {
      // drag-select zooms → remember it so live refreshes don't snap back
      setSelect: [(u) => { if (u.select.width > 0) zoomed = true }],
    },
  }
}

function build() {
  if (plot) { plot.destroy(); plot = null }
  zoomed = false
  const width = wrap.value?.clientWidth || 600
  plot = new uPlot(makeOpts(width), props.data, wrap.value)
  // uPlot's built-in dblclick resets the view; clear our flag so it follows again
  wrap.value.addEventListener('dblclick', () => { zoomed = false })
}

onMounted(async () => {
  await nextTick()
  build()
  ro = new ResizeObserver(() => {
    if (plot && wrap.value) plot.setSize({ width: wrap.value.clientWidth, height: props.height })
  })
  ro.observe(wrap.value)
})

onBeforeUnmount(() => {
  ro?.disconnect()
  plot?.destroy()
})

// New data of same shape: cheap setData. Series shape change: rebuild.
// resetScales=false while zoomed keeps the user's window; otherwise follow new data
watch(() => props.data, (d) => { if (plot) plot.setData(d, !zoomed) })
watch(() => props.series, () => build())
</script>

<template>
  <div class="card card-hover">
    <div class="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">{{ title }}</div>
    <div ref="wrap"></div>
  </div>
</template>

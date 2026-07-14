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

function makeOpts(width) {
  return {
    width,
    height: props.height,
    padding: [12, 12, 0, 0],
    scales: { x: { time: true } },
    axes: [
      { stroke: '#94a3b8', grid: { stroke: '#1e293b', width: 1 }, ticks: { stroke: '#334155' } },
      {
        stroke: '#94a3b8',
        grid: { stroke: '#1e293b', width: 1 },
        ticks: { stroke: '#334155' },
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
  }
}

function build() {
  if (plot) { plot.destroy(); plot = null }
  const width = wrap.value?.clientWidth || 600
  plot = new uPlot(makeOpts(width), props.data, wrap.value)
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
watch(() => props.data, (d) => { if (plot) plot.setData(d) })
watch(() => props.series, () => build())
</script>

<template>
  <div class="card">
    <div class="mb-2 text-sm font-semibold text-slate-300">{{ title }}</div>
    <div ref="wrap"></div>
  </div>
</template>

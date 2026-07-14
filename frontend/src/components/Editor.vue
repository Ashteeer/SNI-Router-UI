<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { EditorView, basicSetup } from 'codemirror'
import { EditorState, Annotation } from '@codemirror/state'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'

const props = defineProps({
  modelValue: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const host = ref(null)
let view = null
// Marks doc changes we push in programmatically, so we don't echo them back
// to the parent as user edits (prevents the visual<->manual sync loop).
const programmatic = Annotation.define()

onMounted(() => {
  view = new EditorView({
    parent: host.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        basicSetup,
        yaml(),
        oneDark,
        EditorView.updateListener.of((u) => {
          if (!u.docChanged) return
          if (u.transactions.some((t) => t.annotation(programmatic))) return
          emit('update:modelValue', u.state.doc.toString())
        }),
      ],
    }),
  })
})

onBeforeUnmount(() => view?.destroy())

watch(() => props.modelValue, (val) => {
  if (!view || val === view.state.doc.toString()) return
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: val },
    annotations: programmatic.of(true),
  })
})
</script>

<template>
  <div ref="host" class="h-full overflow-auto rounded-lg border border-slate-800 text-sm"></div>
</template>

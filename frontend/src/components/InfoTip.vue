<script setup>
// Tiny "(?)" help marker: hover on desktop, tap on touch. Kept intentionally
// subtle so it doesn't compete with the field labels.
import { ref } from 'vue'
defineProps({ text: String })
const open = ref(false)
</script>

<template>
  <span class="relative inline-flex align-middle"
        @mouseenter="open = true" @mouseleave="open = false">
    <button type="button" class="infotip-btn" aria-label="help"
            @click.stop="open = !open" @blur="open = false">?</button>
    <span v-if="open" class="infotip-pop" role="tooltip">{{ text }}</span>
  </span>
</template>

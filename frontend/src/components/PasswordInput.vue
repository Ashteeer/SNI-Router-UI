<script setup>
import { ref } from 'vue'
defineProps({ modelValue: String, placeholder: String, autocomplete: String, required: Boolean })
defineEmits(['update:modelValue'])
const show = ref(false)
</script>

<template>
  <div class="relative">
    <input :type="show ? 'text' : 'password'" :value="modelValue" :placeholder="placeholder"
           :autocomplete="autocomplete || 'off'" :required="required"
           class="input pr-10" @input="$emit('update:modelValue', $event.target.value)" />
    <button type="button" tabindex="-1" :title="show ? 'Hide' : 'Show'"
            class="absolute inset-y-0 right-0 grid w-10 place-items-center text-slate-400 hover:text-slate-200"
            @click="show = !show">
      <svg v-if="!show" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" />
      </svg>
      <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M17.9 17.9A10.5 10.5 0 0 1 12 19c-6.5 0-10-7-10-7a18 18 0 0 1 5.1-6M9.9 4.2A10.5 10.5 0 0 1 12 4c6.5 0 10 7 10 7a18 18 0 0 1-2.2 3.2M1 1l22 22M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      </svg>
    </button>
  </div>
</template>

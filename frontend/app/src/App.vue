<script setup>
import { onBeforeUnmount, ref } from 'vue'
import TransactionsView from './TransactionsView.vue'

const path = ref(window.location.pathname)
const search = ref(window.location.search)
const hash = ref(window.location.hash)

function onLocationChange() {
  path.value = window.location.pathname
  search.value = window.location.search
  hash.value = window.location.hash
}

function navigate(url) {
  window.history.pushState({}, '', url)
  onLocationChange()
}

window.addEventListener('popstate', onLocationChange)
window.addEventListener('hashchange', onLocationChange)
onBeforeUnmount(() => {
  window.removeEventListener('popstate', onLocationChange)
  window.removeEventListener('hashchange', onLocationChange)
})
</script>

<template>
  <TransactionsView :path="path" :search="search" :hash="hash" :navigate="navigate" />
</template>

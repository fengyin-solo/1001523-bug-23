<template>
  <section class="page" data-module="transmission">
    <header class="page-head">
      <div>
        <h2>数据传输管理</h2>
        <p class="page-desc">维护传输链路，围绕链路编号、所属站点、传输方式、上报频次做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记传输链路</button>
        <button class="btn" type="button" @click="exportRows">导出数据传输清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>数据标记</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-abnormal': row.abnormal }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="flag-cell">
            <template v-if="rowFlags(row).length">
              <span v-for="flag in rowFlags(row)" :key="flag" class="flag-badge">{{ flag }}</span>
            </template>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="acting"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无数据传输数据，可先登记传输链路</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据传输记录，待处理 {{ summary.pending }} 条</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | string[] | null>

type Summary = {
  total: number
  pending: number
  abnormal: number
  active: number
  alarming: number
  missing_reports: number
}

const ENDPOINT = '/api/transmission'
const columns = ["链路编号", "所属站点", "传输方式", "上报频次", "最近上报时刻", "缺报次数", "链路带宽", "链路状态"]
const actions = ["开通链路", "确认恢复", "停用链路"]
const emptySummary: Summary = { total: 0, pending: 0, abnormal: 0, active: 0, alarming: 0, missing_reports: 0 }

const rows = ref<Row[]>([])
const total = ref(0)
const summary = ref<Summary>({ ...emptySummary })
const acting = ref(false)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = computed(() => [
  { label: '在用链路', value: summary.value.active },
  { label: '缺报链路', value: summary.value.alarming },
  { label: '缺报次数合计', value: summary.value.missing_reports },
])

function rowFlags(row: Row): string[] {
  return Array.isArray(row.flags) ? (row.flags as string[]) : []
}

function currentQuery(): string {
  return new URLSearchParams(filters.value as Record<string, string>).toString()
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  const query = currentQuery()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  errorMessage.value = '传输链路登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (acting.value) {
    return
  }
  acting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? '数据传输动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输操作失败'
  } finally {
    acting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}?${currentQuery()}`)
    if (!response.ok) {
      throw new Error('传输链路列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    summary.value = { ...emptySummary, ...(payload.summary ?? {}) }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输列表读取失败'
  }
}

onMounted(reload)
</script>

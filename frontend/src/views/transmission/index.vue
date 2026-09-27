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
      <label class="filter-item">
        <span>链路编号</span>
        <input v-model="keyword" placeholder="按链路编号检索" />
      </label>
      <label class="filter-item">
        <span>链路状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
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
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row.issues?.length" class="issue-tag">{{ row.issues.join('；') }}</span>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无数据传输数据，可先登记传输链路</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>
        共 {{ total }} 条数据传输记录 · 待处理 {{ summary['待处理'] ?? 0 }} 条 · 数据标记 {{ summary['数据标记'] ?? 0 }} 条
      </span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & { id: number; status?: string; issues?: string[] }

const ENDPOINT = '/api/transmission'
const columns = ["链路编号", "所属站点", "传输方式", "上报频次", "最近上报时刻", "缺报次数", "链路带宽", "链路状态"]
const actions = ["开通链路", "确认恢复", "停用链路"]
const statuses = ["待开通", "正常上报", "缺报告警", "已停用"]
// 与后端状态流转表保持一致：只有起始状态匹配的链路才展示对应动作。
const ACTION_SOURCES: Record<string, string[]> = {
  开通链路: ["待开通"],
  确认恢复: ["缺报告警"],
  停用链路: ["待开通", "正常上报", "缺报告警"],
}

const rows = ref<Row[]>([])
const total = ref(0)
const summary = ref<Record<string, number>>({})
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const stats = computed(() => [
  { label: '在用链路', value: summary.value['在用链路'] ?? 0 },
  { label: '缺报链路', value: summary.value['缺报链路'] ?? 0 },
  { label: '今日缺报次数', value: summary.value['今日缺报次数'] ?? 0 },
])

function availableActions(row: Row) {
  return actions.filter((action) => (ACTION_SOURCES[action] ?? []).includes(String(row.status ?? '')))
}

function currentQuery() {
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  return params.toString()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
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
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.message ?? '数据传输动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = currentQuery()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error('传输链路列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    summary.value = payload.summary ?? {}
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据传输列表读取失败'
  }
}

onMounted(reload)
</script>

<template>
  <section class="page" data-module="export">
    <div class="notice-bar">
      <span>按批量交付编号交付：</span>
      <input
        v-model="packageForm.交付编号"
        class="inline-input"
        placeholder="如 DLV-20261120-0001"
      />
      <button class="btn" type="button" @click="submitPackage">生成导出包</button>
      <span v-if="packages.length">已落成 {{ packages.length }} 个：</span>
      <button
        v-for="item in packages"
        :key="item.交付编号"
        class="link"
        type="button"
        @click="openPackage(item.交付编号)"
      >
        {{ item.交付编号 }}（{{ item.记录条数 }} 条）
      </button>
    </div>
    <header class="page-head">
      <div>
        <h2>数据导出管理</h2>
        <p class="page-desc">维护导出任务，围绕任务编号、导出对象、导出格式、筛选条件做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记导出任务</button>
        <button class="btn" type="button" @click="exportRows">导出数据导出清单</button>
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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据导出数据，可先登记导出任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据导出记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="packageDetail" class="modal-overlay" @click.self="packageDetail = null">
        <div class="modal-card wide">
          <header class="modal-head">
            <h3>导出包 · {{ packageDetail.交付编号 }}</h3>
            <button class="btn ghost" type="button" @click="packageDetail = null">&times;</button>
          </header>
          <div class="modal-body">
            <div class="kv-row">
              <span>截面策略</span><strong>{{ packageDetail.截面策略 }}</strong>
              <span>订单合计</span><strong>{{ packageDetail.订单合计?.toFixed(2) }}</strong>
              <span>退款合计</span><strong>{{ packageDetail.退款合计?.toFixed(2) }}</strong>
              <span>记录条数</span><strong>{{ packageDetail.记录条数 }}</strong>
            </div>
            <p v-if="packageDetail.核对?.孤立退款.length" class="warn-text">
              孤立退款：{{ packageDetail.核对.孤立退款.map((r: AnyRow) => `${r.退款单号} ${r.退款金额}`).join('、') }}
            </p>
            <table class="data-table compact">
              <thead>
                <tr><th>类型</th><th>单据号</th><th>记账金额</th><th>截面</th><th>关联依据</th></tr>
              </thead>
              <tbody>
                <tr v-for="record in packageDetail.记录" :key="record.记录类型 + record.单据号">
                  <td>{{ record.记录类型 }}</td>
                  <td>{{ record.单据号 }}</td>
                  <td>{{ record.记账金额文本 }}</td>
                  <td>{{ record.取数边界?.截面号 }}</td>
                  <td>{{ describeBasis(record.关联依据) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <footer class="modal-foot">
            <button class="btn" type="button" @click="packageDetail = null">关闭</button>
          </footer>
        </div>
      </div>

      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记导出任务</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label v-for="field in columns.slice(0, 3)" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="createFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type AnyRow = Record<string, any>

const ENDPOINT = '/api/export'
const columns = ["任务编号", "导出对象", "导出格式", "筛选条件", "数据行数", "导出时间", "文件大小", "任务状态"]
const actions = ["开始导出", "重新导出", "标记失败"]
const statuses = ["待导出", "导出中", "已完成", "导出失败"]
const stats = [{"label": "待导出任务", "value": 0}, {"label": "已完成导出", "value": 0}, {"label": "失败导出", "value": 0}]

const rows = ref<Row[]>([])
const packages = ref<AnyRow[]>([])
const packageDetail = ref<AnyRow | null>(null)
const packageForm = ref({ 交付编号: '' })
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})

function updateStats() {
  const data = rows.value
  stats.length > 0 && (stats[0].value = data.filter((r: Row) => r.status === statuses[1] || r.pending).length)
  stats.length > 1 && (stats[1].value = data.filter((r: Row) => r.status && !r.pending && !r.abnormal).length)
  stats.length > 2 && (stats[2].value = data.filter((r: Row) => r.abnormal).length)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = ''
  createFields.value = {}
  showCreateModal.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createFields.value }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || '登记失败')
    }
    showCreateModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('数据导出动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据导出操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('导出任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据导出列表读取失败'
  }
}

function describeBasis(basis: AnyRow[]): string {
  if (!basis?.length) return '—'
  return basis
    .map((item) =>
      item.退款单号
        ? `退款 ${item.退款单号} ${item.退款金额}`
        : `${item.订单号}（${item.关联状态}）`
    )
    .join('；')
}

async function loadPackages() {
  try {
    const response = await request('/api/export/packages')
    if (!response.ok) return
    packages.value = (await response.json()).items ?? []
  } catch {
    packages.value = []
  }
}

async function submitPackage() {
  errorMessage.value = ''
  try {
    const response = await request('/api/export/packages', {
      method: 'POST',
      body: JSON.stringify({ values: { 交付编号: packageForm.value.交付编号, 导出格式: 'Excel' } }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '导出包生成失败')
    await loadPackages()
    await openPackage(payload.entry.交付编号)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出包生成失败'
  }
}

async function openPackage(deliveryNo: string) {
  try {
    const response = await request(`/api/export/packages/${deliveryNo}`)
    if (!response.ok) throw new Error('导出包读取失败')
    packageDetail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出包读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadPackages()
})
</script>

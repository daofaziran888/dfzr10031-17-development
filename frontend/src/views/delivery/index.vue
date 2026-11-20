<template>
  <section class="page" data-module="delivery">
    <header class="page-head">
      <div>
        <h2>批量交付与对账</h2>
        <p class="page-desc">
          按各数据服务的输出数据集与查询参数取明细，一次交付只采用一种截面口径；
          实付按订单记账，退款按退款单记账，孤立退款仍计入退款合计。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reloadAll">刷新</button>
        <button class="btn" type="button" @click="showCorrection = true">更正源数据</button>
        <button class="btn primary" type="button" @click="openCreate">发起批量交付</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <h3 class="section-title">数据截面</h3>
    <table class="data-table">
      <thead>
        <tr><th>数据集</th><th>截面号</th><th>版本</th><th>状态</th><th>生成时间</th><th>说明</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in snapshots" :key="item.截面号">
          <td>{{ item.数据集 }}</td>
          <td>{{ item.截面号 }}</td>
          <td>{{ item.版本 }}</td>
          <td>
            <span :class="['tag', item.状态 === '已确认' ? 'tag-ok' : 'tag-warn']">{{ item.状态 }}</span>
          </td>
          <td>{{ item.生成时间 }}</td>
          <td>{{ item.说明 }}</td>
          <td class="row-actions">
            <button
              v-if="item.状态 !== '已确认'"
              class="link"
              type="button"
              @click="confirmSnapshot(item.截面号)"
            >
              确认截面
            </button>
            <span v-else class="hint-text">已确认</span>
          </td>
        </tr>
        <tr v-if="!snapshots.length">
          <td colspan="7" class="empty-state">暂无数据截面</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">批量交付记录</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>交付编号</th><th>服务范围</th><th>截面策略</th><th>状态</th>
          <th>订单合计</th><th>退款合计</th><th>明细条数</th><th>交付时间</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in deliveries" :key="item.交付编号">
          <td>{{ item.交付编号 }}</td>
          <td>{{ (item.服务编号 || []).join('、') }}</td>
          <td>{{ item.截面策略 }}</td>
          <td>
            <span :class="['tag', item.状态 === '已交付' ? 'tag-ok' : 'tag-warn']">{{ item.状态 }}</span>
          </td>
          <td>{{ item.状态 === '已交付' && item.订单合计 != null ? item.订单合计.toFixed(2) : '—' }}</td>
          <td>{{ item.状态 === '已交付' && item.退款合计 != null ? item.退款合计.toFixed(2) : '—' }}</td>
          <td>{{ item.明细条数 }}</td>
          <td>{{ item.交付时间 }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(item.交付编号)">复查</button>
            <button
              v-if="item.状态 === '待补取'"
              class="link"
              type="button"
              @click="retry(item.交付编号)"
            >
              补取
            </button>
            <button
              v-if="item.状态 === '已交付'"
              class="link"
              type="button"
              @click="fileDelivery(item.交付编号)"
            >
              交付导出
            </button>
          </td>
        </tr>
        <tr v-if="!deliveries.length">
          <td colspan="9" class="empty-state">暂无批量交付，先发起一次订单 + 退款交付</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ deliveries.length }} 次批量交付 · 交付 {{ filedCount }} 个导出包</span>
      <span v-if="message" :class="okFlag ? '' : 'error-text'">{{ message }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card wide">
          <header class="modal-head">
            <h3>发起批量交付</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label class="modal-field">
              <span>数据服务（多选）</span>
              <label v-for="svc in services" :key="svc.服务编号" class="check-item">
                <input v-model="createForm.服务编号" type="checkbox" :value="svc.服务编号" />
                {{ svc.服务编号 }} · {{ svc.服务名称 }}（{{ svc.输出数据集 }}）
              </label>
            </label>
            <label class="modal-field">
              <span>截面策略</span>
              <select v-model="createForm.截面策略">
                <option v-for="policy in policies" :key="policy" :value="policy">{{ policy }}</option>
              </select>
            </label>
            <label class="modal-field">
              <span>开始日期（可选）</span>
              <input v-model="createForm.开始日期" placeholder="YYYY-MM-DD" />
            </label>
            <label class="modal-field">
              <span>结束日期（可选）</span>
              <input v-model="createForm.结束日期" placeholder="YYYY-MM-DD" />
            </label>
            <label class="modal-field">
              <span>原订单号（可选，仅退款服务生效）</span>
              <input v-model="createForm.原订单号" placeholder="如 ORD-1001" />
            </label>
            <p class="hint-text">{{ policyHint }}</p>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">生成交付</button>
            </footer>
          </form>
        </div>
      </div>

      <div v-if="detail" class="modal-overlay" @click.self="detail = null">
        <div class="modal-card wide">
          <header class="modal-head">
            <h3>交付复查 · {{ detail.交付编号 }}</h3>
            <button class="btn ghost" type="button" @click="detail = null">&times;</button>
          </header>
          <div class="modal-body">
            <div class="kv-row">
              <span>状态</span><strong>{{ detail.状态 }}</strong>
              <span>截面策略</span><strong>{{ detail.截面策略 }}</strong>
              <span>订单合计</span><strong>{{ detail.订单合计?.toFixed(2) }}</strong>
              <span>退款合计</span><strong>{{ detail.退款合计?.toFixed(2) }}</strong>
            </div>
            <p class="hint-text">{{ detail.口径说明 }}</p>

            <h4>逐服务取数边界</h4>
            <table class="data-table compact">
              <thead>
                <tr>
                  <th>服务</th><th>数据集</th><th>截面</th><th>截面状态</th>
                  <th>查询参数</th><th>命中行数</th><th>记账合计</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="scope in detail.服务范围 || []" :key="scope.服务编号 + scope.输出数据集">
                  <td>{{ scope.服务编号 }}</td>
                  <td>{{ scope.输出数据集 }}</td>
                  <td>{{ scope.截面号 }}（v{{ scope.截面版本 }}）</td>
                  <td>{{ scope.截面状态 }}</td>
                  <td>{{ formatParams(scope.取数边界?.查询参数) }}</td>
                  <td>{{ scope.取数边界?.命中行数 }}</td>
                  <td>{{ scope.记账合计 }}</td>
                </tr>
                <tr v-if="!(detail.服务范围 || []).length">
                  <td colspan="7" class="empty-state">交付尚未补齐截面，无取数边界</td>
                </tr>
              </tbody>
            </table>

            <template v-if="detail.核对">
              <h4>关联核对</h4>
              <table class="data-table compact">
                <thead>
                  <tr><th>订单号</th><th>实付</th><th>关联退款单</th><th>退款金额</th><th>净额</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in detail.核对.订单明细" :key="row.订单号">
                    <td>{{ row.订单号 }}</td>
                    <td>{{ row.实付金额 }}</td>
                    <td>{{ row.关联退款单号.join('、') || '—' }}</td>
                    <td>{{ row.关联退款.join('、') || '—' }}</td>
                    <td>{{ row.净额 }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-if="detail.核对.孤立退款.length" class="warn-text">
                孤立退款（无原订单，仍计入退款合计）：
                <span v-for="row in detail.核对.孤立退款" :key="row.退款单号">
                  {{ row.退款单号 }} {{ row.退款金额 }}（原订单 {{ row.原订单号 }}）
                </span>
              </p>
            </template>

            <template v-if="detail.待复核?.length">
              <h4>待复核</h4>
              <p v-for="note in detail.待复核" :key="note.输出数据集" class="warn-text">
                {{ note.输出数据集 }}：{{ note.说明 }}
              </p>
            </template>

            <h4>留存明细（{{ (detail.明细 || []).length }} 条）</h4>
            <table class="data-table compact">
              <thead>
                <tr><th>数据集</th><th>序号</th><th>单据号</th><th>记账金额</th><th>截面</th><th>明细指纹</th></tr>
              </thead>
              <tbody>
                <tr v-for="line in detail.明细 || []" :key="line.id">
                  <td>{{ line.输出数据集 }}</td>
                  <td>{{ line.序号 }}</td>
                  <td>{{ line.明细['订单号'] || line.明细['退款单号'] }}</td>
                  <td>{{ (line.记账金额 / 100).toFixed(2) }}</td>
                  <td>{{ line.取数边界?.截面号 }}</td>
                  <td class="mono">{{ line.取数边界?.明细指纹 }}</td>
                </tr>
              </tbody>
            </table>

            <template v-if="recon">
              <h4>源数据复核</h4>
              <p v-if="!recon.差异条数" class="hint-text">留存明细与当前源数据一致，无差异。</p>
              <table v-else class="data-table compact">
                <thead>
                  <tr><th>数据集</th><th>单据号</th><th>变化</th><th>交付时金额</th><th>当前金额</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in recon.差异" :key="row.单据号">
                    <td>{{ row.输出数据集 }}</td>
                    <td>{{ row.单据号 }}</td>
                    <td>{{ row.变化 }}</td>
                    <td>{{ row.交付时金额 || '—' }}</td>
                    <td>{{ row.当前金额 || '—' }}</td>
                  </tr>
                </tbody>
              </table>
              <p class="hint-text">
                复核只读当前源数据并列出差异，不会改动本交付留存明细；
                如需采用更正后数据，请按「最新重取」另发起一次交付。
              </p>
            </template>
          </div>
          <footer class="modal-foot">
            <button class="btn" type="button" @click="detail = null">关闭</button>
          </footer>
        </div>
      </div>

      <div v-if="showCorrection" class="modal-overlay" @click.self="showCorrection = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>更正源数据</h3>
            <button class="btn ghost" type="button" @click="showCorrection = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCorrection">
            <label class="modal-field">
              <span>数据集</span>
              <select v-model="correctionForm.数据集">
                <option value="退款">退款</option>
                <option value="订单">订单</option>
              </select>
            </label>
            <label class="modal-field">
              <span>单据号</span>
              <input v-model="correctionForm.单据号" required />
            </label>
            <label class="modal-field">
              <span>更正金额</span>
              <input v-model="correctionForm.金额" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCorrection = false">取消</button>
              <button class="btn primary" type="submit">提交更正</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type AnyRow = Record<string, any>

const DELIVERY = '/api/data_service/deliveries'
const snapshots = ref<AnyRow[]>([])
const deliveries = ref<AnyRow[]>([])
const packages = ref<AnyRow[]>([])
const services = ref<AnyRow[]>([])
const policies = ref<string[]>(['已确认一致', '最新重取'])
const detail = ref<AnyRow | null>(null)
const recon = ref<AnyRow | null>(null)
const message = ref('')
const okFlag = ref(true)
const showCreateModal = ref(false)
const showCorrection = ref(false)
const createForm = ref<{ 服务编号: string[]; 截面策略: string; 开始日期: string; 结束日期: string; 原订单号: string }>({
  服务编号: ['SVC-ORDER', 'SVC-REFUND'],
  截面策略: '已确认一致',
  开始日期: '',
  结束日期: '',
  原订单号: '',
})
const correctionForm = ref({ 数据集: '退款', 单据号: '', 金额: '' })

const filedCount = computed(() => packages.value.length)
const policyHint = computed(() =>
  createForm.value.截面策略 === '已确认一致'
    ? '只交付各服务均已确认的旧截面：口径最一致，但源数据更正前需重新发起交付才会体现。'
    : '各服务均取各自最新截面（可能含待确认更正）：交付前需重新核对退款/订单合计。'
)

const stats = computed(() => {
  const delivered = deliveries.value.filter((row) => row.状态 === '已交付')
  const suspended = deliveries.value.filter((row) => row.状态 === '待补取')
  return [
    { label: '已交付批次', value: delivered.length },
    { label: '待补取批次', value: suspended.length },
    { label: '已确认截面', value: snapshots.value.filter((row) => row.状态 === '已确认').length },
    { label: '待确认截面', value: snapshots.value.filter((row) => row.状态 !== '已确认').length },
  ]
})

function setMessage(text: string, ok = true) {
  message.value = text
  okFlag.value = ok
}

function formatParams(params: AnyRow | undefined) {
  if (!params || !Object.keys(params).length) return '无'
  return Object.entries(params)
    .map(([key, val]) => `${key}=${val}`)
    .join('，')
}

async function reloadAll() {
  try {
    const [snapPayload, deliveryPayload, packagePayload, servicePayload] = await Promise.all([
      request('/api/data_service/snapshots').then((res) => res.json()),
      request(DELIVERY).then((res) => res.json()),
      request('/api/export/packages').then((res) => res.json()),
      request('/api/data_service?size=200').then((res) => res.json()),
    ])
    snapshots.value = snapPayload.items ?? []
    policies.value = snapPayload.policies ?? policies.value
    deliveries.value = deliveryPayload.items ?? []
    packages.value = packagePayload.items ?? []
    services.value = servicePayload.items ?? []
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '交付数据读取失败', false)
  }
}

function openCreate() {
  showCreateModal.value = true
}

async function submitCreate() {
  const values: AnyRow = {
    服务编号: createForm.value.服务编号,
    截面策略: createForm.value.截面策略,
  }
  const params: AnyRow = {}
  if (createForm.value.开始日期) params['开始日期'] = createForm.value.开始日期
  if (createForm.value.结束日期) params['结束日期'] = createForm.value.结束日期
  if (createForm.value.原订单号) params['原订单号'] = createForm.value.原订单号
  if (Object.keys(params).length) values['查询参数'] = params
  try {
    const response = await request(DELIVERY, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    setMessage(payload.message, payload.ok)
    if (payload.entry?.状态 === '已交付') {
      showCreateModal.value = false
      await reloadAll()
      await openDetail(payload.entry.交付编号)
    } else {
      await reloadAll()
    }
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '批量交付失败', false)
  }
}

async function openDetail(deliveryNo: string) {
  try {
    const [detailPayload, reconPayload] = await Promise.all([
      request(`${DELIVERY}/${deliveryNo}`).then((res) => res.json()),
      request(`${DELIVERY}/${deliveryNo}/reconcile`).then((res) => res.json()),
    ])
    if (detailPayload.detail) throw new Error(detailPayload.detail)
    detail.value = detailPayload
    recon.value = reconPayload
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '交付复查失败', false)
  }
}

async function confirmSnapshot(snapshotNo: string) {
  try {
    const response = await request(`/api/data_service/snapshots/${snapshotNo}/confirm`, {
      method: 'POST',
    })
    const payload = await response.json()
    setMessage(payload.message, payload.ok)
    await reloadAll()
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '截面确认失败', false)
  }
}

async function retry(deliveryNo: string) {
  try {
    const response = await request(`${DELIVERY}/${deliveryNo}/retry`, { method: 'POST' })
    const payload = await response.json()
    setMessage(payload.message, payload.ok)
    await reloadAll()
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '补取失败', false)
  }
}

async function fileDelivery(deliveryNo: string) {
  try {
    const response = await request('/api/export/packages', {
      method: 'POST',
      body: JSON.stringify({ values: { 交付编号: deliveryNo, 导出格式: 'Excel' } }),
    })
    const payload = await response.json()
    setMessage(payload.message, payload.ok)
    await reloadAll()
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '导出交付失败', false)
  }
}

async function submitCorrection() {
  try {
    const response = await request(
      `/api/data_service/source/${correctionForm.value.数据集}/corrections`,
      {
        method: 'POST',
        body: JSON.stringify({
          values: {
            单据号: correctionForm.value.单据号,
            字段: correctionForm.value.数据集 === '退款' ? '退款金额' : '实付金额',
            金额: correctionForm.value.金额,
          },
        }),
      }
    )
    const payload = await response.json()
    setMessage(payload.message, payload.ok)
    if (payload.ok) {
      showCorrection.value = false
      await reloadAll()
    }
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '源数据更正失败', false)
  }
}

onMounted(reloadAll)
</script>

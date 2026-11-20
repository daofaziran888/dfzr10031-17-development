# 数据分析实验与数据应用服务平台

面向指标口径管理、分析实验设计、OLAP查询、数据看板构建与数据API发布的数据应用平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标定义 | `metric_def` | 指标 | 指标编号、指标名称、计算公式 |
| 维度管理 | `dimension` | 分析维度 | 维度编号、维度名称、维度类型 |
| 数据集管理 | `dataset` | 分析数据集 | 数据集编号、数据集名称、来源类型 |
| 分析实验 | `experiment` | 实验方案 | 方案编号、实验名称、分析数据集 |
| OLAP查询 | `query_builder` | 查询模板 | 模板编号、模板名称、查询语句 |
| 数据看板 | `dashboard` | 看板配置 | 看板编号、看板名称、包含图表 |
| 图表配置 | `chart` | 图表 | 图表编号、图表名称、图表类型 |
| 数据API发布 | `data_service` | 数据服务 | 服务编号、服务名称、输出数据集 |
| 批量交付 | `data_service`（`/api/data_service/deliveries`）、页面 `delivery` | 交付批次 | 交付编号、服务范围、截面策略、订单合计、退款合计 |
| 智能告警 | `alert` | 告警规则 | 规则编号、告警名称、监控指标 |
| 分析用户组 | `user_group` | 用户组 | 组编号、组名称、组描述 |
| 数据快照 | `snapshot` | 快照记录 | 快照编号、数据集名称、快照时间 |
| 任务调度 | `scheduler` | 调度任务 | 任务编号、任务名称、调度类型 |
| 缓存管理 | `cache` | 缓存配置 | 缓存编号、缓存目标、缓存策略 |
| 分析管道 | `pipeline` | 分析节点 | 节点编号、输入数据集、分析算子 |
| 分析模型 | `model` | 模型配置 | 模型编号、模型名称、模型类型 |
| 数据集市 | `data_mart` | 集市表 | 表编号、表名称、主题域 |
| 数据导出 | `export` | 导出任务 / 交付导出包 | 任务编号、导出对象、导出格式；交付编号、记录与关联依据 |
| 数据审计 | `audit` | 审计记录 | 记录编号、操作类型、操作人 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 批量交付与财务对账

数据服务（`SVC-ORDER` 订单明细、`SVC-REFUND` 退款明细）按各自的输出数据集和查询参数
读取明细，由批量交付把多个服务的记录打成一个交付包；数据导出再按交付编号交付每条记录
及其关联依据（订单关联的退款单、退款指向的原订单）。

### 口径

- 实付金额按订单记账：同一订单关联两张退款单时，实付只累计一次。
- 退款金额按退款单记账：找不到原订单的退款（孤立退款）仍计入退款合计，并单列出来。
- 一次完整交付只采用一种截面策略：
  - `已确认一致`：各服务都取已确认截面，口径一致但可能落后于源数据更正；
  - `最新重取`：各服务都取各自最新截面（可含待确认更正），交付前重新核对。
- 任一服务缺截面时不落半包，交付状态置为 `待补取`，补齐后可对同一交付编号重试。

### 验收样例

| 项目 | 单据 | 金额 |
| --- | --- | --- |
| 订单 | ORD-1001 | 实付 120.00 |
| 退款 | REF-1001（关联 ORD-1001） | 30.00 |
| 退款 | REF-1002（关联 ORD-1001） | 20.00 |
| 孤立退款 | REF-9001（原订单 ORD-9999 不存在） | 7.00 |

按 `已确认一致` 交付：订单合计 120.00、退款合计 57.00，孤立退款为 REF-9001。
在源数据把 REF-1002 由 20.00 更正为 25.00 后，再用原交付编号打开只回放当时的留存明细
（退款仍为 57.00），复核接口会单独列出「交付时 20.00 / 当前 25.00」的差异；
另发起一次 `最新重取` 交付则口径为退款合计 62.00。两种口径不会出现在同一个交付里。

### 接口

```text
GET  /api/data_service/snapshots                     数据截面及确认状态
POST /api/data_service/snapshots/{截面号}/confirm     服务确认截面
POST /api/data_service/deliveries                    发起批量交付
GET  /api/data_service/deliveries                    交付列表
GET  /api/data_service/deliveries/{交付编号}          按编号回放留存明细与金额
GET  /api/data_service/deliveries/{交付编号}/reconcile 复核差异
POST /api/data_service/deliveries/{交付编号}/retry    挂起交付补取
POST /api/data_service/source/{数据集}/corrections    更正源数据并生成待确认截面

一条完整交付只保存一个截面策略；`已确认一致` 与 `最新重取` 是两次独立交付，
同一交付编号下不会混用两种口径。
POST /api/export/packages                            按交付编号生成导出包
GET  /api/export/packages/{交付编号}                  导出包记录与关联依据
```

### 测试

```bash
cd backend && python3 -m unittest discover -s tests -v
```

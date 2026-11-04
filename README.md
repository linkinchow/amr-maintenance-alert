# AMR 维护开始／结束 → 飞书卡片

Azure Managed Redis（AMR）开始维护和维护结束时，把 Resource Health 事件推送成飞书交互卡片。卡片版式与 [azure-alert](https://github.com/linkinchow/azure-alert) 一致。部署和验证都不会对 Redis 做维护、重启或故障转移。

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FOWNER%2FREPO%2Fmain%2Fazuredeploy.json/createUIDefinitionUri/https%3A%2F%2Fraw.githubusercontent.com%2FOWNER%2FREPO%2Fmain%2Fui%2FcreateUiDefinition.json)

> 仓库发布到 GitHub 后，把按钮链接中的 `OWNER%2FREPO` 换成实际的仓库路径（例如 `myorg%2Famr-maintenance-alert`）。

## 架构

```text
订阅 A 的 AMR → 订阅 A 告警规则 ──┐
订阅 B 的 AMR → 订阅 B 告警规则 ──┼→ 订阅 A：Action Group → Logic App → 飞书卡片
订阅 C 的 AMR → 订阅 C 告警规则 ──┘
```

- 每个被监控订阅一条 `ala-amr-health-events`，覆盖该订阅当前和以后所有 `Microsoft.Cache/redisEnterprise` 的 InProgress／Resolved 健康事件。一条规则不能跨订阅，所以按订阅各建一条。
- 部署订阅里放 `ag-amr-maintenance-feishu` 和 `logic-amr-maintenance-feishu`，发到专用飞书机器人。
- 一次订阅级部署（`azuredeploy.json`）建好全部资源，被监控订阅在部署向导里多选。

## 卡片

| 情况 | 颜色 | 标题 |
|---|---|---|
| 维护开始（原文为 Planned maintenance） | 橙 | `警告｜AMR 维护开始｜<实例>` |
| 维护结束 | 绿 | `已恢复｜AMR 维护结束｜<实例>` |
| 原文无法确认是维护 | 蓝（开始）/ 绿（结束） | `提示｜AMR 健康事件（维护类型未确认）｜<实例>` |
| 回放 / 链路测试 | 同上 | 前缀 `[TEST 历史回放]` / `[TEST 通知链路验证]` |

字段：时间（北京时间）、实例、订阅、订阅 ID、资源组、阶段、事件状态、Event ID；分隔线下是事件原文；“在 Azure 门户中查看”按钮；底部注明 `Azure 告警 · 来源 AMR 维护 · ActivityLog`。

## 部署

### Deploy to Azure

向导共三步：

1. **基本信息**：部署订阅、区域、资源组名（默认 `rg-amr-alerts`）。
2. **飞书通知**：飞书 webhook（安全参数）。
3. **监控订阅**：可搜索、可全选的订阅多选框。

部署人需要对选中的每个订阅有创建资源组和告警规则的权限。

### Azure CLI

```bash
az deployment sub create --subscription <deployment-subscription-id> --location <region> --name amr-maintenance-alerts --template-file azuredeploy.json --parameters @main.parameters.local.json --parameters feishuWebhookUrl="$FEISHU_WEBHOOK_URL"
```

`main.parameters.local.json` 的格式、validate／what-if 和验收步骤见[客户部署指南](docs/customer-deployment.zh-CN.md)。

| 参数 | 说明 |
|---|---|
| `location` | 资源组和 Logic App 的区域 |
| `feishuWebhookUrl` | 飞书 / Lark 自定义机器人 webhook（secure） |
| `subscriptions` | 被监控订阅 `[{"id": "...", "name": "卡片里显示的名称"}]`，同时是工作流的允许清单；默认只有部署订阅 |
| `resourceGroupName` | 默认 `rg-amr-alerts`，部署订阅和每个被监控订阅都用这个名字 |
| `logicAppName` / `actionGroupName` / `ruleName` | 默认与已有部署一致，可原地升级 |
| `ruleEnabled` | 默认 `true`；测试实例设为 `false`，避免真实事件发到测试群 |

## 目录

```
main.bicep                       入口（subscription 作用域）
modules/notifications.bicep      Logic App + Action Group
modules/workflow.json            Logic App 定义（scripts/build_templates.py 生成）
modules/subscription-alert.bicep 订阅级活动日志告警规则
modules/resource-group.bicep     各订阅的资源组
azuredeploy.json                 az bicep build 生成，供 Deploy to Azure 使用
ui/createUiDefinition.json       门户部署向导
scripts/                         生成器、回放、canary、探测、CI 检查
samples/                         回放样例（占位订阅和实例）
test/                            测试实例参数示例（真实参数放 *.local.json，不进 git）
tests/                           离线单元测试
docs/                            部署指南、运维记录、实测报告
```

## 开发

修改工作流或卡片时先改生成器，再重新生成：

```bash
python scripts/build_templates.py
```

```bash
az bicep build -f main.bicep --outfile azuredeploy.json
```

```bash
python -m unittest discover -s tests -v
```

GitHub Actions 会用 Bicep 0.44.1 重新构建，检查 `azuredeploy.json` 和 `modules/workflow.json` 是否已重新生成，并跑单元测试。

## 环境配置（管理脚本）

租户和订阅 ID 不进仓库。管理脚本从 `config.local.json` 读取（已被 `.gitignore` 排除），也可以用环境变量 `AMR_CONFIG` 指定其他路径：

```bash
cp config.example.json config.local.json
```

- `tenantId`：所有订阅所在的租户。
- `hubSubscriptionId`：部署订阅（Action Group 和 Logic App 所在），必须同时列在 `subscriptions` 里。
- `subscriptions`：订阅 ID → 显示名。
- `location`：区域。

仓库里的样例和文档只用占位 ID，离线测试会检查仓库里没有真实 GUID。

| 脚本 | 用途 |
|---|---|
| `scripts/write_parameters.py` | 从 `config.local.json` 生成 `main.parameters.local.json`（不进 git） |
| `scripts/build_templates.py` | 生成 `modules/workflow.json` |
| `scripts/build_samples.py` | 生成 TEST 回放和负面测试样例 |
| `scripts/replay.py --file maintenance-start.json --send-test` | 把样例中的占位订阅换成部署订阅，发给 Logic App，会向飞书群发 TEST 卡片；`--resource-group` / `--logic-app` 可以指向测试实例 |
| `scripts/canary.py prepare\|fire\|cleanup --apply` | 在各订阅建无接收器的临时资源，用它的写操作触发告警，验证“规则 → Action Group → Logic App → 飞书”整条链路（不是 AMR 维护）；`--resource-group` / `--action-group` 可以指向测试实例 |
| `scripts/probe_scopes.py --apply` | 单订阅 / 跨订阅规则对照实验，临时规则自动清理 |
| `scripts/ci_check.py` | 与 GitHub Actions 相同的检查 |

## 通知语义

- InProgress 表示开始／进行中，Resolved 表示结束；原始 `status` 分别可能为 Started、Succeeded。
- 原文明确包含 Planned maintenance 才称为维护；缺少原文时也会发卡片，标为“维护类型未确认”。绝不把规则描述当成维护原文。
- Action Group 用原生活动日志格式（`useCommonAlertSchema=false`），工作流也兼容 Common Alert Schema。
- 活动日志告警是无状态的，结束事件也会产生 Fired 实例。
- 不做持久化去重：Azure 投递或 HTTP 重试可能导致重复卡片，用 Event ID 辨认。
- 只通知开始和结束，不是提前预告；实测从事件发生到 Logic App 开始处理约 2–7 分钟，不保证在故障转移前送达。

## 配合维护窗口

告警只在维护开始和结束时通知，不能决定维护什么时候发生。AMR 的计划维护窗口（预览版）可以把 Redis 服务端更新、来宾系统更新等大部分维护安排到业务低峰；主机、网络、紧急安全补丁等维护不受窗口约束，仍可能在窗口外触发告警。配置要求和门户 / CLI / Bicep 的设置方法见[维护窗口配置](docs/maintenance-window.zh-CN.md)。

## 文档

- [客户部署指南（多订阅、Deploy to Azure / CLI）](docs/customer-deployment.zh-CN.md)
- [内部部署与运维记录](docs/deployment.zh-CN.md)
- [维护窗口配置（门户 / CLI / Bicep）](docs/maintenance-window.zh-CN.md)
- [实测结果与边界](docs/test-results.zh-CN.md)
- [跨订阅 API 原始证据（已脱敏）](docs/scope-probe-results.json)

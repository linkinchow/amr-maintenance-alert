# Azure Managed Redis 维护通知：多订阅客户部署指南

## 1. 目标架构

在同一 Microsoft Entra 租户的多个订阅中部署 AMR 健康事件告警，集中发送飞书卡片。

- **部署订阅（下文称 A）**：资源组里放 Action Group、Consumption Logic App；如果 A 也被选为监控订阅，同一资源组里还有 A 的告警规则。
- **每个被监控的订阅**：建同名资源组和一条订阅级告警规则，引用 A 的 Action Group。
- 每个订阅只需一条规则，覆盖该订阅当前和以后的所有 AMR，不需要按实例建规则。一条规则不能跨订阅（`ScopeIsInvalid`），所以按订阅各建一条。

```text
订阅 A 的 AMR → 订阅 A 告警规则 ──┐
订阅 B 的 AMR → 订阅 B 告警规则 ──┼→ 订阅 A：Action Group → Logic App → 飞书卡片
订阅 C 的 AMR → 订阅 C 告警规则 ──┘
```

一次部署完成全部资源：`azuredeploy.json`（由 `main.bicep` 生成）是订阅级模板，用嵌套部署在每个选中的订阅里建资源组和规则。

### 资源放在哪里

所有订阅使用同一个资源组名，由参数 `resourceGroupName` 决定（默认 `rg-amr-alerts`）：

| 订阅 | 资源组 | 里面的资源 |
|---|---|---|
| 部署订阅 A | `rg-amr-alerts` | Logic App、Action Group；A 也被选为监控订阅时，还有 A 的告警规则 |
| 被监控订阅 B、C…… | `rg-amr-alerts` | 只有本订阅的告警规则 `ala-amr-health-events` |

- 资源组不存在时由部署自动创建，区域为部署时选择的区域；告警规则和 Action Group 是全局资源，不受资源组区域影响。
- 规则所在资源组和 AMR 所在资源组无关：规则的 scope 是整个订阅，覆盖该订阅任意资源组、任意区域的 AMR，以后新建的 AMR 也自动纳入。
- 目前不支持按订阅指定不同的资源组名。

### 通知能力与边界

- 监听 Resource Health 的 `InProgress` 和 `Resolved` 事件，分别表示开始／进行中和结束。
- 卡片格式（与 azure-alert 一致）：
  - 事件原文明确是计划维护：开始为橙色 `警告｜AMR 维护开始｜<实例>`，结束为绿色 `已恢复｜AMR 维护结束｜<实例>`。
  - 原文不足以判断：开始为蓝色 `提示｜AMR 健康事件（维护类型未确认）｜<实例>`，结束为绿色；不会静默丢弃。
  - 字段：时间（北京时间）、实例、订阅、订阅 ID、资源组、阶段、事件状态、Event ID；分隔线下是事件原文，附“在 Azure 门户中查看”按钮。
- **不是提前维护预告，也不保证通知先于连接抖动到达。** 实测从事件发生到 Logic App 开始处理约 2–7 分钟。
- 每个开始／结束事件分别通知；事件跨度不等于业务中断时长。
- 只发飞书，不默认发邮件。
- 资源类型过滤为 `Microsoft.Cache/redisEnterprise`，也会匹配同订阅的旧 Redis Enterprise。
- 不做持久化去重，平台或 HTTP 重试可能产生重复通知，用 Event ID 辨认；同一批实例同时维护会有多张卡片。

## 2. 前提、权限与变更范围

### 2.1 前提

- 所有订阅属于同一租户，状态为 Enabled。
- 部署订阅 A 稳定可用；A 不可用时，所有订阅的集中通知都会受影响。
- 选择支持 Consumption Logic Apps 的区域。
- 飞书群已创建专用自定义机器人，并已批准向该群发送资源名称、订阅 ID 等告警元数据。
- 机器人不要开启签名校验（模板不生成签名字段）。Logic App 出口 IP 不固定，不适合用 IP 白名单；如果配置关键词，需要确认卡片内容包含该关键词。
- 订阅的 `Microsoft.Insights`、A 的 `Microsoft.Logic` 资源提供程序已注册（未注册时需要订阅级注册权限）。

### 2.2 权限

部署人需要：

- A：创建资源组、订阅级部署，以及 Logic App、Action Group、活动日志告警规则的创建／更新权限。
- 每个被监控的订阅：创建资源组、部署，以及活动日志告警规则的创建／更新权限。

工作流不在运行时调用 ARM，不需要托管身份或额外 RBAC；不需要 Redis 访问密钥。

### 2.3 注意现有资源

ARM 会更新同名资源：同名 Logic App 的定义和参数、同名 Action Group 的接收器、同名规则的条件和动作都会被覆盖。**不要把资源组和资源名指向客户已有但用途不同的资源。** 部署前用 what-if 确认（CLI 方式）。

## 3. 方式一：Deploy to Azure（门户向导）

点击仓库 README 中的 **Deploy to Azure** 按钮，在门户中按向导操作：

1. **基本信息**：这一页的“订阅”是**部署订阅 A**（只放 Logic App 和 Action Group），再选区域、填写资源组名称（默认 `rg-amr-alerts`）。
2. **飞书通知**：输入飞书 webhook。它是安全参数，只保存在 Logic App 中，不会出现在部署输出里。建议同时填写**自检告警邮箱**（多个用逗号分隔），见第 8 节。
3. **监控订阅**：从下拉框（可搜索、可全选）勾选要监控 AMR 的订阅；卡片里显示的订阅名称取自这里。只勾选有写权限的订阅：全选会包含只读订阅，对它们建规则会失败。部署订阅也有 AMR 时，在这里同样勾上。
4. **检查 + 创建**：确认后部署，嵌套部署会在每个选中的订阅里建资源组和规则。

部署完成后，按第 5 节回读，按第 6 节做消息验证。

## 4. 方式二：Azure CLI

使用 Bash + Azure CLI；所有 `az` 操作都显式指定订阅。

### 4.1 准备参数

```bash
export SUB_A="<deployment-subscription-id>" LOCATION="<supported-azure-region>"
```

生成参数文件（不含秘密）。`subscriptions` 列出所有被监控订阅的 ID 和卡片里显示的名称：

```bash
cat > main.parameters.local.json <<'EOF'
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "location": { "value": "<supported-azure-region>" },
    "subscriptions": { "value": [
      { "id": "<subscription-a-id>", "name": "订阅 A" },
      { "id": "<subscription-b-id>", "name": "订阅 B" },
      { "id": "<subscription-c-id>", "name": "订阅 C" }
    ] }
  }
}
EOF
```

其他可选参数：`resourceGroupName`（默认 `rg-amr-alerts`）、`logicAppName`、`actionGroupName`、`ruleName`、`ruleEnabled`（默认 `true`）、`tags`。

确认所有订阅在同一租户且状态正常：

```bash
for SUB in <subscription-a-id> <subscription-b-id> <subscription-c-id>; do az account show --subscription "$SUB" --query '{id:id,name:name,tenantId:tenantId,state:state}' --output json || break; done
```

### 4.2 输入 webhook

```bash
read -rsp "Feishu webhook URL: " FEISHU_WEBHOOK_URL
```

不要启用 `set -x` 或 CLI `--debug`。隐藏输入可以避免把秘密写进 shell history，但命令参数仍可能被本机其他高权限进程读到；生产自动化建议使用受控的秘密注入或 Key Vault 参数引用。

### 4.3 验证、预览、部署

```bash
az deployment sub validate --subscription "$SUB_A" --location "$LOCATION" --name amr-maintenance-alerts --template-file azuredeploy.json --parameters @main.parameters.local.json --parameters feishuWebhookUrl="$FEISHU_WEBHOOK_URL" --query properties.provisioningState --output tsv
```

```bash
az deployment sub what-if --subscription "$SUB_A" --location "$LOCATION" --name amr-maintenance-alerts --template-file azuredeploy.json --parameters @main.parameters.local.json --parameters feishuWebhookUrl="$FEISHU_WEBHOOK_URL" --result-format ResourceIdOnly
```

确认变更只涉及预期的资源组、Logic App、Action Group 和每个订阅的规则。

```bash
az deployment sub create --subscription "$SUB_A" --location "$LOCATION" --name amr-maintenance-alerts --template-file azuredeploy.json --parameters @main.parameters.local.json --parameters feishuWebhookUrl="$FEISHU_WEBHOOK_URL" --query '{state:properties.provisioningState,outputs:properties.outputs}' --output json
```

```bash
unset FEISHU_WEBHOOK_URL
```

## 5. 部署回读

输出只有资源 ID，不含 callback 或 webhook。只读 Action Group 的非敏感字段：

```bash
az monitor action-group show --subscription "$SUB_A" --resource-group rg-amr-alerts --name ag-amr-maintenance-feishu --query '{id:id,enabled:enabled,logicApps:logicAppReceivers[].{name:name,resourceId:resourceId,useCommonAlertSchema:useCommonAlertSchema}}' --output json
```

预期 Action Group 启用，接收器指向本次的 Logic App，`useCommonAlertSchema=false`（原生活动日志格式）。

逐个订阅回读规则：

```bash
az monitor activity-log alert show --subscription "<subscription-id>" --resource-group rg-amr-alerts --name ala-amr-health-events --query '{enabled:enabled,scope:scopes,condition:condition,actionGroups:actions.actionGroups[].actionGroupId}' --output json
```

确认 `enabled=true`，scope 是本订阅，条件为 `ResourceHealth` + `Microsoft.Cache/redisEnterprise` + InProgress/Resolved 两个操作，Action Group 指向 A。**不要额外添加 `status=Succeeded`，也不要要求一定有 `properties.cause` 或 `currentHealthStatus`。**

## 6. 无维护影响的消息验证

### 6.1 构造合成负载

从任一被监控订阅复制一个 AMR 的资源 ID，只用来构造消息，不会修改该 Redis：

```bash
export TEST_AMR_RESOURCE_ID="/subscriptions/<monitored-subscription-id>/resourceGroups/<amr-resource-group>/providers/Microsoft.Cache/redisEnterprise/<amr-name>"
```

```bash
python - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

rid = os.environ['TEST_AMR_RESOURCE_ID']
parts = rid.split('/')
if (len(parts) != 9 or parts[1].lower() != 'subscriptions' or parts[3].lower() != 'resourcegroups'
        or parts[5].lower() != 'providers' or parts[6].lower() != 'microsoft.cache'
        or parts[7].lower() != 'redisenterprise' or '<' in rid):
    raise SystemExit('请输入被监控订阅内 AMR 的完整资源 ID')
for phase, operation, status, description in (
    ('start', 'InProgress', 'Started', 'Planned maintenance has started. SYNTHETIC TEST ONLY.'),
    ('end', 'Resolved', 'Succeeded', 'Planned maintenance has completed. SYNTHETIC TEST ONLY.'),
):
    payload = {
        'schemaId': 'Microsoft.Insights/activityLogs',
        'data': {
            'status': 'Activated',
            'context': {'activityLog': {
                'resourceId': rid,
                'eventSource': 'ResourceHealth',
                'operationName': f'Microsoft.Resourcehealth/healthevent/{operation}/action',
                'status': status,
                'eventTimestamp': datetime.now(timezone.utc).isoformat(),
                'eventDataId': str(uuid4()),
                'eventDescription': description,
                'properties': None,
            }},
            'properties': {'testMode': 'history-replay'},
        },
    }
    Path(f'customer-amr-{phase}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print('已生成两份 SYNTHETIC TEST 负载；没有修改 AMR')
PY
```

`history-replay` 标记会让卡片标题带 `[TEST 历史回放]`，正文也写明 `SYNTHETIC TEST ONLY`。

### 6.2 取得 callback 并发送

callback URL 含访问签名，按凭据处理：只放在当前 shell 变量里，不显示、不落盘。

```bash
CALLBACK_URL=$(az rest --subscription "$SUB_A" --method post --url "https://management.azure.com/subscriptions/$SUB_A/resourceGroups/rg-amr-alerts/providers/Microsoft.Logic/workflows/logic-amr-maintenance-feishu/triggers/Receive_alert/listCallbackUrl?api-version=2016-06-01" --query value --output tsv --only-show-errors)
```

以下请求会向飞书群发送真实的 TEST 卡片，不修改 Redis：

```bash
curl --fail-with-body --silent --show-error --output /dev/null --write-out 'HTTP %{http_code}\n' --request POST --header 'Content-Type: application/json' --data-binary @customer-amr-start.json "$CALLBACK_URL"
```

```bash
curl --fail-with-body --silent --show-error --output /dev/null --write-out 'HTTP %{http_code}\n' --request POST --header 'Content-Type: application/json' --data-binary @customer-amr-end.json "$CALLBACK_URL"
```

```bash
unset CALLBACK_URL
```

HTTP 202 只表示工作流收到请求，还需要确认：

1. Logic App 运行历史中两次运行都成功。
2. `Post_to_Feishu` 和 `Delivery_accepted` 动作成功，而不是 Skipped。
3. 飞书群收到一张橙色“维护开始”和一张绿色“维护结束”的 TEST 卡片，订阅、实例、时间和按钮链接正确。

换成其他订阅的 AMR 资源 ID 重复本节，可以确认每个订阅都在允许清单里。直接回放只验证工作流，不验证告警规则的自动触发。

## 7. 上线验收与真实维护验证

### 部署验收

- 所有订阅租户一致。
- 一套中央通知资源，每个选中的订阅一条规则，都部署成功。
- 每条规则的 scope、条件和 Action Group ID 正确。
- 每个订阅的合成负载都能发到正确的飞书群。
- 没有密码、token、callback 或 webhook 写入交付文件。

### 自然维护验收

等自然维护发生后逐层核查：

1. AMR 活动日志中出现真实的 InProgress／Resolved 事件，记录 EventDataId。
2. 对应订阅的告警产生 Fired 实例。
3. 告警历史显示 A 的 Action Group 被执行。
4. Logic App 正常处理同一事件。
5. 飞书收到对应实例的开始／结束卡片。

新建规则不会补发过去的维护日志。不要用重启、扩缩容、故障转移或修改维护计划来强行测试。

## 8. 日常维护与扩展

- **新增订阅**：在向导中重新部署并多选一个订阅，或在 `main.parameters.local.json` 的 `subscriptions` 中追加后重新执行 4.3。同一份部署会同时更新允许清单和新订阅的规则；已有订阅保持不变。
- **只是新增 AMR 实例**：实例所在订阅已在监控范围内时，不需要任何操作。
- **修改资源组或名称**：改名不等于原地重命名，会创建新资源；旧规则和旧资源需要手动退役。
- **轮换 webhook**：用新 webhook 重新部署（参数不变），再做一次合成消息测试。
- **callback 签名泄露**：按 Logic App 文档轮换访问密钥，然后重新部署，以更新 Action Group 里的 callback。
- 查询 Action Group 时只输出接收器名称、资源 ID 和启用状态，不输出整个对象。
- 监控 Logic App 的失败运行：HTTP 200 不足以证明飞书发送成功，工作流还要求飞书业务码为 0，限流时会重试，最终仍未发出则标为失败。
- **自检告警**：部署时填写自检告警邮箱（向导第 2 步，或 CLI 参数 `selfMonitorEmails`，例如 `--parameters selfMonitorEmails='["ops@example.com"]'`），会在同一资源组另建只发邮件的 Action Group `ag-amr-selfmonitor`，以及指标告警 `<Logic App 名>-runs-failed`：Logic App 的 RunsFailed 在 15 分钟内大于 0 就发邮件，恢复后自动解除。它不经过飞书，所以飞书机器人失效时也能收到。首次添加邮箱时，Azure 会给该邮箱发一封“已加入 Action Group”的通知。留空则不创建；以后要关闭，重新部署时清空这个参数不会删除已建资源，需要手动删除这两个资源。
- Consumption Logic App 按执行次数计费，量很小，可以按区域单价估算。

## 9. 停用与排障

优先只禁用本方案的规则，保留 Action Group 和 Logic App 的配置和历史。下面的函数只 PATCH `enabled=false`，不改类别和操作条件：

```bash
disable_rule() {
    az rest --subscription "$1" --method patch --url "https://management.azure.com/subscriptions/$1/resourceGroups/rg-amr-alerts/providers/Microsoft.Insights/activityLogAlerts/ala-amr-health-events?api-version=2020-10-01" --body '{"properties":{"enabled":false}}' --query properties.enabled --output json
}
```

| 现象 | 检查点 |
|---|---|
| 某个订阅部署失败 | 部署人对该订阅是否有创建资源组和告警规则的权限；`Microsoft.Insights` 是否已注册。 |
| Azure 已产生健康事件但没有告警 | 核查规则 scope、类别、资源类型、操作名、enabled，不要额外加 status 或健康属性筛选。 |
| A 能通知，其他订阅不能 | 核查该订阅规则的 Action Group ID，以及部署时是否选中了该订阅（允许清单）。 |
| Workflow Succeeded 但群里没有卡片 | 检查 `Post_to_Feishu` 是否被过滤为 Skipped；检查资源路径、类型和订阅清单。 |
| 卡片显示“维护类型未确认” | 事件原文缺失或不足，不是发送失败；在活动日志里确认原因。 |
| 结束告警仍是 Fired | 活动日志告警是无状态的，结束事件本身也会产生一个 Fired，属于正常。 |
| 飞书返回非零业务码 | 排查机器人地址、群状态、关键词或签名设置。 |

## 10. 官方参考

- [AMR 维护开始会产生 healthevent](https://learn.microsoft.com/en-us/azure/redis/failover#does-maintenance-history-appear-in-the-azure-portal)
- [Activity Log Alert ARM 资源定义](https://learn.microsoft.com/en-us/azure/templates/microsoft.insights/2020-10-01/activitylogalerts)
- [原生 Activity Log 告警负载](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/activity-log-alerts-webhook)
- [通用告警格式（Common Alert Schema）](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-common-schema)
- [Deploy to Azure 按钮](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-to-azure-button)
- [CreateUiDefinition](https://learn.microsoft.com/en-us/azure/azure-resource-manager/managed-applications/create-uidefinition-overview)
- [Logic App 访问密钥轮换 API](https://learn.microsoft.com/en-us/rest/api/logic/workflows/regenerate-access-key?view=rest-logic-2016-06-01)

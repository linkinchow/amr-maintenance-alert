# AMR 飞书维护告警：部署和运维

## 1. 方案与限制

```text
订阅 A 全订阅 AMR ResourceHealth → 订阅 A/rg-amr-alerts/ala-amr-health-events ─┐
订阅 B 全订阅 AMR ResourceHealth → 订阅 B/rg-amr-alerts/同名规则 ──────────────┤
                                                                      ↓
                                           订阅 A/rg-amr-alerts/ag-amr-maintenance-feishu
                                                                      ↓
                                           logic-amr-maintenance-feishu → 新飞书机器人
```

2026-09-20 实测：单规则多订阅在 `2020-10-01`、`2026-01-01` API 均返回 ScopeIsInvalid；同样条件单订阅成功。因此每个受监控订阅各部署一条规则；订阅清单在 `config.local.json` 中维护。

Rule 条件：
- `category = ResourceHealth`
- `resourceType = Microsoft.Cache/redisEnterprise`
- `operationName` 为 `Microsoft.Resourcehealth/healthevent/InProgress/action` 或 `Microsoft.Resourcehealth/healthevent/Resolved/action`

同一类别下 operationName 的 anyOf 已被 Azure 接受；不加 `status=Succeeded`，不要求 `properties.cause/currentHealthStatus`。源日志中这些属性可能不存在。

`redisEnterprise` 资源类型也包含旧 Redis Enterprise。如将来同订阅混用旧产品，当前规则也可能匹配其同类事件。当前盘点均是 AMR kind v2。

## 2. 文件及执行位置

所有命令从仓库根目录运行。

| 文件 | 说明 |
|---|---|
| `main.bicep` | 订阅级入口：中心资源组 + `modules/notifications.bicep`（Logic App、Action Group），对 `subscriptions` 中每个订阅建资源组和 `modules/subscription-alert.bicep` |
| `modules/workflow.json` | Logic App 定义，由 `scripts/build_templates.py` 生成，不要手改 |
| `azuredeploy.json` | `az bicep build -f main.bicep --outfile azuredeploy.json` 生成，Deploy to Azure 按钮使用 |
| `ui/createUiDefinition.json` | 门户部署向导（飞书 webhook、监控订阅多选） |

修改工作流逻辑或卡片：先改生成器，再依次生成 workflow.json 和 azuredeploy.json，最后跑检查：

```bash
python scripts/build_templates.py
```

```bash
az bicep build -f main.bicep --outfile azuredeploy.json
```

```bash
python -m unittest discover -s tests -v
```

GitHub Actions（`.github/workflows/validate.yml`）每次推送都会用同一个 Bicep 版本（0.44.1）重新构建，用 `scripts/ci_check.py` 检查 azuredeploy.json 和 workflow.json 是否已重新生成，并运行单元测试。

## 3. 身份与预检

- 当前 Azure CLI 登录应能在部署订阅和每个被监控订阅里创建资源组、Logic App、Action Group 和活动日志告警规则。
- 中央通知资源与被监控订阅在同一个租户。
- 本方案不需要托管身份或角色分配，不保存任何用户 token。
- 同名资源会被 ARM 覆盖。部署前一定要跑 what-if，确认不会修改无关的工作流、Action Group 或规则。

先按 README 准备 `config.local.json`（不进 git），再生成参数文件 `main.parameters.local.json`（location 和 subscriptions，同样不进 git）：

```bash
python scripts/write_parameters.py
```

```bash
HUB_SUBSCRIPTION_ID=$(python -c "import json; print(json.load(open('config.local.json', encoding='utf-8'))['hubSubscriptionId'])")
```

```bash
az account show --subscription "$HUB_SUBSCRIPTION_ID" --query '{name:name,id:id,tenant:tenantId}' --output json
```

`Microsoft.Logic` 和 `Microsoft.Insights` 的注册状态可以只读查询；namespace 大小写不同不代表未注册。

```bash
az provider show --subscription "$HUB_SUBSCRIPTION_ID" --namespace Microsoft.Logic --query registrationState --output tsv
```

## 4. 部署

新建专用飞书机器人，不复用历史机器人。webhook 是凭据，不在仓库、文档或命令日志中保存。

```bash
read -rsp "AMR Feishu webhook: " FEISHU_WEBHOOK_URL
```

隐藏输入可以避免把秘密写进 shell history，但展开后的进程参数仍可能被本机高权限进程读到。不要开启 `set -x` 或 `--debug`。

```bash
az deployment sub validate --subscription "$HUB_SUBSCRIPTION_ID" --location australiaeast --name amr-maintenance-alerts --template-file azuredeploy.json --parameters @main.parameters.local.json --parameters feishuWebhookUrl="$FEISHU_WEBHOOK_URL" --query properties.provisioningState --output tsv
```

```bash
az deployment sub what-if --subscription "$HUB_SUBSCRIPTION_ID" --location australiaeast --name amr-maintenance-alerts --template-file azuredeploy.json --parameters @main.parameters.local.json --parameters feishuWebhookUrl="$FEISHU_WEBHOOK_URL" --result-format ResourceIdOnly
```

```bash
az deployment sub create --subscription "$HUB_SUBSCRIPTION_ID" --location australiaeast --name amr-maintenance-alerts --template-file azuredeploy.json --parameters @main.parameters.local.json --parameters feishuWebhookUrl="$FEISHU_WEBHOOK_URL" --query '{state:properties.provisioningState,outputs:properties.outputs}' --output json
```

```bash
unset FEISHU_WEBHOOK_URL
```

- 一次部署在每个订阅的同名资源组里新建或更新 `ala-amr-health-events`，并把订阅清单写进 Logic App 的允许清单（`subscriptionNames`）。新增订阅时，加到 `config.local.json` 里，重新生成参数文件后再部署一次即可。
- 模板只输出资源 ID，不输出 callback 或 webhook。HTTP 动作开启了 secure inputs/outputs。HTTP 成功后还要检查飞书 `code` 或 `StatusCode` 为 0。
- 飞书限流（业务码 11232 或 HTTP 429）时，`Send_with_retry` 循环等待后重发同一张卡片：第 n 次失败后等 15n 到 15n+15 秒，最多 `feishuMaxAttempts` 次（默认 8，约 10 分钟）。其他非零业务码不重试。最终没发出去时 `Delivery_failed` 把运行标为失败，错误信息里有尝试次数；成功时 `Delivery_accepted` 的输出里也有尝试次数。
- 默认资源名与 2026-09 首次部署时一致（`rg-amr-alerts`、`logic-amr-maintenance-feishu`、`ag-amr-maintenance-feishu`、`ala-amr-health-events`）。现有环境可以用本模板原地升级，升级前先跑 what-if 确认。

## 5. 测试实例

需要验证模板或卡片又不想影响正式通知时，部署一套独立的测试实例：

- 资源组用 `rg-amr-alerts-test`，资源名带 `-test` 后缀；
- `ruleEnabled=false`，避免真实事件发到测试群；
- 参数放在 `test/test.parameters.local.json`，测试群 webhook 放在 `test/webhook.local.json`（格式见 `test/webhook.example.json`）。

```bash
az deployment sub create --subscription "$HUB_SUBSCRIPTION_ID" --location australiaeast --name amr-alerts-test --template-file azuredeploy.json --parameters @test/test.parameters.local.json --parameters @test/webhook.local.json --query properties.provisioningState --output tsv
```

回放和 canary 用 `--resource-group rg-amr-alerts-test` 以及 `--logic-app` / `--action-group` 指向测试实例（见第 7 节）。测试结束后先核对标签（`temporary=true`），再删除两个订阅里的 `rg-amr-alerts-test`。

## 6. 飞书消息处理与数据边界

默认接收原生 `Microsoft.Insights/activityLogs` schema；兼容 Common Alert Schema。

读取顺序：事件 `eventDescription`、`description`、`properties.details`、`properties.title`。绝不以 `data.essentials.description` 作为维护证据，因为那是规则描述。

- 明确包含 Planned maintenance：橙色 `警告｜AMR 维护开始｜<实例>` 或绿色 `已恢复｜AMR 维护结束｜<实例>`。
- 描述缺失或不能确认：开始为蓝色 `提示｜AMR 健康事件（维护类型未确认）｜<实例>`，结束为绿色。
- 订阅/资源类型/类别/operation 不匹配：跳过，不发送。
- 特定新建 canary Action Group 的成功写操作：只在 `testMode=canary` 时发 TEST 通知。

单条规则也可能匹配非维护健康事件；文字分类不是完整语义识别，不将其静默丢弃，避免漏报。未来若实际维护负载不带描述，应先检查真实 schema，再决定是否增加按事件 ID 查询的最小权限服务身份；当前部署不依赖额外 RBAC。

消息是飞书交互卡片（`msg_type: interactive`），版式与 azure-alert 一致：header 颜色和“级别｜分类｜实例”标题；字段为时间（北京时间）、实例、订阅、订阅 ID、资源组、阶段、事件状态、Event ID；分隔线下是事件原文和“不代表提前预告”的提示；然后是“在 Azure 门户中查看”按钮和来源说明。开始与结束由 operation 决定，不由告警 monitorCondition 决定。

## 7. 测试，不操作 Redis

生成样例：

```bash
python scripts/build_samples.py
```

历史开始回放：

```bash
python scripts/replay.py --file maintenance-start.json --send-test [--resource-group rg-amr-alerts-test --logic-app logic-amr-maintenance-feishu-test]
```

历史结束回放：

```bash
python scripts/replay.py --file maintenance-end.json --send-test
```

其他样例：`common-schema-end.json`、`missing-description.json`、`empty-event.json`、`out-of-scope.json`。后两项必须没有 Post_to_Feishu 成功执行。

回放会发真实飞书消息，但标题明确带 TEST，事件时间保留历史时间。它不创建 Azure Monitor Fired 实例，不证明实时维护触发链路已经验证。

### 独立 canary 验证 Action Group 链路

在每个订阅的部署资源组中建立无接收器 Action Group `ag-amr-canary-signal` 及临时规则 `ala-amr-canary`，规则监听该测试资源的成功写操作，关联通知 Action Group。工作流只接受来自部署资源组（参数 `resourceGroupName`）的 canary。指向测试实例时加 `--resource-group rg-amr-alerts-test --action-group ag-amr-maintenance-feishu-test`。

```bash
python scripts/canary.py prepare --apply
```

等待规则传播后：

```bash
python scripts/canary.py fire --apply
```

检查两订阅的 Fired alert/history 和中央 Logic App run，消息必须是 `[TEST 通知链路验证]`。初始创建本身也可能被事件管道捕获，加上平台重复投递，可能有多条 TEST 消息，不代表多次 Redis 维护。

测试后清理（只清理已回读并核验 temporary/scenario 标签的测试资源）：

```bash
python scripts/canary.py cleanup --apply
```

真实 AMR 自然维护发生后再核验正式规则的 Fired 实例和消息。旧日志不会因为新建规则而重放，禁止重启/缩放 AMR 或变更维护计划制造测试。

## 8. 查询与运维

查看正式规则（避免读取包含 callback URL 的完整 Action Group）：

```bash
az monitor activity-log alert show --subscription "$HUB_SUBSCRIPTION_ID" --resource-group rg-amr-alerts --name ala-amr-health-events --query '{enabled:enabled,scope:scopes,condition:condition,actions:actions.actionGroups[].actionGroupId}' --output json
```

查看工作流最近运行，只输出非敏感字段：

```bash
az rest --subscription "$HUB_SUBSCRIPTION_ID" --method get --url "https://management.azure.com/subscriptions/$HUB_SUBSCRIPTION_ID/resourceGroups/rg-amr-alerts/providers/Microsoft.Logic/workflows/logic-amr-maintenance-feishu/runs?api-version=2016-06-01&\$top=10" --query 'value[].{name:name,status:properties.status,time:properties.startTime}' --output json
```

- Workflow Succeeded 不等于发了消息：事件可能被过滤，需检查 Post_to_Feishu 和 Delivery_accepted 动作。
- Feishu 业务码 0 表示平台接受，还需通过群内消息完成用户侧验收。
- Native 告警是无状态的；维护结束不会自动关闭开始告警。
- 此方案无持久去重，可能重复投递。以 EventDataId 核对，不建议通过忽略所有重复时间戳方式去重。
- 每个被监控订阅只保留一条正式规则，测试结束后清理临时规则。
- 如需停用通知，仅对本方案的规则 PATCH `enabled=false`。
- 不使用 `az monitor activity-log alert update --enabled false` 修改复杂条件：此前该 CLI 路径有默认 category 被重写的实测现象，优先使用 REST PATCH 只改 enabled。
- Logic App 是按执行计费的 Consumption 服务，调用次数、重试和过滤步骤均需评估成本。

## 9. 官方参考

- [AMR 维护事件：开始时发出 healthevent](https://learn.microsoft.com/en-us/azure/redis/failover#does-maintenance-history-appear-in-the-azure-portal)
- [Activity Log 告警 ARM 资源定义](https://learn.microsoft.com/en-us/azure/templates/microsoft.insights/2020-10-01/activitylogalerts)
- [Activity Log Webhook 负载格式](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/activity-log-alerts-webhook)
- [通用告警格式（Common Alert Schema）](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-common-schema)

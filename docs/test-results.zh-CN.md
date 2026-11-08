# AMR 维护通知实测报告

日期：2026-09-20。所有操作显式选择订阅，未改动 Redis 实例。

## 一、跨订阅范围对照实验

| API | 单订阅 scope | 订阅 A + 订阅 B 双订阅 scope |
|---|---|---|
| 2020-10-01 | 成功创建并回读；已清理 | ScopeIsInvalid |
| 2026-01-01 | 成功创建并回读；已清理 | ScopeIsInvalid |

错误原文：

```text
The resources in the scope must be in the same subscription as the rule.
```

单订阅对照使用相同的 ResourceHealth、resourceType 和双 operation anyOf 条件。因此这次错误可明确归因于 scope 限制，而不是 category/operation 组合或权限问题。

[完整脱敏请求与响应](scope-probe-results.json)。临时规则均为禁用、无动作状态；成功创建的单订阅规则已删除，失败请求未留下资源。

## 二、最终资源布局

订阅 A（中央订阅）的 `rg-amr-alerts` 中只保留：
- `Microsoft.Insights/activityLogAlerts/ala-amr-health-events`
- `Microsoft.Insights/actionGroups/ag-amr-maintenance-feishu`
- `Microsoft.Logic/workflows/logic-amr-maintenance-feishu`

订阅 B 的 `rg-amr-alerts` 中只保留：
- `Microsoft.Insights/activityLogAlerts/ala-amr-health-events`

### 监控范围

测试环境共 16 个 AMR（订阅 A 11 个、订阅 B 5 个）。两个订阅各一条规则，覆盖该订阅全部当前/未来匹配类型实例。已回读 scope、enabled、condition 和中央 Action Group 关联，全部正确；最终盘点时 AMR 均为 Running。未纳入的订阅未创建资源组或规则，也不在通知允许清单中。

## 三、已完成的验证

### 本地

- AMR 模板/输入/范围/安全/CLI 参数检查。
- ARM JSON 生成与源代码一致性。
- 文档链接、Python 语法及无秘密落盘检查。

### 云端模板

- ARM validate：Succeeded。
- What-If：仅创建本次中央 Action Group 和 Logic App。
- Deployment：Succeeded；Webhook 参数为 SecureString，输出仅资源 ID。
- Logic App：Enabled。
- Action Group：Enabled，只有新 Logic App receiver，无旧接收器或额外邮件。

### 历史事件回放

使用订阅 A 中一个 AMR 实例 2026-09-10 的真实维护事件作为样例（仓库内样例已替换为占位订阅和实例名）：

| 样例 | 验证结果 |
|---|---|
| 开始（原生 schema） | Run Succeeded，飞书 HTTP + 业务返回码检查成功 |
| 结束（原生 schema） | Run Succeeded，飞书 HTTP + 业务返回码检查成功 |
| Common schema 结束 | Run Succeeded，发送动作与业务码检查成功 |
| 缺少描述 | 发送保守分类的 TEST 健康事件，不以规则描述判断维护 |
| 空事件 | Post_to_Feishu=Skipped |
| 允许清单外订阅 | Post_to_Feishu=Skipped |

回放消息保留历史事件时间，并明确带 TEST，不是今天发生了 Redis 维护。成功业务返回码表示飞书接受请求；群内最终收件及视觉格式以用户确认作为最后验收。

### 两个订阅的真实告警通知链路

在新 RG 中用无接收器 Action Group 的成功写入操作作为 canary，两个订阅均观察到：

1. `ala-amr-canary` 的 Fired 实例。
2. Alert history 的 `ActionsTriggered`：`Action group ag-amr-maintenance-feishu executed`。
3. 中央 Logic App 成功运行。
4. `Post_to_Feishu=Succeeded` 且 `Delivery_accepted=Succeeded`。

两个订阅的告警 history、Fired 实例 ID 和 Logic App 运行记录在内部留存，含环境 ID，不放入公开仓库。平台有事件延迟，初始创建也可能触发 canary，并可能重复投递，因此测试消息数量可能多于两条。

临时 `ala-amr-canary` 和 `ag-amr-canary-signal` 均已按标签及资源 ID 回读确认后删除，最终清单没有临时资源。

## 四、真实维护事件验收

2026-11-04 只读核对告警历史和 Logic App 运行记录（未做任何变更）：

| 项目 | 结果 |
|---|---|
| 时间范围 | 2026-10-01 至 2026-11-04 |
| 自然维护事件 | 34 个（InProgress 17、Resolved 17），涉及 2 个订阅的 12 个实例 |
| 链路 | 34 次全部走通 规则 → Action Group → Logic App → 飞书，飞书业务码均为 0，无失败 |
| 分类 | 维护原文都在 `eventDescription`（“Planned maintenance has started / has completed…”），34 次全部识别为维护开始/结束 |
| 延迟（事件时间 → Logic App 开始运行） | 最短 2 分 3 秒，中位数约 5 分 17 秒，最长 7 分 21 秒；飞书发送约 2 秒 |

由此确认：原生 schema 下真实维护负载的映射与历史回放样例一致；“开始”通知可能与实际 failover 同时或更晚到达。

核对注意：`az monitor activity-log list` 默认只返回 50 条，需要加大 `--max-events` 或以 Logic App 运行记录为准，否则会漏查。

## 五、一键部署模板与卡片验证（2026-11-04）

改为订阅级模板（`main.bicep` → `azuredeploy.json`）+ 飞书交互卡片后，部署了一套独立测试实例：资源组 `rg-amr-alerts-test`，资源名带 `-test`，规则 `ruleEnabled=false`，飞书用模拟接收端（返回业务码 0，并记录收到的请求体）。线上 `rg-amr-alerts` 未改动。

| 项目 | 结果 |
|---|---|
| `az deployment sub validate` | Succeeded |
| what-if | 只创建两个订阅的 `rg-amr-alerts-test` 和其中的测试资源，没有修改任何现有资源 |
| 部署 | 一次部署成功，在 2 个订阅各建 1 条规则；回读 scope 为本订阅、Action Group 指向部署订阅；Logic App 的 `subscriptionNames` 与参数一致 |
| 回放：开始 | 橙色 `[TEST 历史回放] 警告｜AMR 维护开始｜<实例>`，字段、原文、按钮链接、来源说明正确 |
| 回放：结束（原生 / Common Schema） | 绿色 `已恢复｜AMR 维护结束｜<实例>` |
| 回放：缺少原文 | 蓝色 `提示｜AMR 健康事件（维护类型未确认）｜<实例>`，正文为兜底说明 |
| 回放：空事件、订阅不在允许清单 | `Post_to_Feishu` = Skipped |
| canary 跨订阅链路 | 两个订阅的临时规则 → 测试 Action Group → 测试 Logic App → 卡片 `[TEST 通知链路验证]`，订阅名正确；canary 临时资源已清理 |
| 真实飞书群 | 换成真实机器人 webhook 重新部署测试实例后，回放开始、结束、Common Schema 结束、缺少原文 4 个样例，飞书业务码均为 0，群内卡片经人工确认显示正常 |

测试结束后，核对标签后删除了两个订阅的 `rg-amr-alerts-test`。

### 发布后实测与飞书限流重试

推送到 GitHub 后，用按钮使用的 raw 模板地址（`--template-uri`）部署测试实例：what-if 只有新建，部署成功，两个订阅各 1 条规则。回放时有 1 张卡片 HTTP 200 但飞书业务码非 0（原因不可见，重发成功），据此参照 azure-alert 加入限流重试，并用模拟接收端验证：

| 模拟场景 | 结果 |
|---|---|
| 不限流 | 第 1 次成功 |
| 限流一次（11232） | 第 2 次成功，耗时 24 秒 |
| 始终限流，`feishuMaxAttempts=3` | 3 次后运行失败，耗时 64 秒，错误信息含尝试次数 |
| 连续限流 8 次（默认上限） | 8 次后运行失败，耗时约 7.5 分钟 |
| 格式错误（9499） | 不重试，第 1 次后运行失败 |


### 门户 Deploy to Azure 实测

从 README 按钮进入门户向导，部署订阅选订阅 A，区域 East US 2，资源组 `rg-amr-alerts-test`，监控订阅勾选订阅 A 和订阅 B。

| 项目 | 结果 |
|---|---|
| 第一次部署 | 校验失败：`InvalidDeploymentLocation`。在各订阅建资源组的嵌套部署是订阅级部署，名称原来只由订阅和资源组名决定；之前在 australiaeast 的测试留下了同名部署记录，换区域就冲突。修复：名称加入 `deployment().location`，并加了单元测试；用旧模板在 East US 2 复现了同样的错误，新模板校验通过 |
| 修复后重新部署 | 成功 |
| 向导三步 | 基本信息、飞书通知、监控订阅（多选）都能正常填写，参数汇总正确 |
| 回读 | 两个订阅都建了资源组；部署订阅有 Logic App、Action Group、规则；另一个订阅只有规则。规则已启用，scope 为本订阅，指向部署订阅的 Action Group；Logic App 的订阅清单和显示名与勾选一致 |
| 发送 | 通过这套部署发出 TEST 卡片，飞书一次返回业务码 0，群内收到 |
| 清理 | 核对资源组名、scenario 标签和资源清单后删除两个订阅的 `rg-amr-alerts-test` |

### 正式环境升级

2026-11-04 用本模板原地升级正式环境（订阅 A、B 的 `rg-amr-alerts`）：what-if 全部为修改，没有新建或删除；规则只变更 `managedBy` 标签，条件和 scope 不变；Logic App 换成卡片 + 限流重试的定义；Action Group 刷新 callback。部署成功后回读：两条规则已启用、条件与升级前一致、指向原 Action Group；Logic App 订阅清单正确；Action Group 只有这个 Logic App 接收器、原生 schema、无邮件接收器。经正式 Logic App 回放一张 TEST 卡片，飞书一次返回业务码 0。

### 自检告警（Logic App 失败运行 → 邮件）

测试实例部署时传入 `selfMonitorEmails`，飞书换成始终返回格式错误（9499）的模拟接收端：

| 项目 | 结果 |
|---|---|
| 部署 | 另建只发邮件的 Action Group（1 个邮件接收人，没有 Logic App / webhook 接收人）和指标告警 `<Logic App 名>-runs-failed` |
| 制造失败 | 回放 1 张卡片，飞书拒收，运行失败 |
| 告警 | 约 7 分钟后告警 Fired，告警历史显示邮件 Action Group 已执行 |
| 邮件 | 收件人收到 “Fired:Sev2 Azure Monitor Alert …-runs-failed” 邮件，以及加入 Action Group 的通知邮件 |
| 清理 | 核对标签和资源清单后删除测试资源组 |

### AMR 健康事件类型（2026-11-09 只读核对）

有 AMR 的 3 个订阅，近 90 天 `Microsoft.Cache` 的 Resource Health 活动日志共 78 条（21 个实例，含已删除）：InProgress / Started 39 条、Resolved / Succeeded 39 条，原文只有 “Planned maintenance has started / has completed …”，level 均为 Informational，cause、type、title 为空。没有出现 Activated、Updated 或其他原文，所以现有规则只收 InProgress / Resolved 不会漏掉已观察到的事件。不受维护窗口约束的维护（主机 OS、网络、紧急安全补丁）是否产生事件，事件里没有可区分的字段，文档也没有说明，需要向产品组确认。

## 六、已知边界

- 是维护开始/结束通知，不是提前预告；事件周期不等于业务中断时长。加上 2–7 分钟投递延迟，“开始”消息可能晚于 failover。
- 开始与结束是独立事件告警，两个 monitorCondition 都可能是 Fired；不能将 Resolved operation 当作开始告警自动恢复。
- 未做持久化去重，也不合并消息；同一批实例同时维护会产生多条通知，按 EventDataId 辨认重复投递。
- 单条规则不能跨订阅，每个受监控订阅需单独部署规则。
- 无原文时仍通知健康阶段并提示维护未确认，不保证每条通知标题都自动判为 Planned maintenance。
- 没有新增运行时身份权限，没有修改已有其他告警或其他租户资源。

#!/usr/bin/env python3
"""Generate the Logic App workflow definition (modules/workflow.json) loaded by modules/notifications.bicep."""
import json
from pathlib import Path
from azure_helpers import BASE


def expr(value):
    return "@" + value


def compose(value, after=None):
    return {"type": "Compose", "inputs": expr(value), "runAfter": {after: ["Succeeded"]} if after else {}}


def build_workflow():
    event = "outputs('Event')"
    target = "outputs('Target')"
    meta = "outputs('Metadata')"
    props = f"{event}?['properties']"
    operation = f"toLower(coalesce({event}?['operationName'], ''))"
    description = (
        f"string(coalesce({event}?['eventDescription'], {event}?['description'], "
        f"{props}?['details'], {props}?['title'], ''))"
    )
    actions = {
        "Event": compose("coalesce(triggerBody()?['data']?['context']?['activityLog'], triggerBody()?['data']?['alertContext'], json('{}'))"),
        "Metadata": compose("coalesce(triggerBody()?['data']?['properties'], triggerBody()?['data']?['customProperties'], json('{}'))", "Event"),
        "Target": compose(
            f"toLower(coalesce({event}?['resourceId'], first(if(empty(triggerBody()?['data']?['essentials']?['alertTargetIDs']), "
            "createArray(''), triggerBody()?['data']?['essentials']?['alertTargetIDs']))))", "Metadata"),
        "Description": compose(description, "Target"),
    }
    # Validate the resource path before using fixed subscription/resource-group segments.
    valid_path = f"and(startsWith({target}, '/subscriptions/'), equals(length(split({target}, '/')), 9))"
    test = f"equals({meta}?['testMode'], 'history-replay')"
    base_match = (
        f"and(contains(parameters('subscriptionNames'), split({target}, '/')[2]), "
        f"equals(split({target}, '/')[3], 'resourcegroups'), equals(split({target}, '/')[5], 'providers'))"
    )
    amr_match = (
        f"and({base_match}, equals(split({target}, '/')[6], 'microsoft.cache'), "
        f"equals(split({target}, '/')[7], 'redisenterprise'), "
        f"equals(toLower(coalesce({event}?['eventSource'], '')), 'resourcehealth'), "
        f"or(equals({operation}, 'microsoft.resourcehealth/healthevent/inprogress/action'), "
        f"equals({operation}, 'microsoft.resourcehealth/healthevent/resolved/action')))"
    )
    canary_match = (
        f"and({base_match}, equals(split({target}, '/')[4], toLower(parameters('resourceGroupName'))), "
        f"equals(split({target}, '/')[6], 'microsoft.insights'), "
        f"equals(split({target}, '/')[7], 'actiongroups'), "
        f"equals(split({target}, '/')[8], 'ag-amr-canary-signal'), "
        f"equals({meta}?['testMode'], 'canary'), "
        f"equals(toLower(coalesce({event}?['eventSource'], '')), 'administrative'), "
        f"equals({operation}, 'microsoft.insights/actiongroups/write'), "
        f"equals(toLower(coalesce({event}?['status'], '')), 'succeeded'))"
    )
    is_canary = "outputs('Is_canary')"
    is_start = f"equals({operation}, 'microsoft.resourcehealth/healthevent/inprogress/action')"
    explicit_maintenance = "contains(toLower(outputs('Description')), 'planned maintenance')"
    instance = f"last(split({target}, '/'))"
    # Card layout follows azure-alert: header colour/level, "**key**：value" fields, hr, original text, portal button, note.
    color = f"if({is_canary}, 'blue', if(not({is_start}), 'green', if({explicit_maintenance}, 'orange', 'blue')))"
    level = f"if({is_canary}, '提示', if(not({is_start}), '已恢复', if({explicit_maintenance}, '警告', '提示')))"
    category = (
        f"if({is_canary}, 'AMR 通知链路', if({explicit_maintenance}, "
        f"if({is_start}, 'AMR 维护开始', 'AMR 维护结束'), 'AMR 健康事件（维护类型未确认）'))"
    )
    title = (
        f"concat(if({is_canary}, '[TEST 通知链路验证] ', if({test}, '[TEST 历史回放] ', '')), "
        f"{level}, '｜', {category}, '｜', {instance})"
    )
    timestamp = f"{event}?['eventTimestamp']"
    fields = [
        ("时间（北京时间）", f"if(empty({timestamp}), '未提供', convertTimeZone({timestamp}, 'UTC', 'China Standard Time', 'yyyy-MM-dd HH:mm:ss'))"),
        ("实例", instance),
        ("订阅", f"coalesce(parameters('subscriptionNames')?[split({target}, '/')[2]], '未提供')"),
        ("订阅 ID", f"split({target}, '/')[2]"),
        ("资源组", f"split({target}, '/')[4]"),
        ("阶段", f"if({is_canary}, 'TEST canary（不是维护）', if({is_start}, '开始/进行中', '结束'))"),
        ("事件状态", f"coalesce({event}?['status'], '未提供')"),
        ("Event ID", f"coalesce({event}?['eventDataId'], '未提供')"),
    ]
    field_text = "concat(" + ", '\n', ".join(f"'**{k}**：', {v}" for k, v in fields) + ")"
    summary = (
        "concat(if(empty(outputs('Description')), '负载未提供原始维护说明，请查看 Activity Log；不以规则描述代替。', "
        "outputs('Description')), '\n\n本通知不代表提前预告；事件跨度不等于业务中断时长。')"
    )
    card = {"msg_type": "interactive", "card": {
        "config": {"wide_screen_mode": True},
        "header": {"template": expr(color), "title": {"tag": "plain_text", "content": expr(title)}},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": expr(field_text)}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": expr(summary)}},
            {"tag": "action", "actions": [{"tag": "button", "type": "primary",
                                           "text": {"tag": "plain_text", "content": "在 Azure 门户中查看"},
                                           "url": expr(f"concat('https://portal.azure.com/#resource', {target})")}]},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "Azure 告警 · 来源 AMR 维护 · ActivityLog"}]},
        ]}}
    send_actions = {
        "Is_canary": compose(canary_match),
        "Post_to_Feishu": {
            "type": "Http", "runAfter": {"Is_canary": ["Succeeded"]},
            "inputs": {"method": "POST", "uri": "@parameters('feishuWebhookUrl')",
                       "headers": {"Content-Type": "application/json"},
                       "retryPolicy": {"type": "exponential", "count": 3, "interval": "PT10S"},
                       "body": card},
            "runtimeConfiguration": {"secureData": {"properties": ["inputs", "outputs"]}},
        },
        "Verify_Feishu_result": {
            "type": "If", "runAfter": {"Post_to_Feishu": ["Succeeded"]},
            "expression": expr("equals(string(coalesce(body('Post_to_Feishu')?['code'], body('Post_to_Feishu')?['StatusCode'], -1)), '0')"),
            "actions": {"Delivery_accepted": compose("'Feishu returned business code 0; verify group delivery for acceptance.'")},
            "else": {"actions": {"Delivery_failed": {"type": "Terminate", "runAfter": {},
                "inputs": {"runStatus": "Failed", "runError": {"code": "FeishuRejected", "message": "Feishu did not return a successful business code."}}}}},
        },
    }
    actions["Validate_resource_path"] = {
        "type": "If", "runAfter": {"Description": ["Succeeded"]}, "expression": expr(valid_path),
        "actions": {"Validate_event": {
            "type": "If", "runAfter": {},
            "expression": expr(f"and(or(equals(triggerBody()?['schemaId'], 'Microsoft.Insights/activityLogs'), equals(triggerBody()?['schemaId'], 'azureMonitorCommonAlertSchema')), or({amr_match}, {canary_match}))"),
            "actions": send_actions, "else": {"actions": {}},
        }},
        "else": {"actions": {}},
    }
    return {
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "contentVersion": "1.0.0.0",
        # subscriptionNames doubles as the allow-list and display names; resourceGroupName scopes the canary. Values come from main.bicep.
        "parameters": {"feishuWebhookUrl": {"type": "SecureString"}, "subscriptionNames": {"type": "Object"},
                       "resourceGroupName": {"type": "String"}},
        "triggers": {"Receive_alert": {"type": "Request", "kind": "Http",
            "inputs": {"method": "POST", "schema": {"type": "object", "required": ["schemaId", "data"],
                "properties": {"schemaId": {"type": "string"}, "data": {"type": "object"}}}}}},
        "actions": actions, "outputs": {},
    }


def render(definition):
    return json.dumps(definition, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    (BASE / "modules" / "workflow.json").write_text(render(build_workflow()), encoding="utf-8")
    print("Generated modules/workflow.json; rebuild azuredeploy.json with: az bicep build -f main.bicep --outfile azuredeploy.json")

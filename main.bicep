// AMR maintenance alerts entry point (Deploy to Azure: azuredeploy.json is built from this file).
//   az deployment sub create -l <region> -f main.bicep -p @main.parameters.local.json -p feishuWebhookUrl=...
//   - Logic App + Action Group go into resourceGroupName in the deployment subscription
//   - every subscription in `subscriptions` gets the same resource group and one activity log alert rule
targetScope = 'subscription'

@description('Region of the resource groups and the Logic App.')
param location string

@description('Resource group created in the deployment subscription and in every monitored subscription.')
param resourceGroupName string = 'rg-amr-alerts'

param logicAppName string = 'logic-amr-maintenance-feishu'
param actionGroupName string = 'ag-amr-maintenance-feishu'
param ruleName string = 'ala-amr-health-events'

@secure()
@description('Feishu / Lark custom bot webhook URL.')
param feishuWebhookUrl string

@description('Monitored subscriptions: [{ id, name }]. name is shown in the card; the list is also the workflow allow-list.')
param subscriptions array = [
  {
    id: subscription().subscriptionId
    name: subscription().displayName
  }
]

@description('Feishu rate limiting (code 11232 / HTTP 429): attempts per message before the run fails; the wait grows with each attempt (8 attempts take about 10 minutes).')
@minValue(1)
@maxValue(15)
param feishuMaxAttempts int = 8

@description('Create the alert rules enabled. Test deployments set false so real events do not reach a test group.')
param ruleEnabled bool = true

param tags object = {
  scenario: 'amr-maintenance-alerts'
  managedBy: 'amr-maintenance-alert'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module notifications 'modules/notifications.bicep' = {
  name: 'amr-notifications'
  scope: rg
  params: {
    location: location
    logicAppName: logicAppName
    actionGroupName: actionGroupName
    tags: tags
    feishuWebhookUrl: feishuWebhookUrl
    subscriptionNames: toObject(subscriptions, s => toLower(s.id), s => s.name)
    feishuMaxAttempts: feishuMaxAttempts
  }
}

module ruleRg 'modules/resource-group.bicep' = [for sub in subscriptions: {
  name: 'amr-rg-${uniqueString(sub.id, resourceGroupName)}'
  scope: subscription(sub.id)
  params: {
    name: resourceGroupName
    location: location
    tags: tags
  }
}]

module rule 'modules/subscription-alert.bicep' = [for (sub, i) in subscriptions: {
  name: 'amr-rule-${uniqueString(sub.id, resourceGroupName)}'
  scope: resourceGroup(sub.id, resourceGroupName)
  dependsOn: [
    ruleRg[i]
  ]
  params: {
    ruleName: ruleName
    actionGroupId: notifications.outputs.actionGroupId
    enabled: ruleEnabled
    tags: tags
  }
}]

output resourceGroupName string = rg.name
output actionGroupId string = notifications.outputs.actionGroupId
output logicAppId string = notifications.outputs.logicAppId
output ruleIds array = [for (sub, i) in subscriptions: rule[i].outputs.ruleId]

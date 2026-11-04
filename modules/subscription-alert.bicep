// One activity log alert per monitored subscription: AMR Resource Health InProgress / Resolved events.
// A rule cannot span subscriptions (ScopeIsInvalid), so main.bicep deploys this once per subscription.
targetScope = 'resourceGroup'

param ruleName string
param actionGroupId string
param enabled bool = true
param tags object = {}

resource rule 'Microsoft.Insights/activityLogAlerts@2020-10-01' = {
  name: ruleName
  location: 'global'
  tags: tags
  properties: {
    enabled: enabled
    scopes: [
      subscription().id
    ]
    description: 'AMR ResourceHealth InProgress/Resolved events; not advance maintenance notice.'
    condition: {
      allOf: [
        {
          field: 'category'
          equals: 'ResourceHealth'
        }
        {
          field: 'resourceType'
          equals: 'Microsoft.Cache/redisEnterprise'
        }
        {
          anyOf: [
            {
              field: 'operationName'
              equals: 'Microsoft.Resourcehealth/healthevent/InProgress/action'
            }
            {
              field: 'operationName'
              equals: 'Microsoft.Resourcehealth/healthevent/Resolved/action'
            }
          ]
        }
      ]
    }
    actions: {
      actionGroups: [
        {
          actionGroupId: actionGroupId
        }
      ]
    }
  }
}

output ruleId string = rule.id

// Self-monitoring: e-mail when the notification Logic App has failed runs (e.g. Feishu still rejecting after all retries).
// Uses its own Action Group with e-mail receivers only, so it does not depend on Feishu or on the AMR workflow,
// which ignores anything that is not an AMR health event.
targetScope = 'resourceGroup'

param workflowId string
param workflowName string
param actionGroupName string
param emails array
param tags object = {}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: actionGroupName
  location: 'global'
  tags: tags
  properties: {
    enabled: true
    groupShortName: 'AMRSelfMon'
    emailReceivers: [for (email, i) in emails: {
      name: 'email-${i}'
      emailAddress: email
      useCommonAlertSchema: true
    }]
  }
}

resource alert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${workflowName}-runs-failed'
  location: 'global'
  tags: tags
  properties: {
    description: 'AMR maintenance alerts self-monitoring: ${workflowName} has failed runs (Feishu notification not delivered).'
    severity: 2
    enabled: true
    scopes: [
      workflowId
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    autoMitigate: true
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'runsfailed'
          metricNamespace: 'Microsoft.Logic/workflows'
          metricName: 'RunsFailed'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Total'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

output alertId string = alert.id

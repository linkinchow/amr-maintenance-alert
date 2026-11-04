import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from azure_helpers import rule_body, az, AzError
from build_templates import build_workflow
from build_samples import fixtures

HUB = '11111111-1111-1111-1111-111111111111'
SPOKE = '22222222-2222-2222-2222-222222222222'
GUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def nested(template, deployment_prefix):
    """Inner template of the main.bicep module whose deployment name contains deployment_prefix."""
    for resource in template['resources']:
        if resource['type'] == 'Microsoft.Resources/deployments' and deployment_prefix in resource['name']:
            return resource['properties']['template']
    raise AssertionError(deployment_prefix)


class AmrTemplateTests(unittest.TestCase):
    def setUp(self):
        self.workflow = build_workflow()
        self.actions = self.workflow['actions']
        self.validate = self.actions['Validate_resource_path']['actions']['Validate_event']
        self.send = self.validate['actions']
        self.deploy = load('azuredeploy.json')
        self.notifications = nested(self.deploy, 'amr-notifications')
        self.rule = nested(self.deploy, 'amr-rule')['resources'][0]
        self.card = self.send['Post_to_Feishu']['inputs']['body']

    def test_generated_workflow_and_azuredeploy_are_current(self):
        self.assertEqual(load('modules/workflow.json'), self.workflow)
        # azuredeploy.json must be rebuilt (az bicep build) after the workflow changes.
        reference = self.notifications['resources'][0]['properties']['definition']
        variable = re.fullmatch(r"\[variables\('(.+)'\)\]", reference).group(1)
        self.assertEqual(self.notifications['variables'][variable], self.workflow)

    def test_template_has_no_environment_identifiers(self):
        self.assertIsNone(GUID.search(json.dumps(self.deploy)))
        params = self.deploy['parameters']
        self.assertEqual(params['logicAppName']['defaultValue'], 'logic-amr-maintenance-feishu')
        self.assertEqual(params['resourceGroupName']['defaultValue'], 'rg-amr-alerts')
        self.assertIn('subscription()', json.dumps(params['subscriptions']['defaultValue']))

    def test_ui_outputs_cover_required_parameters(self):
        outputs = load('ui/createUiDefinition.json')['parameters']['outputs']
        params = self.deploy['parameters']
        for name in outputs:
            self.assertIn(name, params)
        for name, spec in params.items():
            if 'defaultValue' not in spec:
                self.assertIn(name, outputs)
        self.assertIn("contains(steps('scope').subscriptionIds", outputs['subscriptions'])

    def test_repository_has_only_placeholder_guids(self):
        # Public repo: real IDs belong in git-ignored *.local.json only. Screenshots are masked by hand and reviewed visually.
        for path in ROOT.rglob('*'):
            if (not path.is_file() or '.git' in path.parts or '__pycache__' in path.parts
                    or path.name.endswith('.local.json') or path.suffix.lower() == '.png'):
                continue
            for guid in GUID.findall(path.read_text(encoding='utf-8')):
                self.assertLessEqual(len(set(guid.lower().replace('-', '')) - {'0'}), 1, f'{path.relative_to(ROOT)}: {guid}')

    def test_secrets_not_in_outputs_or_defaults(self):
        self.assertEqual(self.deploy['parameters']['feishuWebhookUrl']['type'], 'securestring')
        self.assertNotIn('defaultValue', self.deploy['parameters']['feishuWebhookUrl'])
        self.assertEqual(self.notifications['parameters']['feishuWebhookUrl']['type'], 'securestring')
        self.assertEqual(self.workflow['parameters']['feishuWebhookUrl']['type'], 'SecureString')
        for outputs in (self.deploy['outputs'], self.notifications['outputs']):
            self.assertNotIn('callback', json.dumps(outputs).lower())
            self.assertNotIn('feishuWebhookUrl', json.dumps(outputs))
        self.assertEqual(self.send['Post_to_Feishu']['runtimeConfiguration']['secureData']['properties'], ['inputs','outputs'])

    def test_both_event_schemas_accepted_and_rule_description_not_used(self):
        value = json.dumps(self.actions)
        self.assertIn("['context']?['activityLog']", value)
        self.assertIn("['alertContext']", value)
        self.assertIn('azureMonitorCommonAlertSchema', self.validate['expression'])
        self.assertNotIn("['essentials']?['description']", value)
        self.assertIn("['eventDescription']", self.actions['Description']['inputs'])

    def test_input_scope_and_resource_filters(self):
        predicate = self.validate['expression']
        for text in ('subscriptionNames', 'microsoft.cache', 'redisenterprise', 'resourcehealth', 'inprogress/action', 'resolved/action'):
            self.assertIn(text, predicate)
        self.assertIn("equals(length(split(outputs('Target'), '/')), 9)", self.actions['Validate_resource_path']['expression'])
        self.assertEqual(self.validate['else']['actions'], {})

    def test_canary_is_tightly_scoped_and_labelled(self):
        predicate = self.validate['expression']
        for text in ("parameters('resourceGroupName')",'ag-amr-canary-signal',"['testMode'], 'canary'",'microsoft.insights/actiongroups/write'):
            self.assertIn(text, predicate)
        title = self.card['card']['header']['title']['content']
        self.assertIn('TEST 通知链路验证', title)
        self.assertIn('TEST 历史回放', title)

    def test_stage_is_not_monitor_condition(self):
        post = json.dumps(self.send['Post_to_Feishu'], ensure_ascii=False)
        self.assertIn('AMR 维护开始', post)
        self.assertIn('AMR 维护结束', post)
        self.assertNotIn('monitorCondition', post)
        self.assertIn('planned maintenance', post)
        self.assertIn('维护类型未确认', post)

    def test_feishu_business_failure_is_not_success(self):
        action = self.send['Verify_Feishu_result']
        self.assertIn("body('Post_to_Feishu')?['code']", action['expression'])
        self.assertIn("body('Post_to_Feishu')?['StatusCode']", action['expression'])
        self.assertIn("-1)), '0')", action['expression'])
        self.assertEqual(action['else']['actions']['Delivery_failed']['inputs']['runStatus'], 'Failed')

    def test_card_layout_matches_azure_alert(self):
        card = self.card['card']
        self.assertEqual(self.card['msg_type'], 'interactive')
        for color in ("'orange'", "'green'", "'blue'"):
            self.assertIn(color, card['header']['template'])
        title = card['header']['title']['content']
        for text in ('警告', '已恢复', '提示', '｜'):
            self.assertIn(text, title)
        self.assertEqual([e['tag'] for e in card['elements']], ['div', 'hr', 'div', 'action', 'note'])
        fields = card['elements'][0]['text']['content']
        for key in ('时间（北京时间）', '实例', '订阅', '订阅 ID', '资源组', '阶段', '事件状态', 'Event ID'):
            self.assertIn(f"'**{key}**：'", fields)
        self.assertIn('不代表提前预告', card['elements'][2]['text']['content'])
        button = card['elements'][3]['actions'][0]
        self.assertEqual(button['text']['content'], '在 Azure 门户中查看')
        self.assertIn('portal.azure.com/#resource', button['url'])
        self.assertEqual(card['elements'][4]['elements'][0]['content'], 'Azure 告警 · 来源 AMR 维护 · ActivityLog')

    def test_receiver_is_native_schema_with_callback_dependency(self):
        ag=self.notifications['resources'][1]
        self.assertFalse(ag['properties']['logicAppReceivers'][0]['useCommonAlertSchema'])
        self.assertTrue(ag['dependsOn'])
        self.assertEqual(ag['properties']['emailReceivers'], [])

    def test_single_rule_covers_both_operations_without_status_filter(self):
        body=rule_body([f'/subscriptions/{HUB}'])
        conditions=body['properties']['condition']['allOf']
        self.assertEqual(conditions[0],{'field':'category','equals':'ResourceHealth'})
        self.assertEqual(conditions[1],{'field':'resourceType','equals':'Microsoft.Cache/redisEnterprise'})
        self.assertEqual(len(conditions[2]['anyOf']),2)
        self.assertNotIn('status', [c.get('field') for c in conditions])
        self.assertEqual(body['properties']['actions']['actionGroups'],[])
        self.assertFalse(body['properties']['enabled'])
        # The deployed rule (modules/subscription-alert.bicep) uses the same condition, scoped to its own subscription.
        self.assertEqual(self.rule['properties']['condition'], body['properties']['condition'])
        self.assertEqual(self.rule['properties']['scopes'], ['[subscription().id]'])

    def test_raw_fixtures_match_rule_case_insensitively(self):
        rule=rule_body([f'/subscriptions/{HUB}'])['properties']['condition']['allOf']
        for name in ('maintenance-start.json','maintenance-end.json'):
            fixture=fixtures()[name]
            event=fixture['data']['context']['activityLog']
            lookup={'category':event['eventSource'],'resourceType':'MICROSOFT.CACHE/REDISENTERPRISE','operationName':event['operationName']}
            for c in rule:
                if 'anyOf' in c:
                    self.assertTrue(any(lookup[x['field']].lower()==x['equals'].lower() for x in c['anyOf']))
                else:
                    self.assertEqual(lookup[c['field']].lower(),c['equals'].lower())
            self.assertEqual(fixture['data']['properties']['testMode'],'history-replay')
            self.assertIsNone(event['properties'])

    def test_cli_always_has_explicit_subscription_and_no_default_switch(self):
        with patch('azure_helpers.shutil.which',return_value='az'), patch('azure_helpers.subprocess.run') as run:
            run.return_value=SimpleNamespace(returncode=0,stdout='{"ok":true}',stderr='')
            self.assertEqual(az(SPOKE,'group','list'),{'ok':True})
            args=run.call_args.args[0]
            self.assertEqual(args[args.index('--subscription')+1],SPOKE)
            self.assertNotIn('set',args)

    def test_cli_failure_does_not_become_success(self):
        with patch('azure_helpers.shutil.which',return_value='az'), patch('azure_helpers.subprocess.run') as run:
            run.return_value=SimpleNamespace(returncode=1,stdout='',stderr='AuthorizationFailed')
            with self.assertRaises(AzError): az(SPOKE,'group','list')

    def test_windows_cli_bypasses_cmd_and_preserves_url(self):
        url='https://management.azure.com/subscriptions/x/events?api-version=1&$top=10'
        with patch('azure_helpers.os.name','nt'), patch('azure_helpers.shutil.which',return_value='az.cmd'), patch('azure_helpers.Path') as path, patch('azure_helpers.subprocess.run') as run:
            path.return_value.suffix='.cmd'
            path.return_value.resolve.return_value.parents.__getitem__.return_value.__truediv__.return_value.is_file.return_value=True
            run.return_value=SimpleNamespace(returncode=0,stdout='{}',stderr='')
            az(HUB,'rest','--method','get','--url',url)
            args=run.call_args.args[0]
            self.assertEqual(args[1:5],['-X','utf8','-IBm','azure.cli'])
            self.assertEqual(args[args.index('--url')+1],url)
            self.assertEqual(run.call_args.kwargs['env']['AZ_INSTALLER'],'MSI')

    def test_scope_probe_evidence_is_conclusive(self):
        results=json.loads((ROOT/'docs/scope-probe-results.json').read_text())
        self.assertEqual(len(results),4)
        for r in results:
            if r['mode']=='single':
                self.assertTrue(r['accepted']); self.assertTrue(r['temporaryRuleDeleted'])
            else:
                self.assertFalse(r['accepted']); self.assertIn('ScopeIsInvalid',r['error'])
            self.assertFalse(r['request']['properties']['enabled'])
            self.assertEqual(r['request']['properties']['actions']['actionGroups'],[])


if __name__=='__main__':
    unittest.main()

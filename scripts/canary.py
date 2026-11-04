#!/usr/bin/env python3
"""Test Azure alert delivery with isolated, receiver-free canary action groups."""
import argparse
from datetime import datetime, timezone
from azure_helpers import RG, SCENARIO, action_group_id, az, load_config, rest, rule_url

SIGNAL_NAME = 'ag-amr-canary-signal'
RULE_NAME = 'ala-amr-canary'


def signal_id(sid, rg):
    return f'/subscriptions/{sid}/resourceGroups/{rg}/providers/Microsoft.Insights/actionGroups/{SIGNAL_NAME}'


def signal_url(sid, rg):
    return 'https://management.azure.com'+signal_id(sid, rg)+'?api-version=2023-01-01'


def verify_owned(resource):
    if resource.get('tags',{}).get('scenario')!=SCENARIO or resource.get('tags',{}).get('temporary')!='true':
        raise RuntimeError('Not a temporary resource of this scenario; refusing to modify')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','fire','cleanup'))
    parser.add_argument('--apply',action='store_true',required=True)
    # The canary must live in the deployment's resource group: the workflow only accepts it from there.
    parser.add_argument('--resource-group',default=RG)
    parser.add_argument('--action-group',default='ag-amr-maintenance-feishu')
    args=parser.parse_args()
    config=load_config()
    rg=args.resource_group
    action_group=action_group_id(config['hub'],rg,args.action_group)
    for sid in config['subscriptions']:
        if args.action=='prepare':
            rules=az(sid,'monitor','activity-log','alert','list','--resource-group',rg)
            groups=az(sid,'monitor','action-group','list','--resource-group',rg)
            if any(r['name'].lower()==RULE_NAME for r in rules) or any(r['name'].lower()==SIGNAL_NAME for r in groups):
                raise RuntimeError('Canary name already exists; inspect before rerunning prepare')
            tags={'scenario':SCENARIO,'temporary':'true'}
            rest(sid,'put',signal_url(sid,rg),{'location':'global','tags':tags,'properties':{
                'groupShortName':'AMRCanary','enabled':True,'emailReceivers':[],'webhookReceivers':[],'logicAppReceivers':[]}})
            rest(sid,'put',rule_url(sid,RULE_NAME,rg=rg),{'location':'global','tags':tags,'properties':{
                'enabled':True,'description':'TEST ONLY: notification transport validation, not AMR maintenance.',
                'scopes':[signal_id(sid,rg)],'condition':{'allOf':[
                    {'field':'category','equals':'Administrative'},
                    {'field':'operationName','equals':'Microsoft.Insights/actionGroups/write'},
                    {'field':'status','equals':'Succeeded'}]},
                'actions':{'actionGroups':[{'actionGroupId':action_group,'webhookProperties':{'testMode':'canary'}}]}}})
            print(f'PREPARED {sid}; allow alert configuration propagation before fire')
        elif args.action=='fire':
            signal=rest(sid,'get',signal_url(sid,rg)); verify_owned(signal)
            rule=rest(sid,'get',rule_url(sid,RULE_NAME,rg=rg)); verify_owned(rule)
            if signal['properties'].get('emailReceivers') or signal['properties'].get('logicAppReceivers') or signal['properties'].get('webhookReceivers'):
                raise RuntimeError('Canary signal unexpectedly has receivers')
            rest(sid,'put',signal_url(sid,rg),{'location':'global',
                'tags':{**signal['tags'],'testRun':datetime.now(timezone.utc).isoformat()},
                'properties':signal['properties']})
            print(f'FIRED TEST write event at {datetime.now(timezone.utc).isoformat()} for {sid}')
        else:
            for url in (rule_url(sid,RULE_NAME,rg=rg),signal_url(sid,rg)):
                resource=rest(sid,'get',url); verify_owned(resource)
                rest(sid,'delete',url)
            print(f'CLEANED temporary canary resources from {sid}')


if __name__=='__main__':
    main()

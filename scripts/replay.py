#!/usr/bin/env python3
"""Replay approved TEST fixtures through the Logic App without printing its callback."""
import argparse
import json
import urllib.request
import urllib.error
from azure_helpers import RG, BASE, SAMPLE_SUBSCRIPTION, load_config, rest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file',required=True)
    parser.add_argument('--send-test',action='store_true',required=True)
    parser.add_argument('--resource-group',default=RG)
    parser.add_argument('--logic-app',default='logic-amr-maintenance-feishu')
    args=parser.parse_args()
    path=BASE/'samples'/args.file
    if path.parent!=BASE/'samples' or not path.is_file():
        raise RuntimeError('Select a fixture from this scenario samples directory')
    hub=load_config()['hub']
    # Committed samples use a placeholder subscription; point in-scope ones at the real hub.
    body=path.read_text(encoding='utf-8').replace(SAMPLE_SUBSCRIPTION,hub).encode('utf-8')
    payload=json.loads(body)
    workflow=f'https://management.azure.com/subscriptions/{hub}/resourceGroups/{args.resource_group}/providers/Microsoft.Logic/workflows/{args.logic_app}'
    meta=payload.get('data',{}).get('properties') or payload.get('data',{}).get('customProperties') or {}
    # Empty/out-of-scope negative tests are allowed but must not generate notifications.
    if meta.get('testMode')!='history-replay' and args.file!='empty-event.json':
        raise RuntimeError('Fixture must be explicitly labelled as a test')
    callback=rest(hub,'post',workflow+'/triggers/Receive_alert/listCallbackUrl?api-version=2016-06-01',{})['value']
    request=urllib.request.Request(callback,data=body,headers={'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=60) as response:
            print(json.dumps({'fixture':args.file,'httpStatus':response.status}))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Logic App test request failed: HTTP {exc.code}') from None
    except urllib.error.URLError:
        raise RuntimeError('Logic App test request failed at transport layer; callback redacted') from None


if __name__=='__main__':
    main()

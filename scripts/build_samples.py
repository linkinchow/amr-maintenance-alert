#!/usr/bin/env python3
"""Generate clearly labelled historical ResourceHealth replay fixtures."""
import copy
import json
from azure_helpers import BASE, SAMPLE_SUBSCRIPTION


def native(resource_id, phase, time, event_id):
    start = phase == "start"
    return {
        "schemaId": "Microsoft.Insights/activityLogs",
        "data": {"status": "Activated", "context": {"activityLog": {
            "eventSource": "ResourceHealth", "resourceId": resource_id,
            "eventTimestamp": time, "eventDataId": event_id,
            "operationName": "Microsoft.Resourcehealth/healthevent/" + ("InProgress" if start else "Resolved") + "/action",
            "status": "Started" if start else "Succeeded", "properties": None,
            "caller": None, "correlationId": "",
            "eventDescription": ("Planned maintenance has started on this instance and your instance will undergo failover."
                                 if start else "Planned maintenance has completed on this instance and your instance performed a failover."),
        }}, "properties": {"testMode": "history-replay"}},
    }


def fixtures():
    rid=f"/subscriptions/{SAMPLE_SUBSCRIPTION}/resourceGroups/rg-sample/providers/Microsoft.Cache/redisEnterprise/redis-sample-01"
    start=native(rid,"start","2026-09-10T04:47:16.130835Z","eeeeeeee-0000-0000-0000-000000000000")
    end=native(rid,"end","2026-09-10T05:01:28.316131Z","ffffffff-0000-0000-0000-000000000000")
    common={"schemaId":"azureMonitorCommonAlertSchema","data":{
        "essentials":{"alertTargetIDs":[rid],"description":"RULE description is not maintenance evidence","monitorCondition":"Fired"},
        "alertContext":copy.deepcopy(end['data']['context']['activityLog']),
        "customProperties":{"testMode":"history-replay"},
    }}
    del common['data']['alertContext']['resourceId']
    missing=copy.deepcopy(start)
    del missing['data']['context']['activityLog']['eventDescription']
    empty={"schemaId":"Microsoft.Insights/activityLogs","data":{}}
    foreign=copy.deepcopy(start)
    foreign['data']['context']['activityLog']['resourceId']=rid.replace(SAMPLE_SUBSCRIPTION,'00000000-0000-0000-0000-000000000000')
    return {'maintenance-start.json':start,'maintenance-end.json':end,'common-schema-end.json':common,
            'missing-description.json':missing,'empty-event.json':empty,'out-of-scope.json':foreign}


if __name__=='__main__':
    for name,payload in fixtures().items():
        (BASE/'samples'/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(name)

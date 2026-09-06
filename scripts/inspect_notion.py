import os
import json
from job_application_agents.plugins.notion.client import NotionClient

token = os.environ.get("NOTION_TOKEN")
if not token:
    raise SystemExit("NOTION_TOKEN environment variable is required")
client = NotionClient(token=token)

res = client._request("POST", "search", data={})
results = res.get("results", [])
print(f"Total search results: {len(results)}")
for item in results:
    obj = item.get("object")
    iid = item.get("id")
    title = ""
    if obj == "database":
        title_list = item.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_list)
        print(f"DATABASE: {title} | ID: {iid}")
    elif obj == "page":
        props = item.get("properties", {})
        for pk, pv in props.items():
            if pv.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in pv.get("title", []))
        parent = item.get("parent", {})
        print(f"PAGE: {title} | ID: {iid} | Parent: {parent.get('type')} ({parent.get('database_id') or parent.get('page_id')})")

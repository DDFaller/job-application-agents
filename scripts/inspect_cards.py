import os
import json
from job_application_agents.plugins.notion.client import NotionClient

token = os.environ.get("NOTION_TOKEN")
if not token:
    raise SystemExit("NOTION_TOKEN environment variable is required")
client = NotionClient(token=token)
db_id = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"

res = client._request("POST", f"databases/{db_id}/query", data={"page_size": 100})
results = res.get("results", [])
print(f"Total cards in database {db_id}: {len(results)}\n")

for p in results:
    pid = p.get("id")
    props = p.get("properties", {})

    # Title
    title_prop = props.get("Application") or props.get("Name") or {}
    title = "".join(t.get("plain_text", "") for t in title_prop.get("title", []))

    # Status
    status_prop = props.get("Status") or {}
    status = status_prop.get("select", {}).get("name") if status_prop.get("type") == "select" else status_prop.get("status", {}).get("name")

    # Company, Role, URL, Version, Match Score
    company = "".join(t.get("plain_text", "") for t in props.get("Company", {}).get("rich_text", []))
    role = "".join(t.get("plain_text", "") for t in props.get("Role", {}).get("rich_text", []))
    job_url = props.get("Job URL", {}).get("url")
    version = "".join(t.get("plain_text", "") for t in props.get("Current Version", {}).get("rich_text", []))
    score = props.get("Match Score", {}).get("number")

    created_time = p.get("created_time")

    print(f"Card ID: {pid}")
    print(f"  Title:        {title}")
    print(f"  Status:       {status}")
    print(f"  Company/Role: {company} | {role}")
    print(f"  Job URL:      {job_url}")
    print(f"  Version:      {version}")
    print(f"  Match Score:  {score}")
    print(f"  Created Time: {created_time}")
    print("-" * 50)

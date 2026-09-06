from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TOKEN = os.environ.get("NOTION_TOKEN")
DB_ID = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"


def check():
    if not TOKEN:
        raise RuntimeError("NOTION_TOKEN environment variable is required")
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    # 1. Check Database Schema
    print(f"=== 1. Checking Database Metadata ({DB_ID}) ===")
    req_db = urllib.request.Request(f"https://api.notion.com/v1/databases/{DB_ID}", headers=headers)
    with urllib.request.urlopen(req_db) as resp:
        db = json.loads(resp.read().decode())
        title_list = db.get("title", [])
        title = title_list[0].get("plain_text") if title_list else "Untitled"
        print(f"Database Title: {title}")
        print(f"Database URL: {db.get('url')}")
        print(f"Parent: {db.get('parent')}")
        print("\nConfigured Properties:")
        for p_name, p_data in db.get("properties", {}).items():
            print(f" - {p_name} ({p_data.get('type')})")

    # 2. Query Rows in Database
    print(f"\n=== 2. Querying Rows inside Database ({DB_ID}) ===")
    req_q = urllib.request.Request(f"https://api.notion.com/v1/databases/{DB_ID}/query", data=b"{}", headers=headers)
    with urllib.request.urlopen(req_q) as resp:
        query_data = json.loads(resp.read().decode())
        results = query_data.get("results", [])
        print(f"Total Rows Found: {len(results)}")
        for idx, row in enumerate(results, start=1):
            row_id = row.get("id")
            archived = row.get("archived")
            props = row.get("properties", {})
            title_text = ""
            for p_name, p_val in props.items():
                if p_val.get("type") == "title":
                    t = p_val.get("title", [])
                    if t:
                        title_text = t[0].get("plain_text", "")
            status_obj = props.get("Status", {}).get("select") or {}
            status_name = status_obj.get("name", "NO STATUS")
            company_obj = props.get("Company", {}).get("rich_text", [])
            company_text = company_obj[0].get("plain_text", "") if company_obj else ""
            print(f"[{idx}] ID: {row_id} | Archived: {archived} | Title: '{title_text}' | Status: '{status_name}' | Company: '{company_text}'")


if __name__ == "__main__":
    check()

"""Ask a running FS-SC server which projects it knows about. Standard library only."""
import json
import os
import urllib.request

BASE = os.environ.get("FSSC_URL", "http://127.0.0.1:8099")

with urllib.request.urlopen(f"{BASE}/api/projects", timeout=5) as response:
    data = json.load(response)

print(f"active project: {data.get('active_project_id')}")
for project in data.get("projects", []):
    print(f"- {project.get('id') or project.get('project_id')}")

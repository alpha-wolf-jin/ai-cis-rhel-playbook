#!/usr/bin/env python3
import yaml

# Load the original playbook
with open('./cis_rhel9_scan_playbook/cis_audit_1_1_1_1.yml', 'r') as f:
    content = f.read()

playbook_data = yaml.safe_load(content)
play = playbook_data[0]
tasks = play.get('tasks', [])

# Find a task with content field
for task in tasks:
    if 'copy' in task and 'content' in task['copy']:
        print("Found task with content field:")
        print(f"Task name: {task.get('name')}")
        content_value = task['copy']['content']
        print(f"Content type: {type(content_value)}")
        print(f"Content has newlines: {'\\n' in content_value}")
        print(f"Content repr (first 200 chars): {repr(content_value[:200])}")
        print(f"Content actual (first 5 lines):")
        print(content_value.split('\n')[:5])
        break


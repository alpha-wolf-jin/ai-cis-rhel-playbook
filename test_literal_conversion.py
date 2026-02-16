#!/usr/bin/env python3
import yaml

class LiteralStr(str):
    """String class that forces literal block scalar style in YAML."""
    pass

class LiteralDumper(yaml.SafeDumper):
    """Custom dumper that uses literal block scalar style for multi-line strings."""
    pass

def literal_str_representer(dumper, data):
    """Represent LiteralStr as literal block scalars."""
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

def str_representer(dumper, data):
    """Represent regular strings, using literal style if multi-line."""
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

# Register the custom representers
yaml.add_representer(LiteralStr, literal_str_representer, Dumper=LiteralDumper)
yaml.add_representer(str, str_representer, Dumper=LiteralDumper)

def convert_to_literal_strings(obj):
    """Recursively convert multi-line strings in 'content' fields to LiteralStr."""
    if isinstance(obj, dict):
        return {k: LiteralStr(v) if k == 'content' and isinstance(v, str) and '\n' in v 
                else convert_to_literal_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_literal_strings(item) for item in obj]
    else:
        return obj

# Load the original playbook
with open('./cis_rhel9_scan_playbook/cis_audit_1_1_1_1.yml', 'r') as f:
    content = f.read()

playbook_data = yaml.safe_load(content)
play = playbook_data[0]
tasks = play.get('tasks', [])

# Find a task with content field
for task in tasks:
    if 'copy' in task and 'content' in task['copy']:
        print("Original task:")
        print(yaml.dump([task], default_flow_style=False, sort_keys=False)[:500])
        print("\n" + "="*80 + "\n")
        
        # Convert
        converted_task = convert_to_literal_strings(task)
        print("Converted task (checking if content is LiteralStr):")
        if 'copy' in converted_task and 'content' in converted_task['copy']:
            print(f"Content type: {type(converted_task['copy']['content'])}")
            print(f"Is LiteralStr: {isinstance(converted_task['copy']['content'], LiteralStr)}")
        
        print("\nDumped with LiteralDumper:")
        print(yaml.dump([converted_task], Dumper=LiteralDumper, default_flow_style=False, sort_keys=False)[:500])
        break


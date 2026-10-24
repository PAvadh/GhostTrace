"""Patches app.py to add AMLSim dataset selector."""
import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
block_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_app_new_block.py")

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

with open(block_path, "r", encoding="utf-8") as f:
    new_block = f.read()

start = content.find("    # Session State Initialization")
end_marker = "    ledger, graph_result = get_cached_investigation(scenario_choice, seed_val)\n"
end = content.find(end_marker) + len(end_marker)

if start == -1 or end <= len(end_marker):
    print("ERROR: markers not found")
else:
    new_content = content[:start] + new_block + content[end:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Done. Total lines: {new_content.count(chr(10))}")

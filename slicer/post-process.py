#!/usr/bin/env python3
import sys

def process_gcode(lines):
    _has_str = lambda s, line: not 'gcode_substitutions' in line and s in line

    has_extruder_change = any(_has_str('change extruder', line) for line in lines)
    layer_change_index = next((i for i, line in enumerate(lines) if _has_str(';LAYER_CHANGE', line)), None)

    if not has_extruder_change and layer_change_index is not None:
        # Compensate for missing toolchange on default tool/first tool.
        lines.insert(layer_change_index, 'T0 ; missing extruder')
    
    result = []
    for line in lines:
        has_tool_change = _has_str('change extruder', line)
        if has_tool_change:
            result.append('_CLEAR_OFFSETS HOME=1')
        result.append(line)
        if has_tool_change:
            result.append('_APPLY_OFFSETS HOME=1')


    return result

def main():
    if len(sys.argv) < 2:
        print("No file specified", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, "r") as f:
        lines = f.readlines()

    result = process_gcode([l.rstrip("\n\r") for l in lines])

    with open(filepath, "w") as f:
        for line in result:
            f.write(line + "\n")


if __name__ == "__main__":
    main()
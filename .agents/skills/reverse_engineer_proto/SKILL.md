---
name: reverse_engineer_proto
description: Read the protobuf dump log, analyze and reverse engineer unrecognized proto messages, generate .proto definitions, add decoding wrappers, and register them to the wiki.
---

# Skill: Reverse Engineering Protobuf Messages

Use this skill when you need to process `to_be_reverse_engineered.log` to reverse-engineer unknown protobuf payloads, integrate their decoding wrappers, and register them into the livechat wiki.

## Steps to Execute

### 1. Read the Dump Log
Read `to_be_reverse_engineered.log` in the workspace root. Identify any unparsed protobuf entries:
```json
{"event_type": "EVENT_NAME", "path": "field.path", "pb_base64": "...", "timestamp": 1234567}
```

### 2. Analyze the Wire Format
For each unique `(event_type, path)` entry in the log:
1. Extract the `pb_base64` value.
2. Run `scripts/proto_analyzer.py` with the base64 string to analyze the field tags, types, and nested message structures:
   ```bash
   python scripts/proto_analyzer.py <pb_base64>
   ```

### 3. Design the Protobuf Schema
1. Define the appropriate messages (e.g. fields, types, tags) in `bilibili_api/data/protos/livechat_events.proto` or a new `.proto` file.
2. Ensure consistent naming matching Bilibili fields (e.g., standard names like `uid`, `uname`, etc., if recognizable).

### 4. Create and Integrate the Python Decoder
1. Implement a decoder function using `BytesReader` inside `bilibili_api/live.py` (refer to existing implementations like `parse_interact_word_v2` for patterns).
2. Wire the decoder function into Bilibili's `LiveDanmaku` event dispatching loop inside `bilibili_api/live.py` under the corresponding `event_type` handler block, producing a `pb_decoded` dictionary field alongside the raw `pb` field.

### 5. Register with the Wiki Compiler
Add the mapping to `PROTO_PARSERS` in `scripts/build_wiki.py` so that the compiler knows the protobuf field is now successfully reverse-engineered and can annotate it:
```python
PROTO_PARSERS = {
    ...
    ("EVENT_NAME", "field.path"): {
        "parser": "bilibili_api.live.parse_event_name",
        "proto": "bilibili_api/data/protos/livechat_events.proto#EventName"
    }
}
```

### 6. Compile and Clean Up
1. Run `python scripts/build_wiki.py` to compile the wiki and update `docs/wiki.html` and `docs/wiki_data.json`.
2. Remove the processed lines from `to_be_reverse_engineered.log`.

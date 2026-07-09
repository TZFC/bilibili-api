---
name: bilibili-api-maintainance
description: Perform database maintenance: reverse-engineer any unrecognized protobuf fields, and document any undocumented events based on their names and example JSON if confident.
---

# Skill: Bilibili Livechat API Maintenance

Use this skill when the user asks you to "perform maintenance". This skill involves two main tasks:
1. **Reverse Engineering Protobuf Messages**: Decoding binary payloads dumped to `to_be_reverse_engineered.log`.
2. **Documenting Undocumented Events**: Analyzing custom/unknown events (currently labeled as `自定义/未知事件`) and adding their descriptions to the wiki.

---

## Task 1: Reverse Engineering Protobuf Messages

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
Add the mapping to `PROTO_PARSERS` in `scripts/build_wiki.py`:
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

---

## Task 2: Documenting Undocumented Events

### 1. Identify Undocumented Events
Look at `docs/wiki_data.json` or run the compiler. Any event type that displays with the description prefix `自定义/未知事件` is undocumented because it is missing from `CMD_DESCRIPTIONS` in `scripts/build_wiki.py`.

### 2. Analyze Name and Example JSON
For each undocumented event:
1. Inspect its name (e.g., `PK_BATTLE_PRE_NEW`, `WIDGET_GIFT_STAR_PROCESS_V2`).
2. Read its example payload (`example` structure) from `docs/wiki_data.json`.
3. Infer the purpose of the event and its fields (e.g., `PK_BATTLE_PRE_NEW` represents a PK battle preparation event containing opponent details and countdown; `WIDGET_GIFT_STAR_PROCESS_V2` represents progress toward a collective gift goal).

### 3. Add to Wiki Descriptions
Only if you are confident with the interpretation:
1. Write a descriptive description line matching the format of existing commands:
   `"CMD_NAME": "中文名称 (EnglishName): 详细的功能与字段描述。"`
2. Add this entry to `CMD_DESCRIPTIONS` in [build_wiki.py](file:///f:/bilibili-api/scripts/build_wiki.py).

### 4. Compile
1. Run `python scripts/build_wiki.py` to regenerate the wiki files.
2. Verify that the event name is now colored blue (documented) in the sidebar.

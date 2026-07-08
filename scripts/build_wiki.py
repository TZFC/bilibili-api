import os
import sys
import sqlite3
import json
import time
from typing import Dict, Any, Set

# Known Bilibili live stream commands and descriptions
CMD_DESCRIPTIONS = {
    "DANMU_MSG": "弹幕消息 (ChatMessage): 观众在直播间发送的常规弹幕，包含发言人、勋章、等级等丰富信息。",
    "SEND_GIFT": "投喂礼物 (SendGift): 观众向主播赠送道具礼物，包含礼物数量、价格、连击等。",
    "COMBO_SEND": "连击礼物投喂 (ComboGift): 连续赠送礼物时的状态更新。",
    "SUPER_CHAT_MESSAGE": "醒目留言 (SuperChat): 付费留言，在直播间顶部保留显示一段时间。",
    "WELCOME": "欢迎进入直播间 (Welcome): 欢迎普通VIP/老爷级别用户进入房间。",
    "WELCOME_GUARD": "欢迎房管进入直播间 (WelcomeGuard): 欢迎拥有房间管理员身份的用户进入房间。",
    "ENTRY_EFFECT": "特殊入场特效 (EntryEffect): 舰长/大航海等高阶用户进入直播间的酷炫进场特效提示。",
    "INTERACT_WORD": "用户交互事件 (InteractWord): 包含用户进入直播间、关注主播、分享直播间、加入粉丝团等交互动作。",
    "INTERACT_WORD_V2": "用户交互事件 V2 (InteractWordV2): 包含与 INTERACT_WORD 类似的动作，其详细数据封装在 Protobuf (pb) 字节流中。",
    "ONLINE_RANK_COUNT": "高能用户数更新 (OnlineRankCount): 房间在线高能用户总数的实时波动更新。",
    "ONLINE_RANK_V3": "高能用户榜单更新 (OnlineRankV3): 房间内在线的高能用户排行榜信息，其详细列表数据由 Protobuf 编码。",
    "ONLINE_RANK_TOP3": "高能榜前三名 (OnlineRankTop3): 房间内在线前三名高能用户的简要数据通知。",
    "WATCH_ROOM_OUT_LIMIT": "围观人数超限 (WatchLimit): 直播间当前在线人气或人数超出某种系统限额的事件。",
    "WIDGET_BANNER": "挂件/横幅广告 (WidgetBanner): 直播间右上角或挂件横幅的状态更新与配置。",
    "ROOM_REAL_TIME_MESSAGE_UPDATE": "房间实时数据 (RealTimeStats): 直播间粉丝数、点赞数、热度等数据的周期性汇总更新。",
    "PREPARING": "下播/准备中 (Preparing): 主播切断推流下播，系统提示进入准备中状态。",
    "LIVE": "开播通知 (LiveStarted): 主播开始推流，直播间正式转为直播中状态。",
    "STOP_LIVE_ROOM_TIPS": "停播提示 (StopLiveTips): 平台或系统下发的关于本场直播结束的提示信息。",
    "CUT_FILTERS": "分流过滤器 (CutFilters): 与直播分流和推流优化策略相关的过滤控制信号。",
    "VIEW": "人气值更新 (PopularityUpdate): 心跳包返回的直播间当前人气数值值更新。",
    "VERIFICATION_SUCCESSFUL": "认证成功 (VerificationSuccessful): 弹幕客户端与B站WS弹幕服务器完成鉴权握手并确立连接。"
}

# Helper to infer JSON schema
def infer_schema(data: Any, path: str = "", typical_vals: Dict[str, Set[Any]] = None) -> Dict[str, Any]:
    if typical_vals is None:
        typical_vals = {}
        
    if isinstance(data, dict):
        properties = {}
        for k, v in data.items():
            child_path = f"{path}.{k}" if path else k
            properties[k] = infer_schema(v, child_path, typical_vals)
        return {"type": "object", "properties": properties}
        
    elif isinstance(data, list):
        if not data:
            return {"type": "array", "items": {"type": "any"}}
        # Bilibili uses heterogeneous lists (like tuples) for DANMU_MSG info array,
        # so we merge them while keeping index-based properties if they contain different structures.
        # Check if list elements look heterogeneous (e.g. have different types or if it's the top-level info list in DANMU_MSG)
        is_danmu_info = (path == "info" or path.endswith(".info"))
        if is_danmu_info:
            # Represent as object-like array properties to show meaning of each index
            items_schema = {}
            for idx, item in enumerate(data):
                child_path = f"{path}.{idx}"
                items_schema[str(idx)] = infer_schema(item, child_path, typical_vals)
            return {"type": "heterogeneous_array", "items": items_schema}
        else:
            # Standard homogenous array
            child_path = f"{path}[]"
            # Use the first element as the structural template
            items_schema = infer_schema(data[0], child_path, typical_vals)
            return {"type": "array", "items": items_schema}
            
    else:
        # Primitive
        if data is None:
            type_name = "null"
        elif isinstance(data, bool):
            type_name = "boolean"
        elif isinstance(data, int):
            type_name = "integer"
        elif isinstance(data, float):
            type_name = "number"
        else:
            type_name = "string"
            
        if path:
            if path not in typical_vals:
                typical_vals[path] = set()
            if data is not None and len(typical_vals[path]) < 8:
                # Limit length of typical values to keep them readable
                val_str = str(data)
                if len(val_str) < 150:
                    typical_vals[path].add(data)
                    
        return {"type": type_name}

def compile_wiki_data(db_path: str) -> Dict[str, Any]:
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return {"event_types": {}}
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT event_type, raw_data FROM livechat_events ORDER BY id ASC")
    
    event_types_data = {}
    total_events = 0
    
    for event_type, raw_data_str in cursor.fetchall():
        total_events += 1
        try:
            raw_data = json.loads(raw_data_str)
        except Exception:
            continue
            
        if event_type not in event_types_data:
            event_types_data[event_type] = {
                "count": 0,
                "description": CMD_DESCRIPTIONS.get(event_type, f"自定义/未知事件 ({event_type})"),
                "typical_vals_raw": {},  # Set internally
                "example": raw_data
            }
            
        event_types_data[event_type]["count"] += 1
        # Update schema and typical values
        infer_schema(raw_data, "", event_types_data[event_type]["typical_vals_raw"])
        
    conn.close()
    
    # Process final data structure
    compiled = {
        "total_events": total_events,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event_types": {}
    }
    
    for event_type, val in event_types_data.items():
        # Convert schema
        typical_vals_serializable = {}
        for path, values in val["typical_vals_raw"].items():
            typical_vals_serializable[path] = list(values)
            
        schema = infer_schema(val["example"])
        
        compiled["event_types"][event_type] = {
            "count": val["count"],
            "description": val["description"],
            "schema": schema,
            "typical_values": typical_vals_serializable,
            "example": val["example"]
        }
        
    return compiled

def update_wiki():
    db_path = 'livechat_events.db'
    wiki_template_path = os.path.join('docs', 'wiki_template.html')
    wiki_out_path = os.path.join('docs', 'wiki.html')
    
    # Compile
    data = compile_wiki_data(db_path)
    data_json_str = json.dumps(data, ensure_ascii=False, indent=2)
    
    if not os.path.exists('docs'):
        os.makedirs('docs')
        
    # Read template if exists, otherwise use standard template string
    if os.path.exists(wiki_template_path):
        with open(wiki_template_path, 'r', encoding='utf-8') as f:
            template = f.read()
    else:
        template = get_default_html_template()
        with open(wiki_template_path, 'w', encoding='utf-8') as f:
            f.write(template)
            
    # Inject data
    output = template.replace('/* WIKI_DATA_PLACEHOLDER */', f'const wikiData = {data_json_str};')
    
    with open(wiki_out_path, 'w', encoding='utf-8') as f:
        f.write(output)
        
    print(f"Successfully compiled wiki to {wiki_out_path} with {len(data['event_types'])} event types.")

def get_default_html_template() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bilibili 直播弹幕协议 Wiki 文档</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #0f172a;
            --bg-card: #1e293b;
            --bg-hover: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #a855f7;
            --accent-glow: rgba(168, 85, 247, 0.4);
            --border: #334155;
            --type-string: #10b981;
            --type-number: #f59e0b;
            --type-boolean: #3b82f6;
            --type-object: #ec4899;
            --type-array: #8b5cf6;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background-color: var(--bg-main);
            color: var(--text-main);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* Sidebar styling */
        .sidebar {
            width: 320px;
            background-color: #0b0f19;
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            height: 100%;
        }

        .sidebar-header {
            padding: 24px;
            border-bottom: 1px solid var(--border);
        }

        .sidebar-header h1 {
            font-size: 1.25rem;
            font-weight: 700;
            background: linear-gradient(135deg, #c084fc, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }

        .sidebar-header .subtitle {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .search-box {
            padding: 16px 24px;
            border-bottom: 1px solid var(--border);
        }

        .search-box input {
            width: 100%;
            padding: 10px 14px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background-color: var(--bg-main);
            color: var(--text-main);
            outline: none;
            font-size: 0.875rem;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .search-box input:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 2px var(--accent-glow);
        }

        .event-list {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }

        .event-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            border-radius: 8px;
            cursor: pointer;
            margin-bottom: 8px;
            transition: background-color 0.2s, transform 0.1s;
        }

        .event-item:hover {
            background-color: var(--bg-card);
            transform: translateX(4px);
        }

        .event-item.active {
            background-color: var(--accent);
            color: #ffffff;
        }

        .event-name {
            font-size: 0.875rem;
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .event-count {
            font-size: 0.75rem;
            background-color: rgba(255, 255, 255, 0.15);
            padding: 2px 8px;
            border-radius: 12px;
            font-weight: 600;
        }

        /* Content Panel styling */
        .content {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            background-color: var(--bg-main);
        }

        .content-header {
            padding: 32px;
            border-bottom: 1px solid var(--border);
            background-color: var(--bg-card);
        }

        .content-header h2 {
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 12px;
        }

        .content-header .description {
            font-size: 0.95rem;
            color: var(--text-muted);
            line-height: 1.6;
        }

        .content-tabs {
            display: flex;
            gap: 16px;
            padding: 16px 32px 0 32px;
            border-bottom: 1px solid var(--border);
            background-color: var(--bg-card);
        }

        .tab-btn {
            padding: 12px 16px;
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-muted);
            background: none;
            border: none;
            border-bottom: 3px solid transparent;
            cursor: pointer;
            transition: color 0.2s, border-color 0.2s;
        }

        .tab-btn:hover {
            color: var(--text-main);
        }

        .tab-btn.active {
            color: var(--accent);
            border-bottom-color: var(--accent);
        }

        .tab-content-container {
            flex: 1;
            overflow-y: auto;
            padding: 32px;
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        /* Schema representation */
        .schema-node {
            margin-left: 20px;
            border-left: 1px dashed var(--border);
            padding-left: 16px;
            margin-top: 8px;
        }

        .schema-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            font-family: monospace;
            font-size: 0.9rem;
        }

        .key-name {
            font-weight: 600;
            color: var(--text-main);
        }

        .type-badge {
            font-size: 0.75rem;
            padding: 1px 6px;
            border-radius: 4px;
            font-weight: 500;
            text-transform: lowercase;
        }

        .type-string { background-color: rgba(16, 185, 129, 0.15); color: var(--type-string); }
        .type-integer, .type-number { background-color: rgba(245, 158, 11, 0.15); color: var(--type-number); }
        .type-boolean { background-color: rgba(59, 130, 246, 0.15); color: var(--type-boolean); }
        .type-object { background-color: rgba(236, 72, 153, 0.15); color: var(--type-object); }
        .type-array, .type-heterogeneous_array { background-color: rgba(139, 92, 246, 0.15); color: var(--type-array); }

        /* Typical values table */
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }

        th, td {
            text-align: left;
            padding: 14px 16px;
            border-bottom: 1px solid var(--border);
        }

        th {
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }

        td {
            font-family: monospace;
        }

        .val-badge {
            display: inline-block;
            background-color: var(--bg-card);
            padding: 4px 8px;
            border-radius: 4px;
            margin: 2px;
            max-width: 300px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        /* JSON Example View */
        pre {
            background-color: #0b0f19;
            padding: 24px;
            border-radius: 12px;
            border: 1px solid var(--border);
            overflow-x: auto;
            font-family: monospace;
            font-size: 0.875rem;
            line-height: 1.5;
        }

        /* Welcome screen */
        .welcome-screen {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-muted);
            text-align: center;
            padding: 48px;
        }

        .welcome-screen h3 {
            font-size: 1.5rem;
            color: var(--text-main);
            margin-bottom: 12px;
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h1>Bilibili Livechat Wiki</h1>
            <div class="subtitle" id="wiki-stats">加载中...</div>
        </div>
        <div class="search-box">
            <input type="text" id="search-input" placeholder="搜索事件类型..." oninput="filterEvents()">
        </div>
        <div class="event-list" id="event-list">
            <!-- Event types injected here -->
        </div>
    </div>
    
    <div class="content" id="content-panel">
        <div class="welcome-screen" id="welcome-panel">
            <h3>协议库文档中心</h3>
            <p>从左侧列表中选择一个事件类型，以浏览它的协议字段结构、典型取值与 JSON 数据样例。</p>
        </div>
        
        <div id="data-panel" style="display: none; height: 100%; flex-direction: column;">
            <div class="content-header">
                <h2 id="active-cmd-name">CMD_NAME</h2>
                <div class="description" id="active-cmd-desc">Description of the event command.</div>
            </div>
            
            <div class="content-tabs">
                <button class="tab-btn active" onclick="switchTab('schema')">协议字段结构</button>
                <button class="tab-btn" onclick="switchTab('values')">典型字段取值</button>
                <button class="tab-btn" onclick="switchTab('examples')">JSON 样例数据</button>
            </div>
            
            <div class="tab-content-container">
                <div class="tab-content active" id="tab-schema">
                    <div id="schema-tree"></div>
                </div>
                
                <div class="tab-content" id="tab-values">
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 35%">字段路径 (Path)</th>
                                <th style="width: 65%">典型取值 (Typical Values)</th>
                            </tr>
                        </thead>
                        <tbody id="values-table-body">
                            <!-- Injected rows -->
                        </tbody>
                    </table>
                </div>
                
                <div class="tab-content" id="tab-examples">
                    <pre><code id="json-example-code"></code></pre>
                </div>
            </div>
        </div>
    </div>

    <script id="wiki-data-placeholder">
        /* WIKI_DATA_PLACEHOLDER */
    </script>

    <script>
        let currentTab = 'schema';
        let currentCmd = null;

        function initWiki() {
            if (typeof wikiData === 'undefined' || !wikiData.event_types) {
                document.getElementById('wiki-stats').innerText = "未找到协议事件数据，请运行 build_wiki.py 编译。";
                return;
            }

            document.getElementById('wiki-stats').innerText = `已加载 ${Object.keys(wikiData.event_types).length} 种事件 • 共记录 ${wikiData.total_events} 条包 • 更新于 ${wikiData.last_updated}`;
            
            renderEventList();
        }

        function renderEventList() {
            const listContainer = document.getElementById('event-list');
            listContainer.innerHTML = '';
            
            // Sort event types by count descending
            const sortedCmds = Object.keys(wikiData.event_types).sort((a, b) => {
                return wikiData.event_types[b].count - wikiData.event_types[a].count;
            });
            
            sortedCmds.forEach(cmd => {
                const info = wikiData.event_types[cmd];
                const item = document.createElement('div');
                item.className = 'event-item';
                item.id = `item-${cmd}`;
                item.onclick = () => selectEvent(cmd);
                
                const nameSpan = document.createElement('span');
                nameSpan.className = 'event-name';
                nameSpan.innerText = cmd;
                
                const countBadge = document.createElement('span');
                countBadge.className = 'event-count';
                countBadge.innerText = info.count;
                
                item.appendChild(nameSpan);
                item.appendChild(countBadge);
                listContainer.appendChild(item);
            });
        }

        function filterEvents() {
            const query = document.getElementById('search-input').value.toLowerCase();
            const items = document.getElementsByClassName('event-item');
            
            for (let i = 0; i < items.length; i++) {
                const cmd = items[i].id.replace('item-', '');
                const desc = wikiData.event_types[cmd].description.toLowerCase();
                if (cmd.toLowerCase().includes(query) || desc.includes(query)) {
                    items[i].style.display = 'flex';
                } else {
                    items[i].style.display = 'none';
                }
            }
        }

        function selectEvent(cmd) {
            currentCmd = cmd;
            
            // Toggle active classes in list
            const items = document.getElementsByClassName('event-item');
            for (let i = 0; i < items.length; i++) {
                items[i].classList.remove('active');
            }
            document.getElementById(`item-${cmd}`).classList.add('active');
            
            // Show panels
            document.getElementById('welcome-panel').style.display = 'none';
            document.getElementById('data-panel').style.display = 'flex';
            
            // Fill headers
            document.getElementById('active-cmd-name').innerText = cmd;
            document.getElementById('active-cmd-desc').innerText = wikiData.event_types[cmd].description;
            
            // Render active tab contents
            renderTabContent();
        }

        function switchTab(tab) {
            currentTab = tab;
            const tabs = document.getElementsByClassName('tab-btn');
            for (let i = 0; i < tabs.length; i++) {
                tabs[i].classList.remove('active');
            }
            
            // Find active tab button
            event.target.classList.add('active');
            
            // Show corresponding content panel
            const contents = document.getElementsByClassName('tab-content');
            for (let i = 0; i < contents.length; i++) {
                contents[i].classList.remove('active');
            }
            document.getElementById(`tab-${tab}`).classList.add('active');
            
            renderTabContent();
        }

        function renderTabContent() {
            if (!currentCmd) return;
            const info = wikiData.event_types[currentCmd];
            
            if (currentTab === 'schema') {
                const container = document.getElementById('schema-tree');
                container.innerHTML = '';
                container.appendChild(buildSchemaNodeHtml(info.schema, 'Root'));
            } else if (currentTab === 'values') {
                const tbody = document.getElementById('values-table-body');
                tbody.innerHTML = '';
                
                // Sort keys alphabetically
                const paths = Object.keys(info.typical_values).sort();
                paths.forEach(path => {
                    const tr = document.createElement('tr');
                    const tdPath = document.createElement('td');
                    tdPath.innerText = path;
                    tdPath.style.fontWeight = '500';
                    tdPath.style.color = '#c084fc';
                    
                    const tdVals = document.createElement('td');
                    info.typical_values[path].forEach(val => {
                        const span = document.createElement('span');
                        span.className = 'val-badge';
                        span.innerText = JSON.stringify(val);
                        tdVals.appendChild(span);
                    });
                    
                    tr.appendChild(tdPath);
                    tr.appendChild(tdVals);
                    tbody.appendChild(tr);
                });
            } else if (currentTab === 'examples') {
                const pre = document.getElementById('json-example-code');
                pre.innerText = JSON.stringify(info.example, null, 2);
            }
        }

        function buildSchemaNodeHtml(schema, key) {
            const container = document.createElement('div');
            container.className = 'schema-node';
            
            const row = document.createElement('div');
            row.className = 'schema-row';
            
            const keySpan = document.createElement('span');
            keySpan.className = 'key-name';
            keySpan.innerText = key + ':';
            
            const typeBadge = document.createElement('span');
            typeBadge.className = `type-badge type-${schema.type}`;
            typeBadge.innerText = schema.type.replace('_', ' ');
            
            row.appendChild(keySpan);
            row.appendChild(typeBadge);
            container.appendChild(row);
            
            if (schema.type === 'object' && schema.properties) {
                Object.keys(schema.properties).forEach(propKey => {
                    container.appendChild(buildSchemaNodeHtml(schema.properties[propKey], propKey));
                });
            } else if (schema.type === 'heterogeneous_array' && schema.items) {
                Object.keys(schema.items).forEach(indexKey => {
                    container.appendChild(buildSchemaNodeHtml(schema.items[indexKey], `[${indexKey}]`));
                });
            } else if (schema.type === 'array' && schema.items) {
                container.appendChild(buildSchemaNodeHtml(schema.items, '[index]'));
            }
            
            return container;
        }

        window.onload = initWiki;
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    update_wiki()

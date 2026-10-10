# AGENTS.md

## 项目概览

足球比赛数据报表导出模块（Flask + SQLite + openpyxl）。从爬虫共享数据库读取完场比赛快照 JSON，导出为多 Sheet Excel 报表。

基础技术栈：Python 3 + Flask + SQLite（只读连接）+ openpyxl。

## 运行

```bash
python app.py --port 5000
```

依赖：`pip install flask openpyxl`（生产由 systemd 服务 `football-export.service` 托管，端口 8081，Nginx 反向代理 + Basic Auth）。

两套程序共存于同一 VPS：
- `football.service`：爬虫（V2.5.8，端口 5000 内部）
- `football-export.service`：本导出模块（端口 8081）

## 关键配置

- `config.ini`：`[paths]` 段下 `db_path`、`output_dir`（VPS 上指向 `/root/football_system/football.db` 与 `/root/football_system/download`）
- `football_export/config.py`：程序内配置，`_read_config_ini()` 会在启动时读取 config.ini 覆盖默认路径

## 数据模型

`matches` 表：比赛主表（状态字段为 `latest_*` 前缀，如 `latest_state_code=-1` 表示完场）。
`snapshots` 表：快照 JSON，`snapshot_type='fulltime'`。JSON 字段：
- `shijian_json`：技术统计（techStat.itemList / firstHalfList / secondHalfList）、事件（eventTxt.EventTxtLives）、阵型（lineup）、角球（cornerEvent）
- `analysis_json`：联赛排名（curLeagueStat.itemList）、近绩（nearMatches）、往绩（vsMatches）、裁判（referee）、球队ID（homeTeam.id / awayTeam.id）

SQL 关联：优先 `matches.fulltime_snapshot_id = snapshots.id`，否则回退 `snapshots.match_id + snapshot_type='fulltime'`。

## 重要坑点

1. **事件倒序**：`eventTxt.EventTxtLives` 是倒序（完场在前），导出前必须 `reversed()`。
2. **统计项双编码**：同一统计项存在英文键（如 CORNER）与数字码（如 60=解围）、拼写变体（XGNON_PENAlTY），固定表头导出必须归一（见 `fixed_schema.py`）。
3. **百分比小数化**：控球率/成功率等 value 是 int（56表示56%），需 ÷100 转小数。
4. **matches 表无球队 ID 列**：球队 ID 仅嵌在 analysis_json 的 homeTeam.id/awayTeam.id 中。
5. **禁止给运行时 DB 建索引/写**：导出只用只读连接（WAL 模式）。
6. **跨盘符路径**：Windows 上 `relpath` 会抛 ValueError，需 try-except 处理并复制到默认输出目录。

## 模块结构

- `app.py`：Flask 路由 + 后台导出任务线程
- `football_export/`：核心包
  - `db_reader.py`：查询比赛（query_matches）、联赛、日期范围
  - `json_parser.py`：JSON 解析提取（技术统计/事件/近绩/往绩/联赛排名/裁判）
  - `excel_exporter.py`：**V1.7 动态表头**导出（表头随匹配字段动态变化）
  - `fixed_exporter.py`：**V1.8 固定表头**导出（8 Sheet 固定简体中文表头）
  - `fixed_schema.py`：固定表头 schema 配置（8 Sheet 清单 + 英文键/数字码归一映射）
  - `team_master.py`：球队主数据（team_id → 规范名），支持动态新增球队回退 + 增量学习
  - `config.py`：配置；`data/team_master_seed.json`：球队初始化主数据表
- `templates/` + `static/js/` + `static/css/`：Web 前端

## 两个导出模式

- **V1.7 动态表头**（`/`）：所有匹配字段 union，保留全量信息。
- **V1.8 固定表头**（`/fixed`）：8 个 Sheet 表头固定（比赛/指标/近绩/往绩/上半场统计/下半场统计/联赛排名/详细事件），简体中文，双编码归一，球队ID归一，缺失留空。阈值原则：固定(≥25%) / 剔除(<20%)。
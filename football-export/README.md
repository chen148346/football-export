# 足球比赛数据报表导出模块

## 模块简介

独立的 Python 模块，从 SQLite 数据库读取完场足球比赛数据（shijian_json + analysis_json），解析并导出为包含 7 个 Sheet 的结构化 Excel 文件，用于机器学习训练。

## 目录结构

```
football_export/
├── __init__.py          # 包入口，导出主要接口
├── config.py            # 配置常量（数据库路径、odds黑名单、kind映射等）
├── db_reader.py         # 数据库只读访问（筛选、查询）
├── json_parser.py       # JSON解析工具（odds过滤、多语言处理、空值判断）
├── excel_exporter.py    # Excel导出（7个Sheet构建器）
└── export_cli.py        # 命令行工具

scripts/
├── test_export.py       # 测试脚本（用样本数据验证）
├── verify_excel.py      # Excel内容验证脚本
└── analyze_json.py      # JSON结构分析工具（开发辅助）
```

## 快速开始

### 1. 命令行使用

```bash
# 查看数据库信息
python football_export/export_cli.py --db /path/to/football.db --info

# 导出2024年所有完场比赛
python football_export/export_cli.py --db /path/to/football.db \
    --start 2024-01-01 --end 2024-12-31

# 导出英超和西甲中含"曼联"的比赛
python football_export/export_cli.py --db /path/to/football.db \
    --league 英超 西甲 --team 曼联

# 导出前10场（测试用）
python football_export/export_cli.py --db /path/to/football.db --limit 10
```

### 2. Python API 使用

```python
from football_export import export_matches

# 一站式导出
output_file = export_matches(
    db_path="/path/to/football.db",
    start_date="2024-01-01",
    end_date="2024-12-31",
    sclass_names=["英超", "西甲"],
    team_name="曼联",
)

print(f"导出完成: {output_file}")
```

### 3. 分步使用

```python
from football_export import query_matches, export_to_excel

# 第1步：查询比赛数据
matches = query_matches(
    db_path="/path/to/football.db",
    start_date="2024-01-01",
    end_date="2024-12-31",
)

# 第2步：导出Excel
output_file = export_to_excel(matches, output_path="output.xlsx")
```

## Excel 结构（7个Sheet）

| Sheet | 名称 | 粒度 | 列数 | 说明 |
|-------|------|------|------|------|
| 1 | match_overview | 每行一场比赛 | ~19 | 比赛总览：联赛、时间、球队、比分、阵型、角球、黄红牌、裁判 |
| 2 | tech_stats | 每行一场比赛 | 动态(~110) | 技术统计：53项指标×主客队，含射门、控球率、xG等 |
| 3 | events | 每行一个事件 | ~12 | 重要事件：进球、黄牌、红牌、换人、VAR、点球 |
| 4 | player_stats | 每行一名球员 | 动态(~37) | 球员统计：28项技术指标，含位置、上场时间、评分 |
| 5 | near_matches | 每行一场近期比赛 | ~27 | 近期战绩：主客队各自近期比赛记录 |
| 6 | vs_matches | 每行一场交锋记录 | ~25 | 交锋历史：两队历史交锋记录 |
| 7 | goal_distribution | 每行一场比赛×count×球队 | ~15 | 进失球分布：6个时间段的进球率/失球率 |

## 技术要点

### 1. Odds（赔率）字段过滤
以下字段在导出时被完全过滤，确保不泄露赔率数据：
- `companyList`, `companyList2` — 博彩公司赔率数据
- `sameHandicapMatches`, `sameOuMatches` — 同盘口/同大小球比赛
- `matches2` — vsMatches中的二级交锋（含赔率）
- `oddsRecords`, `cornerOdds`, `leaguePanlu`, `letgoal`, `ou` — 各类赔率字段

### 2. 多语言字典处理
球员/裁判姓名可能是 `{"cn": "张三", "en": "Zhang San"}` 格式，统一提取 `cn` 键：
```python
def get_name(name_field):
    if isinstance(name_field, dict):
        return name_field.get("cn", "")
    return name_field or ""
```

### 3. 时间戳处理
- `matches.match_time`：14位字符串 `YYYYMMDDHHMMSS` → 格式化为 `YYYY-MM-DD HH:MM:SS`
- `analysis_json.matchTime`：10位Unix时间戳（秒）→ 转为北京时间（UTC+8）

### 4. 动态列
- **tech_stats**：扫描所有比赛的 `techStat.itemList`，取所有 `kind` 的并集，生成 `home_{kind}_{中文名}` 和 `away_{kind}_{中文名}` 列
- **player_stats**：扫描所有球员的 `techInfos`，取所有 `infoKind` 的并集，生成 `tech_{infoKind}` 列

### 5. 空值判断
所有字段读取前做空值判断，使用 `safe_get()` 函数安全读取嵌套结构：
```python
safe_get(data, "events", "eventList", default=[])
safe_get(data, "techStat", "itemList", 0, "home", "value", default="")
```

### 6. 数值类型转换
- 百分比字符串（如 `"76%"`）→ 浮点数（`0.76`），便于ML训练
- 数值字符串（如 `"7.9"`）→ 浮点数（`7.9`）
- 文本字段（如位置"守门员"）→ 保持字符串

### 7. 只读数据库访问
使用 SQLite URI 只读模式连接，确保不修改任何数据：
```python
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

## 数据筛选

支持以下筛选条件（均可选）：
- **日期范围**：`start_date` / `end_date`（YYYY-MM-DD）
- **联赛**：`sclass_names`（多选）
- **球队**：`team_name`（模糊搜索，匹配主队或客队）
- **数量限制**：`limit`

仅导出 `latest_state_code = -1`（完场）且 `snapshot_type = 'fulltime'` 的比赛。

## 文件命名

导出文件名格式：`training_{联赛}_{开始日期}_{结束日期}_{时间戳}.xlsx`

- 多联赛时用 `multi` 代替
- 无筛选时用 `all` 代替
- 时间戳格式：`YYYYMMDDHHMMSS`

## 依赖

```
openpyxl >= 3.0
```

安装：`pip install openpyxl`

## 数据库表结构

### matches 表（31列）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 比赛ID（主键） |
| sclass_id | INTEGER | 联赛ID |
| sclass_name | TEXT | 联赛名称 |
| sclass_color | TEXT | 联赛颜色 |
| match_time | TEXT | 14位时间字符串 YYYYMMDDHHMMSS |
| match_date | TEXT | 日期 YYYY-MM-DD |
| home_team | TEXT | 主队名称 |
| away_team | TEXT | 客队名称 |
| home_rank | INTEGER | 主队排名 |
| away_rank | INTEGER | 客队排名 |
| weather | TEXT | 天气 |
| round_info | TEXT | 轮次信息 |
| is_neutrality | INTEGER | 是否中立场 |
| latest_state_code | INTEGER | 状态码（-1=完场） |
| latest_state_text | TEXT | 状态文本 |
| latest_state_display | TEXT | 状态显示 |
| latest_home_score | INTEGER | 主队比分 |
| latest_away_score | INTEGER | 客队比分 |
| latest_home_half_score | INTEGER | 主队半场比分 |
| latest_away_half_score | INTEGER | 客队半场比分 |
| latest_home_red | INTEGER | 主队红牌 |
| latest_away_red | INTEGER | 客队红牌 |
| latest_home_yellow | INTEGER | 主队黄牌 |
| latest_away_yellow | INTEGER | 客队黄牌 |
| latest_elapsed_min | INTEGER | 已进行分钟 |
| latest_updated_at | TEXT | 更新时间 |
| created_at | TEXT | 创建时间 |
| first_seen_state | INTEGER | 首次状态 |
| halftime_snapshot_id | INTEGER | 半场快照ID |
| min60_snapshot_id | INTEGER | 60分钟快照ID |
| fulltime_snapshot_id | INTEGER | 完场快照ID |

### snapshots 表（13列）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 快照ID（主键） |
| match_id | INTEGER | 关联比赛ID |
| snapshot_type | TEXT | 快照类型（fulltime/halftime/min60） |
| state_code | INTEGER | 状态码 |
| state_text | TEXT | 状态文本 |
| home_score | INTEGER | 主队比分 |
| away_score | INTEGER | 客队比分 |
| home_half_score | INTEGER | 主队半场比分 |
| away_half_score | INTEGER | 客队半场比分 |
| elapsed_min | INTEGER | 已进行分钟 |
| shijian_json | TEXT | 事件JSON |
| analysis_json | TEXT | 分析JSON |
| created_at | TEXT | 创建时间 |

### reports 表（7列）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 报告ID |
| match_id | INTEGER | 关联比赛ID |
| snapshot_id | INTEGER | 关联快照ID |
| report_type | TEXT | 报告类型 |
| file_path | TEXT | 文件路径 |
| file_name | TEXT | 文件名 |
| created_at | TEXT | 创建时间 |

### 关联方式
- `matches.fulltime_snapshot_id` → `snapshots.id`（优先使用）
- 若 `fulltime_snapshot_id` 为空，fallback 到 `snapshots.match_id` + `snapshot_type='fulltime'`

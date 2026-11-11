# AGENTS.md

## 项目概览

本仓库是足球数据系统 monorepo，包含三个独立模块：

| 目录 | 说明 | 端口 |
|---|---|---|
| `football-export/` | 报表导出模块（当前沙箱运行的主模块，Next.js 之外的独立 Flask 应用） | 5000 / VPS 8081 |
| `football_system/` | 比赛数据爬取系统 V2.6.3（抓取时过滤丢弃全部 odds 数据） | VPS 80 |
| `football_odds/` | 赔率数据系统 V1.0（从 V2.6.3 fork，**全量保留 odds 数据**） | VPS 8083 |

三个模块均为 Python Flask + SQLite(WAL) + APScheduler 架构，各自独立目录、独立数据库、独立 systemd 服务，互不依赖。

### football_odds 与 football_system 的核心差异（维护时必须保持）

1. **odds 全量保留**：`scraper.py` 无 `_filter_odds`；赛程解析写入 `asian_home/asian_letgoal/asian_away/ou_line/ou_result` 5 列；快照保留完整 `shijian_json`（含 oddsRecords/cornerOdds）与 `analysis_json`（含 leaguePanlu/theSamePanKou）
2. **快照节点仅 2 个**：`monitor.py` 的 `MONITOR_NODES` 只有 `ht`(halftime) + `ft`(fulltime)；页面无 60/75 分钟列
3. **错峰运行**：定时刷新 04:01/16:01（原系统 04:00/16:00），监控线程启动 sleep 60 秒
4. **独立资源**：`DB_PATH=football_odds.db`、`SERVICE_PORT=8083`、`football-odds.service`

## 构建和测试命令

各模块无构建步骤，直接运行：

```bash
cd football_odds
python -m py_compile app.py scraper.py config.py db.py monitor.py scheduler.py  # 语法检查
DEPLOY_RUN_PORT=5001 python app.py   # 本地启动（缺 waitress 时 pip install waitress）
```

端到端验证链路：`POST /api/refresh`（抓赛程）→ 查 matches 表 odds 列 → `POST /api/snapshot/<match_id>`（抓快照）→ 查 snapshots 表 jsonData → `GET /match/<id>`（详情页渲染）。

## 代码风格指南

- Python 3、Flask 服务端渲染（Jinja2 模板在各自 `templates/` 目录）
- 数据库访问集中在 `db.py`，动态列 upsert：`scraper.py` 的 match dict 新增字段自动入库（需先在 `db.py` 建列+迁移）
- 版本变更在文件头部 docstring 追加说明，格式 `[V<x.y.z>] 变更内容`
- 页面标题/页脚保持与系统名一致（football_odds 页面标题为「足球赔率数据系统 football_odds V1.0」）

## 安全注意事项

- **严禁**把 VPS 密码、Nginx Basic Auth 密码、GitHub token 写入仓库
- 抓取目标为球探网（m.titan007.com），使用随机 UA headers（`config.get_random_headers`），不要提高抓取频率
- 两个爬取系统时刻表刻意错峰，新增定时任务必须避开 04:00/16:00 整点

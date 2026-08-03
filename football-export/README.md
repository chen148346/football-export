# 足球比赛数据报表导出模块 V1.7

独立的 Python 模块，从 SQLite 数据库读取足球比赛数据，解析并导出为包含 12 个 Sheet 的结构化 Excel 文件，支持**完场/半场/自定义分钟区间**三种模式，用于机器学习训练。

## 目录结构

```
football-export/
├── config.ini               # 配置文件（数据库路径、导出目录）
├── app.py                   # Flask Web 应用
├── requirements.txt         # Python 依赖
├── .gitignore
├── README.md
├── football_export/         # Python 包
│   ├── __init__.py          # 包入口，export_matches 一站式接口
│   ├── config.py            # 配置常量（路径、odds黑名单、kind映射等）
│   ├── db_reader.py         # 数据库只读访问（筛选、查询）
│   ├── json_parser.py       # JSON 解析（odds过滤、多语言处理、空值判断）
│   ├── excel_exporter.py    # Excel 导出（12个Sheet构建器）
│   └── export_cli.py        # 命令行工具
├── templates/               # HTML 模板
│   └── export.html
├── static/                  # 静态资源
│   └── js/export.js
├── docs/
│   └── 项目文档.md           # 完整项目文档（各版本迭代、API、测试）
├── download/                # 导出文件输出目录（自动创建）
│   └── {联赛}_{日期范围}/    # V1.7 按联赛+日期创建子目录
└── football.db              # 数据库文件
```

## 详细文档

完整项目文档（含版本演进、架构说明、API 接口、测试用例等）请参阅：

📄 [`docs/项目文档.md`](docs/项目文档.md)

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 Web 应用

```bash
python app.py
# 访问 http://localhost:5000
```

### 3. 命令行使用

```bash
# 查看数据库信息
python football_export/export_cli.py --info

# 导出数据
python football_export/export_cli.py --start 2024-01-01 --league 英超 --team 曼联
```

## 配置文件

编辑 `config.ini` 设置数据库路径和导出目录（留空则自动检测）：

```ini
[paths]
db_path =                    # 留空自动查找 football.db 或 upload/*.db
output_dir =                 # 留空默认使用 download/
```

## Web 功能

| 功能 | 说明 |
|------|------|
| 📅 日期时间筛选 | 精确到分钟，支持快捷按钮 |
| 🏆 联赛多选 | 左右分栏布局，支持搜索/全选/清空 |
| ⚽ 球队搜索 | 模糊搜索球队名称 |
| 🏁 按球队拆分 | 勾选后每支球队生成独立 Excel 文件 |
| 📊 12 个 Sheet | 比赛总览/技术统计/事件/球员/近绩/往绩/分布/上下半场/联赛排名/半全场统计/详细事件 |
| ⏱ 非完场模式 | 支持半场快照和自定义分钟区间导出 |
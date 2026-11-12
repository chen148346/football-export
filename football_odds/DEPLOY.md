# football_odds 部署指引（VPS）

football_odds V1.0 是从 football_system V2.6.3 fork 的独立系统：**抓取时保留全部 odds 数据**（赛程亚盘/大小球、ShiJian oddsRecords 逐次赔率变动、cornerOdds 角球盘、Analysis 联赛盘路统计/同盘历史），监控快照节点只保留 **中场(halftime) + 完场(fulltime)**。

与原系统的关系：**完全并行、互不影响**——独立目录、独立数据库、独立端口、独立 systemd 服务。原系统（football.service）零改动继续运行。

## 关键差异一览

| 项目 | 原系统 football_system | 新系统 football_odds |
|---|---|---|
| 目录 | /root/football_system | /root/football_odds |
| 数据库 | football.db | football_odds.db |
| 端口 | 80 | 8083（Nginx Basic Auth 对外）→ 127.0.0.1:8090（后端） |
| 服务 | football.service | football-odds.service |
| 定时刷新 | 04:00 / 16:00 | 04:01 / 16:01（偏移1分钟，避免同时请求球探网） |
| 快照节点 | 中场/60分/75分/完场 | 仅 中场/完场 |
| odds 数据 | 抓取时过滤丢弃 | 全量保留入库 |

## 部署步骤

```bash
# 1. 创建目录并上传代码（本地执行 scp 或 git clone）
mkdir -p /root/football_odds
# 在本地执行：
#   scp -r football_odds/* root@<VPS_IP>:/root/football_odds/
# 或在 VPS 上：
#   cd /root/football_odds && git clone <repo> .  (monorepo 的子目录是 football_odds/)

# 2. 创建虚拟环境并安装依赖
cd /root/football_odds
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. 安装 systemd 服务
cp football-odds.service /etc/systemd/system/football-odds.service
systemctl daemon-reload
systemctl enable football-odds
systemctl start football-odds

# 4. 确认运行状态
systemctl status football-odds
ss -tlnp | grep 8083
journalctl -u football-odds -f

# 5. 防火墙放行 8083（如需外网访问）
iptables -I INPUT -p tcp --dport 8083 -j ACCEPT
# 云服务器还需在安全组放行 8083
```

访问：`http://<VPS_IP>:8083`（Nginx Basic Auth 弹窗验证，与旧系统一致）

## 访问保护（Nginx Basic Auth 反代）

后端服务只监听本机回环 `127.0.0.1:8090`（service 文件里 `BIND_HOST` + `DEPLOY_RUN_PORT=8090`），外部无法直连；Nginx 监听 8083 对外，先弹密码验证再反代到后端。

Nginx 配置示例（`/etc/nginx/conf.d/football-odds.conf`）：

```nginx
server {
    listen 8083;
    server_name _;
    auth_basic "football_odds";
    auth_basic_user_file /etc/nginx/.htpasswd;   # 与旧系统共用密码文件
    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

修改后端绑定后需 `systemctl daemon-reload && systemctl restart football-odds`，Nginx 改配置后 `nginx -t && systemctl reload nginx`。

## 使用方式

1. 首页自动刷新当日赛程（含亚盘/大小球两列）
2. 进入「定时监控」页，添加要跟踪的比赛 ID（或配置自动监控联赛）
3. 监控线程 2 分钟轮询，到达中场/完场自动抓快照（完整保留 oddsRecords/cornerOdds/analysis）
4. 点击比赛进入详情页，查看「赔率变动明细」（按公司×亚盘/大小球/欧赔×全场/半场分组）、「角球盘」、「联赛盘路统计」

## 注意事项

- 数据库首次启动自动创建 `football_odds.db`（WAL 模式），与 football.db 完全隔离
- 定时刷新刻意偏移 1 分钟（04:01/16:01），监控线程启动后先 sleep 60 秒再轮询，降低对球探网的并发压力
- 若原系统也在同机运行，两者互不知晓对方，无需任何联动配置
- 备份：定期拷贝 `football_odds.db`（WAL 模式下建议先 `PRAGMA wal_checkpoint(TRUNCATE)` 或连 `-wal` 一起拷）

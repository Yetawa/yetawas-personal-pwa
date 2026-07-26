# 国内部署指南（Python 原样部署，零改写、精度零风险）

本程序是纯标准库实现（`fund_arb.py`），本仓库即完整部署包。
**不用改写任何代码**，直接把 `fund_arb.py` 跑在能 24 小时在线的腾讯云主机上，
手机通过公网地址即可访问两个界面（界面一 `/`、界面二 `/ranking`）与内置 PWA。

> 为什么选这条路：EdgeOne Pages 边缘函数只支持 JavaScript，要把约 2000 行估算引擎用 JS 重写并重新对拍，
> 极易引入计算漂移（而你最看重估算精度）。原样部署 Python 后端则完全规避该风险。

---

## 路线一：腾讯云轻量应用服务器（推荐，约 ¥几十/年）

### 1. 选购与初始化
- 轻量应用服务器 → 镜像选 **系统镜像 / Ubuntu 22.04**（或 TencentOS），配置 **1 核 1G 起步**（Python 单进程占用很小，2 核 2G 更从容）。
- 创建后，在控制台「防火墙」放行 **TCP 8000**（若改端口需同步放行）。
- SSH 登录，确认 Python：`python3 --version`（Ubuntu 自带 3.10+）。

### 2. 上传代码
```bash
# 方式 A：从本 GitHub 仓库克隆（推荐，后续更新只需 git pull）
apt update && apt install -y git
git clone https://github.com/Yetawa/yetawas-personal-pwa.git /opt/fund_arb
cd /opt/fund_arb

# 方式 B：本地 scp 上传
# scp -r ./* root@<轻量公网IP>:/opt/fund_arb/
```

### 3. 常驻启动
**方式 A（systemd，生产推荐）**：把仓库里的 `fund-arb.service` 放到 `/etc/systemd/system/`，然后
```bash
cp fund-arb.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now fund-arb
systemctl status fund-arb   # 应显示 active (running)
```

**方式 B（nohup 临时）**：
```bash
cd /opt/fund_arb
HOST=0.0.0.0 PORT=8000 nohup python3 fund_arb.py > server.log 2>&1 &
```

### 4. 域名 + HTTPS（让手机能装 PWA）
PWA 要求 HTTPS（或 localhost）。两种做法：

**做法 1（推荐，复用你已有的 EdgeOne）**：
- EdgeOne 控制台 → 接入站点 → 加速域名（如 `fund.你的域名.com`）→ 源站类型「IP/端口」填轻量**公网 IP:8000**。
- EdgeOne 自动签发 HTTPS 证书。手机访问 `https://fund.你的域名.com` 即可。

**做法 2（nginx + 自有证书）**（可选）：
```nginx
server {
    listen 443 ssl;
    server_name fund.你的域名.com;
    ssl_certificate     /path/fullchain.pem;
    ssl_certificate_key /path/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 5. 手机访问
- 界面一：`https://fund.你的域名.com/`
- 界面二：`https://fund.你的域名.com/ranking`
- 浏览器「添加到主屏幕」即得到可全屏、带日/夜切换的 App（PWA 已内置）。

---

## 路线二：腾讯云 CloudBase Web 函数（Serverless，免运维）

1. CloudBase 控制台 → 新建「云函数」→ 运行环境 **Python 3.10** → 函数类型选 **Web 函数**。
2. 上传本仓库代码（或关联 GitHub 仓库做自动部署）。
3. **启动命令**填：`python fund_arb.py`（Web 函数会注入 `PORT`，程序自动绑定 `0.0.0.0`）。
4. 绑定自定义域名 + HTTPS（CloudBase 提供或自有证书）。
5. 缓存 `weights_cache.json` / `holdings_mode_cache.json` 写在函数代码目录，容器层可写会落盘；
   冷启动首次会跑权重校准（约数十秒），之后命中缓存变快。免费额度对个人看盘足够。

> 验证：部署后 `curl https://你的域名/api/validate?code=513310` 应返回 JSON（含 name/error 等字段）。

---

## 本地代码上传到 GitHub（供上面「克隆 / 自动部署」用）

本仓库已 `git init` 并提交。你只需关联远程并推送（需你自己的 GitHub 凭证）：

```bash
git remote add origin https://github.com/Yetawa/yetawas-personal-pwa.git
git branch -M main
git push -u origin main
```

推送后：轻量可 `git clone` 拉取；CloudBase 可在函数里「关联 GitHub 仓库」实现提交即部署。

---

## 数据合规提醒
东财/腾讯/stockanalysis 均为非官方公开接口，个人自用一般无碍；若公开发布请注意数据版权与平台规范。

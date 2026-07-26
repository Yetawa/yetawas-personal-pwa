# 部署到云端（让手机随时随地查看，不依赖本机电脑）

本程序纯标准库实现，无任何第三方依赖，可直接部署到任意支持 Python 的云平台。
部署后手机会访问「云端后端」返回的网页，电脑关不关机都不影响。

## 方式一：Render（免费、最简单，推荐个人使用）
1. 注册 https://render.com （可用 GitHub 登录）。
2. 把本目录推到一个 GitHub 仓库（或直接用 Render 的 "Deploy from filesystem" / 拖拽上传）。
3. 在 Render 新建 **Web Service**：
   - Runtime: Python 3
   - Build Command: `echo ok`
   - Start Command: `python fund_arb.py`
   - 实例类型选 **Free**
4. 部署完成后 Render 会给你一个 `https://xxxx.onrender.com` 的公网地址。
5. 手机浏览器直接打开该地址即可，填基金代码实时查询。
   - 访问 `https://xxxx.onrender.com` 是**单基金套利看板（界面一）**。
   - 访问 `https://xxxx.onrender.com/ranking` 是**基金溢价排行表（界面二）**，支持多基金按单日溢价排序、更换日期、增删代码。
   - 首次冷启动可能要等几秒（免费实例休眠后唤醒）。
   - 数据抓取走东财/腾讯/stockanalysis，与本地完全一致。

> 免费版限制：15 分钟无访问会休眠，下次访问约 30s 唤醒。个人看盘完全够用。

## PWA（可安装到手机主屏幕 / 离线看壳）
本仓库已内置 PWA 能力，部署后**无需额外配置**即可使用：
- `manifest.json`（应用名、图标、standalone 全屏模式）
- `sw.js`（Service Worker：缓存应用壳 + 数据接口网络优先、失败回退缓存）
- `icon.svg`（蜡烛图风格图标）

它们既以文件形式存在于仓库根目录，也作为常量内置在 `fund_arb.py` 中，由同一个 Python 服务自动托管（路由 `/manifest.json`、`/sw.js`、`/icon.svg`）。只要按上面的方式部署成功，**HTTPS 访问下浏览器/手机就会出现「安装 / 添加到主屏幕」入口**，像 App 一样打开，且保留日/夜切换。

应用壳缓存已包含 `/`（界面一）和 `/ranking`（界面二），两个页面均可离线看壳；排行数据同样走「网络优先、失败回退缓存」。

使用要点：
- **必须 HTTPS 或 localhost（安全上下文）**：Render / Railway / 自建 HTTPS 域名都行；直接双击 `fund_arb.html`（`file://` 协议）时 Service Worker 不生效，PWA 无法安装，但数据查询仍可用。
- 离线时显示已缓存的外壳，数据走「网络优先、失败回退上次缓存」，弱网也能看到最近一次结果。
- 想自定义应用名 / 图标：直接改仓库里的 `manifest.json` 和 `icon.svg` 即可（服务器优先读取磁盘文件，无则回退到内置常量）。

## 方式二：Railway / Fly.io / 腾讯云轻量服务器
- 同样是 `python fund_arb.py`，平台会注入 `PORT` 环境变量（程序已支持）。
- 腾讯云轻量服务器：装好 Python，用 `nohup python fund_arb.py &` 或 systemd 常驻，
  再在安全组放行对应端口，绑定域名 + HTTPS 证书即可。

## 方式三：做成微信小程序（进阶）
小程序不能直接调东财，也不能连 localhost，必须：
1. 先按上面把后端部署成**公网 HTTPS 服务**；
2. 注册微信小程序账号拿到 `appid`；
3. 在小程序后台把你的域名加入「request 合法域名」（需 ICP 备案 + HTTPS）；
4. 前端用 `wx.request` 调 `https://你的域名/api/data`，页面用 WXML 重写。
本仓库可加一个 `miniprogram/` 目录承载前端代码，后端复用 `fund_arb.py`。

## 数据合规提醒
东财/腾讯/stockanalysis 均为非官方公开 API，个人自用一般无碍；
但若要公开发布（尤其小程序上架），请注意数据版权与平台运营规范，
必要时应改用券商/指数公司官方数据接口。

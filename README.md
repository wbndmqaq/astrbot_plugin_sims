# astrbot_plugin_sims (模拟人生 Sims AstrBot 插件)

基于 Yunzai 原版 [sims-plugin](https://github.com/) **全量移植**的 AstrBot 插件 v1.0.0。
角色扮演、职业晋升、买房置业、农场种植、酒馆/网吧/影院经营、钓鱼、股市、抽奖、恋爱养成、宠物等玩法一应俱全，共 **184 条指令**。

## ✨ 移植完成度

对照原版 157 条指令规则（`#模拟人生版本` 在原版两个模块重复注册，已去重），本插件注册 **184 条指令**：

| 模块 | 指令数 | 说明 |
| :--- | :--- | :--- |
| 主角色系统 | 11 | 创建角色/签到/改名/签名/头像馆/体力药水 |
| 帮助+公告+引导 | 9 | 指令手册/版本公告/更新日志/分阶段新手引导 |
| 统一商店 | 10 | 12 家 NPC 商店、购买/出售/使用/装备/搜索 |
| 成就系统 | 3 | 多维成就徽章、自动解锁、奖励领取 |
| 农场 | 14 | 买地/升级/种子农具/种植/浇水/施肥/收获/季节 |
| 职业系统 | 24+3 | 6 职业、技能晋升、跨玩家协作、联动任务链 + 医生手术/警察破案/消防火情真实数据行动 |
| 酒馆 | 15 | 调酒上架、原料行情、员工、营业随机事件、排行参观 |
| 电影院 | 11 | 影厅/片源/排片/设施/员工/票房结算/排行 |
| 网吧 | 20 | 设备维护、零食进货定价、VIP 包间、店内活动（原版仅实现 10 条，本版补全） |
| 钓鱼 | 10 | 两段式垂钓、鱼竿鱼饵鱼篓、新鲜度衰减、排行 |
| 股市 | 5 | 5 分钟随机游走行情、买卖持仓盈亏 |
| 抽奖 | 5 | 多奖池、稀有度保底、十连保底、抽奖券 |
| 房产 | 6 | 市场筛选、装修出租出售、每小时行情波动 |
| 管理命令 | 14 | 配置管理/反作弊开关/封禁/数据报告/更新 |
| 恋爱养成 | 7 | 邂逅 NPC、送礼约会、求婚订婚、举办婚礼 |
| 宠物系统 | 6 | 抽卡池、喂食遛弯、亲密度、放生 |
| 厨师烹饪 | 9 | 食材市场、菜谱烹饪、厨具加成、研发菜品 |
| 时装店 | 6 | 8 部位时装、品质加成、套装收集，提升魅力/心情 |
| 世界事件 | 1 | 每小时按概率触发天气/职业/社交事件，`#小镇动态` 查看 |

> 恋爱/宠物/厨师/时装/世界事件/商店扩展基于原版携带但从未接入指令的数据实现。

---

## 📦 安装教程

### 0. 环境要求

| 项 | 要求 |
| :--- | :--- |
| AstrBot | ≥ v4.16.0 |
| Python | 3.10+（与 AstrBot 运行环境一致） |
| 系统 | Windows / Linux / macOS 均可 |

### 1. 安装插件本体

**方式 A：WebUI 在线安装（推荐）**

1. 打开 AstrBot WebUI → 插件管理 → 从仓库安装
2. 输入本插件仓库地址，点击安装
3. AstrBot 会自动执行 `pip install -r requirements.txt`

**方式 B：手动放置**

```bash
# 进入 AstrBot 目录
cd AstrBot/data/plugins

# 方式一：git clone
git clone https://github.com/wbndm/astrbot_plugin_sims.git

# 方式二：下载 zip 后解压到 data/plugins/astrbot_plugin_sims
```

### 2. 安装 Python 依赖

使用 **AstrBot 同款 Python 环境**（venv/docker 内）执行：

```bash
pip install -r data/plugins/astrbot_plugin_sims/requirements.txt
```

当前依赖只有两项：`playwright`、`pyyaml`。

<details>
<summary>国内网络加速</summary>

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```
</details>

### 3. 安装浏览器内核（图片渲染必需）

游戏面板图片由 Playwright 驱动 Chromium 截图生成，**必须单独下载内核**：

```bash
playwright install chromium
```

- **Linux 服务器**还需安装系统依赖：
  ```bash
  playwright install-deps chromium
  # 或 Debian/Ubuntu: apt install libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2
  ```
- **Windows 服务器**：如启动报错缺 DLL，安装 [VC++ 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- <details>
  <summary>内核下载加速</summary>

  ```bash
  # 设置镜像后再执行 playwright install chromium
  set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright   # CMD
  $env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright" # PowerShell
  export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright  # Linux
  ```
  </details>

> 💡 Docker 部署：在容器内执行上述命令；若使用 AstrBot 官方镜像，可挂载后 `docker exec -it astrbot bash` 进容器操作。

### 4. 启动与验证

1. 重启 AstrBot（或 WebUI 插件管理里重载本插件）
2. 日志出现 `载入成功` 且无红色报错
3. 在任意会话发送：

```
#开始模拟人生     ← 创建角色
#模拟人生帮助     ← 查看全部指令（验证图片渲染）
```

能收到帮助图片即安装完成 ✅

### ❓ 常见问题

| 现象 | 解决 |
| :--- | :--- |
| 提示「图片渲染组件未安装」 | 执行第 2 步 `pip install playwright` |
| 提示「浏览器内核未就绪」 | 执行第 3 步 `playwright install chromium` |
| Linux 下浏览器闪退/缺 so 文件 | 执行 `playwright install-deps chromium` |
| 渲染出的图片字体不对 | 服务器需安装中文字体（Windows 自带；Linux 可 `apt install fonts-noto-cjk`） |
| 指令没反应 | 确认消息以 `#` 开头；WebUI 里检查插件是否为「已启用」状态 |
| 数据存在哪里 | `data/plugin_data/astrbot_plugin_sims/sims.db`（SQLite，玩家存档+运行状态）；备份此目录即备份全服进度 |

### 🔄 更新与卸载

- **更新**：WebUI 插件管理 → 本插件 → 更新（或手动 `git pull` 后重载）。玩家存档在 plugin_data 目录，更新不会丢失
- **卸载**：WebUI 卸载插件。如需彻底清档，手动删除 `data/plugin_data/astrbot_plugin_sims/`

---

## 🖥 独立 WebUI 管理面板

插件启动后自带独立端口的管理面板（设计参考上班族物语 WebUI，樱花粉主题），浏览器打开 `http://127.0.0.1:17818` 即可访问。

**功能**：

- **总览**：玩家存档数 / 注册指令数 / 数据库大小 / 有效封禁数 / 世界事件横幅 / 一键清空全服指令冷却
- **玩家管理**：搜索分页列表（金币/体力/等级/职业/婚姻/封禁状态）、在线改金币体力与名字、封禁/解封、删除存档（二次确认弹窗）
- **股市行情**：实时行情表，现价格子内联改价（黄框=待保存）→ 批量保存，即时影响玩家买卖
- **世界事件**：当前事件详情、强制抽取一次事件作用于全体玩家
- **配置查看**：只读展示合并后的配置组（defSet + 用户覆盖）

**配置与安全**（WebUI 可调）：

| 配置 | 默认 | 说明 |
| :--- | :--- | :--- |
| `webui_enabled` | true | 是否启动面板 |
| `webui_host` | 127.0.0.1 | 仅本机可访问；改为 0.0.0.0 可局域网访问 |
| `webui_port` | 17818 | 端口被占用时更换后重载即可 |
| `webui_password` | （空） | 访问密码；监听非本机地址时**务必设置** |

- 设置密码后所有管理接口需 HMAC Cookie 会话（12 小时有效），密码错误有防爆破延迟
- 未设密码且监听非本机地址时，启动日志会输出安全警告

## 🖼 渲染架构

- **内置 art-template 编译器**：将原版 55 个 HTML 模板的 art-template/EJS 方言
  （`{{each}}/{{if}}/{{set}}`、三元、可选链、箭头函数、`<% %>` 语句块、`{{extend}}` 布局）
  直接编译为 Python 函数，无模板引擎转译损耗。
- **本地 Playwright 截图**：通过 `<base href>` 注入解析模板内的相对资源引用
  （头像/字体/CSS），完全离线可用，不依赖任何云端渲染服务。
- **QQ 官方适配器增强**：`qq_official`/`qq_official_webhook` 平台下文本回复自动走
  Markdown 通道（标题加粗/分隔线规整/文末快捷指令提示），发送失败自动降级纯文本；
  按钮键盘因 AstrBot 平台层未暴露接口暂不支持。
- **存储**：SQLite 单库（WAL 模式），`players` 表按用户存 JSON 文档（与原版存档结构
  兼容），`kv` 表存全局状态；静态游戏数据保持 `data/*.json` 纯 JSON 由缓存层读取。
- **定时任务**：每小时世界推进（时间/天气/事件）、农场生长、酒馆行情、影院票房结算、
  网吧收益、股价波动、房产市场、鱼篓保鲜，统一注册到一个 tick 循环。

## 🛠 与原版的已知差异

| 项 | 原版 | 本版 |
| :--- | :--- | :--- |
| Redis 双写同步/防作弊 | 本地 JSON + Redis 镜像，不一致即封禁 | 单一权威存档；反作弊保留开关/封禁/报告指令，一致性检查改为缺失字段自动修复 |
| `#模拟人生版本` | 帮助与公告模块重复注册（双重回复） | 仅帮助模块注册（图片渲染） |
| 网吧 20 条规则 | 仅实现 10 条，其余触发报错 | 全部实现 |
| 体力药水商店 | `staminaPotions` 未定义（运行时崩溃） | 补全三档药水定义 |
| 签名敏感词 | `sensitiveWords` 未定义（运行时崩溃） | 补全词表 |
| `#抽奖` 带前缀 | `#模拟人生抽奖` 解析出错误奖池名 | 前缀解析修复 |
| 指令冲突 | `#购买.*` 会同时命中多个模块 | 按优先级仲裁；`#雇佣员工` 网吧/酒馆按工种自动分流 |
| `#更新` | Yunzai git 更新 | 输出 AstrBot WebUI 更新指引 |

## ⚙️ 插件配置（WebUI 可调）

| 配置 | 默认 | 说明 |
| :--- | :--- | :--- |
| `reply_mode` | text | 普通文本回复方式：image（渲染成图片）/ text（纯文本）/ auto |
| `render_scale` | 100 | 图片渲染缩放百分比（50-200） |
| `hourly_cron` | true | 每小时世界推进开关（时间/天气/事件/经营结算） |

游戏内数值配置（冷却/职业/奖池/网吧 等）沿用原版 `defSet/*.yaml` 体系，
管理员可用 `#查看配置` / `#修改配置` / `#重置配置` 热调整。

## 🧪 测试

```bash
# 渲染引擎（编译器单测 + 真实截图冒烟）
python tests/test_render_engine.py
# 全量指令端到端
python tests/test_player_commands.py
# AstrBot 载入链路模拟（stub astrbot 包 + 注册数量断言）
python tests/test_boot.py
```

## 📄 License

沿用原版 sims-plugin 的开源协议（见 LICENSE）。

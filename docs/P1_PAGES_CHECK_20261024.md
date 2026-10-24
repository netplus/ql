# Pages 发布候选：版本一致性与启动诊断

核查日期：2026-10-24。该日期不是市场数据日期。本轮不采集行情、不改变历史样例、不增加交易信号。

## 当前实际状态

读取 `netplus/ql` 返回 `visibility=public`、`has_pages=false`；Actions runs 返回零记录。PR #2 仍为草案，源分支起点 `11fd14ef1fcb1b9551951e2698d27178a8102bb2`；发布分支起点 `93903a868b1a0d40a1ed5153540c9661317bc4a0`。用户此前已自行公开仓库，本轮不改变可见性。

现有 GitHub 连接动作可读取和更新代码，但没有 Pages 设置管理动作。本轮没有启用站点、合并 main、购买服务或添加工作流。发布分支更新不等于部署成功。

当前工作环境：对预期项目地址 `https://netplus.github.io/ql/` 的直接 HTTP 检查为 DNS 解析失败；网页读取工具也未能打开；Chromium 对本地 HTTP 与该 HTTPS 地址导航均报告 `ERR_BLOCKED_BY_ADMINISTRATOR`。没有修改浏览器策略。网络受限不证明远端站点宕机；站点未启用的依据是仓库返回的状态，不是 DNS 错误。

## 新增实现

`tools/build_pages_candidate.py` 接收现有 `build_release.py` 生成的 public 目录，生成版本 `p1.2-pages-integrity/1`：

- 为脚本和样式按内容 SHA-256 命名；HTML 和动态加载的 app 脚本带 SRI 校验。
- 仅接受已审计 P1.1 空壳字节集合；固定输入摘要防止伪造 manifest 后混入其他代码或数据。将来修改源应用需要重新审核并更新此有限迁移工具的基线，不自动放开准入。
- 增加可读的启动状态、组件缺失/资源失败/执行失败/超时提示和重新载入按钮；不清空用户数据，不上传文件。
- 保留上一代五个静态资源，旧缓存 HTML 不因本次改名而立即缺文件。仅保留一个明确的兼容代际，不无限积累。
- 共13个发布文件，无行情数据、持仓、备注或密钥。`index.html` 的数据块仍为 `null`，网络数据请求仍被 CSP 禁止。

`tools/verify_pages.py` 用本地已审核的候选字节作为期望值，逐项校验站点根页面和资源；不把远端自述 manifest 当作可信根。区分 HTTP 错误、旧版/错误内容、错误 MIME、跳转、过大响应、DNS/网络失败。遇首个失败即停止，不反复请求或跨域跟随。结果分别记录 `http_verified` 与 `browser_verified`；HTTP字节一致不代表浏览器功能通过。

## 本轮测试

新增26项离线/本地HTTP测试通过。真实本地HTTP服务用于校验检查器，返回成功、404、跳转、错误HTML、缺失资源、篡改字节、错误MIME和超大响应；这些是合成服务器情境，不是GitHub Pages在线结果。

新增9个 Chromium 144.0.7559.96 启动控制流场景通过：加载组件缺失、初始化异常、空壳启动、应用加载中、资源失败、执行失败、成功、超时、重复启动保护。采用注入HTML与显式脚本加载模拟，不实际获取脚本；未验证浏览器SRI执行、真实导航、原生存储、触屏设备或线上加载。

此前96项离线与40条界面检查为前次记录，本轮未将它们重复计为本轮验收。原研究代码、数据文件与既有应用功能源码未修改。

候选的八个基线文件先按实际仓库Git blob SHA核对；新构建与测试对同一组字节执行。测试证据可随本轮附件复核。

## 可复跑路径

```bash
python tools/build_release.py --output dist/release-p1.1-check
python tools/build_pages_candidate.py --source dist/release-p1.1-check/public --output dist/pages-p1.2
python -m unittest discover -s tests -p test_pages_candidate.py -v
python tools/test_pages_boot.py --candidate dist/pages-p1.2 --output boot-check.json
python tools/verify_pages.py --url https://netplus.github.io/ql/ --expected dist/pages-p1.2 --output pages-check.json
```

输出目录/报告不能覆盖既有版本。测试也接受 `QL_LEGACY_DIR` 指向逐文件校验过的既有P1.1发布目录，避免将容器恢复误称为完整项目重新构建。

## 下一项验收

需要实际保存发布源为 `Deploy from a branch / pages-ready / (root)` 并取得成功的部署记录，再进行线上HTTP字节检查及真实浏览器交互检查。此次未获得任何站点成功访问证据，不能给出“已上线”的结论。

公开站初始仍是无数据工作台；原本地样例为2026-10-08至10-15，自动日更仍未接通。发布可用性与数据更新能力是两个验收项，不能互相代替。

技术依据：
- GitHub发布源说明：<https://docs.github.com/en/enterprise-cloud@latest/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site>
- MDN SRI：<https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Subresource_Integrity>

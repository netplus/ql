# ql 执行计划：可日常使用的研究 Page

计划登记：2026-10-24。用户已同意按计划推进。基线：PR #3 / `af1ad4f6fdeda7db10a2e4a1d1fcd0a1cf3a6d15`。本轮实际读取仓库为public，has_pages=false；不能沿用早期private表述。

最终产品是固定网址上的Page，默认展示最近有效报告，收盘后形成初报并补齐；个人不必运行脚本或手动导入。文档、测试数和发布候选文件不单独构成产品完成。

## 1. 任务、依赖、完成证据

| 任务 | 优先级与依赖 | 验收门槛 | 本轮起始状态 |
|---|---|---|---|
| M1 固定网址与浏览器 #4 | P0，可与M2并行 | 成功部署SHA/run/URL，真实HTTP与浏览器加载/刷新/存储结果 | 待配置核实与真实上线，不继续重复制造发布壳 |
| M2 真实取数到页面 #5 | P0，当前实施 | 沪深各一只ETF，官方原始HTTP、字段/日期对账、有效包、私人预览；再扩池 | 单次流程本轮实施，真实网络不得用合成数据替代 |
| M3 收盘初报与自动发布 #6 | P1，依赖M1/M2/数据用途审查 | 无手动导入、缺口补跑、版本一致、失败保留、10个交易日真实记录 | 未启用日更 |
| M4 行业资金与条件观察 #7 | P1，依赖M2/M3的数据 | 21/61观察值支持20/60间隔；份额和事件准入；历史映射/广度；多端验收 | 现有产品级净值观察不等于行业资金系统 |

Issue为动态状态真源：#4 https://github.com/netplus/ql/issues/4；#5 https://github.com/netplus/ql/issues/5；#6 https://github.com/netplus/ql/issues/6；#7 https://github.com/netplus/ql/issues/7。

实施由本会话在用户推进时执行；不会在没有运行的任务/工作流下声称后台持续推进。无需每个小改动反复确认；购买、私人信息公开、改变仓库权限和未评审主线合并仍不擅自执行。任务以证据完成，不按提交数或未经验证的时间估计关闭。

## 2. 本轮实施范围

新增 `tools/run_nav_cycle.py`，连接已有采集器与通用Page：请求计划 → 有限HTTP → SHA256/原始响应重解析 → 独立日历逐日对账 → Node精确数值/协议校验 → 私人数据包与预览。缺日、陈旧、错源、正文篡改均拒绝生成合格预览；不前填，不改造前次页面，不输出伪日更数据。

`tools/collect_nav.py`仅增加真实编码、HTTP元数据和运行环境参数，避免在GitHub主机运行时仍标作工作容器。未更换来源、未增加请求频率。每次1—4产品，本次固定159995和510330，区间2026-10-08至10-23（12个已登记交易日，预期24行）；这不是“自动最新日期”，超出日历范围必须先更新日历。

公共日志仅显示状态、行数、日期、摘要和错误代码；不得显示净值、源站全文或数据预览。源站响应仅保存在该次临时运行目录，不等于长期私有证据档案。输出目录必须是新目录，保留前次证据。

## 3. 运行环境策略

优先核实既有self-hosted runner；当前GitHub连接无runner管理动作，未确认存在或可用。此阻塞不能再让取数环节只停留在当前容器DNS失败。

增加单次诊断工作流 `nav-acceptance.yml`，仅特定功能分支相关文件push触发；只读contents权限，标准ubuntu-24.04，8分钟超时、单并发；没有schedule、付费大型runner、secret、上传市场数据或Pages部署。官方说明公开仓库标准runner执行免费；不使用缓存和artifact，避免额外存储支出。

https://docs.github.com/en/actions/concepts/billing-and-usage

工作流写入/运行须以连接实测为准。如被权限拒绝，不换通道绕过限制；提交其余实现和明确阻塞。写入成功也不意味着运行成功，必须检查具体run/job结果。功能分支的单次push工作流不冒称main上的日更服务。

## 4. 测试与使用

```bash
# 默认不联网、不落盘
python tools/run_nav_cycle.py --start 2026-10-08 --end 2026-10-23
# 一次真实验收；失败非零退出，原始正文不写stdout
python tools/run_nav_cycle.py --start 2026-10-08 --end 2026-10-23 \
  --execute --output /path/to/new-private-run
python -m unittest discover -s tests -p test_nav_cycle.py -v
node --test tests/test_market_data.js
```

本轮本地新增16项单次流程测试通过；与此前恢复并核对的P0/采集测试一起，81项Python通过，32项Node通过。不是重跑仓库全部历史页面测试。成功路径使用明确合成HTML，未用作真实行情。

当前容器实际执行两请求仍为DNS失败，退出码2，没有原始HTTP、合格包或新预览。此结论不扩展为源站或GitHub运行器不可用；远端结果另记在PR/Issue。

## 5. 下阶段收口规则

M2真实成功后，再建立长期存储、增量/修订与来源权限审批，冻结小观察池；M3仅启用实际完成的数据维度。公开Page应用与可公开市场数据、私人持仓/备注分别处理。页面新数据默认加载、手动导入仅备用。日更发布必须有明确Pages部署步骤，不依赖GITHUB_TOKEN推送分支自动触发。

https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

PR #1 → #2 → #3 → 运行验收变更按依赖收口，避免长期增加互不落地草案；本轮不无审查合并。M1/M2同时受阻时，交付可复跑失败证据和最小解除动作，不新增大屏、复杂评分或重复报告。10日工程观察与投资有效性回测分别验收。

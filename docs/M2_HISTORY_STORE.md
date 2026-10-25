# M2：本地历史库、时点回放与备份恢复

2026-10-25。基于 PR #11 的 `3514d3181f166231cfcf9177c8c61245921cce2a`，关联 Issue #5、#6。

## 交付与边界

本轮将“有效数据包 → 本地历史库 → 按知识时点重建数据包 → Page数据协议”实现为可运行组件。不是再发布一个空界面，也不表示已部署用户长期服务器或接通公共日更数据。

新增 `tools/history_store.py`（Python标准库SQLite）和 `tools/history.py`。默认dry-run；写入必须显式execute并指定仓库外的目录。没有网络请求、密钥、加密上传、外部存储、定时器或Pages发布动作。没有重试此前被拦截的加密归档方案。

## 数据语义

- 保存规范化后的原始字段及来源记录；未知私人字段不入库。输入文件摘要与规范化数据包摘要分别保存；规范化包不是源站原始HTTP响应。
- 每批数据只有一次首次入库时间`known_at`，与来源`recorded_at`和`published_at`分开。今天导入十月旧样例，不声称系统十月初已知道这些值。
- 同一规范化包重复导入不增加批次/字段。不同取证批次可有重复观察，数值相同仅保留证据，不记成数值修订。
- 同源后续修订追加记录，不覆盖旧值；按cutoff回放只能使用该时点之前已入库的版本。旧取证晚入库不覆盖较新取证。
- 同一来源、同一取证时刻、同一字段出现不同值，整批拒绝。不同来源的最新有效值矛盾，快照停止，不能靠随机排序选择所谓权威值。
- 缺失不变成零，不跨日期前填。同一历史日期在后续抓取中暂时缺失，不撤销此前已知值；原始批次里的缺失仍保留。本版尚无正式撤回/作废事件模型，不能将null当作撤回声明。
- 日历由调用者提供并经现有Page协议校验，不从观察行推导。市场/币种/收益口径/分组改变会拒绝；正式行业分类历史映射仍未实现。
- 快照始终`private-review`、`auto_updated=false`；净申赎只沿用既有条件试算，正式资金准入没有放开。

## 存储与恢复

使用事务同时写入批次、字段索引和可选HTTP字节；中途失败回滚。原生SQL触发器阻止常规update/delete。目录0700、数据库0600、拒绝预先存在的符号链接和源代码目录内的数据存放；这不是对有管理员权限的攻击者或并发改变父目录的进程提供安全隔离。

原始HTTP字节必须由调用者显式提供且匹配来源摘要，才接受`raw_response_archived=true`。仅摘要不能满足归档声明。摘要验证不认证来源身份，也不替代采集器的原始响应重解析与字段对账。

备份采用SQLite在线备份API；恢复只创建新目录，不覆盖现有工作库。验证数据库完整性、外键、批次摘要、字段索引与可选原始字节摘要。备份清单用于损坏检测，不是数字签名或独立可信副本。本轮不声称异地灾备、掉电测试或用户生产恢复演练完成。

参考官方设计依据：
- https://www.sqlite.org/backup.html
- https://www.sqlite.org/lang_transaction.html

## 长历史适配

现有Page对来源记录最多64条的限制，会阻碍逐日取证积累。改为最多2048条来源，保留2MiB总大小、64产品、520日期及16384产品日期预算。新增70个独立来源的60间隔计算测试，2048/2049边界和总字节限制测试；这些是合成记录，不能当成真实60日数据。

本PR未部署生产前，线上版本仍有旧来源数量限制。当前7产品样例只有11条来源，历史库导出的该样例可被现有v3.1读取。

## 命令

以下路径是本机使用示例，不是已发现或已配置的用户服务器。父目录须先由用户/运维建立。除audit外都是写入操作；不加`--execute`只打印计划。

```sh
python tools/history.py init --store /private/ql-history --execute
python tools/history.py ingest --store /private/ql-history --input /private/market.json --execute
python tools/history.py snapshot --store /private/ql-history --calendar /private/calendar.json --codes 159995,510330 --benchmark 510330 --output /private/new-snapshot.json --execute
python tools/history.py audit --store /private/ql-history --execute
python tools/history.py backup --store /private/ql-history --output /private/new-backup --execute
python tools/history.py restore --store /private/new-backup --output /private/new-restored-store --execute
```

HTTP证据通过`--responses-dir`读取，文件名为来源SHA256加`.bin`。对现有采集作业的自动checkpoint适配、失败状态报告与长期运行目录绑定尚未完成。

## 本轮实际样例验证

使用本会话已有`ql-market-20261023.json`，没有新抓取：7产品、12个交易日、84条净值、6条历史份额、11条来源。首次入库时间2026-10-25T00:01:04.342424Z。分别启动独立进程执行初始化、导入、重复导入、快照、审计、备份、恢复与再次快照。

- 入库90个非空字段；重复导入新增0。
- 恢复后以同一knowledge cutoff重建，数据包逐字节一致，SHA256 `deb5abdc82a461bf35496c450a5f7eacc3ff5702bde61579c30e8ea9f73ead43`。
- 所有规范化数值与输入一致；截至2026-10-23净值覆盖7/7，份额覆盖0/7，未把10月15日份额前填。
- 原始HTTP响应数0；样例仍是原取证模式。数据库和真实样例未提交GitHub、未发布Pages。
- 这是当前工作容器的磁盘与进程级验收，不是用户永久服务器的留存保证。用户主机连接发现调用失败，未对用户服务器写入。

本地30项新增Python测试及35项Node测试通过。GitHub运行器的实际结果需在运行后记录，不能提前标为通过。

## 仍需收口

1. 选择实际可用的非公开持久目标，绑定采集器与历史库，验收重启、备份及失败恢复。当前没有已确认的用户服务器路径。
2. 确认来源允许的具体使用与展示范围。华夏声明 https://m.chinaamc.com/protocol/hxjjstatement.html 对资料复制、保存、分发与公开用途设有限制；本轮已读取，不推断私人保存或衍生结果自动获得授权。没有为绕过该限制而公开历史包。
3. 允许公开的快照通过独立发布审查后，再接默认索引和每日调度。当前站点market.manifest.json仍unpublished，未以合成数据填充。
4. 未来需要正式撤回事件、同来源优先级审批、历史分类映射以及更大规模分页导出，均独立评审。

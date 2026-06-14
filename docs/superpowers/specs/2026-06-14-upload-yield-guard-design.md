# PT 场景上传收益保护设计

## 背景

用户的上下行带宽都是 10M，当前目标不是单纯限制下载速度，而是保证刷流资源优先给“上传快、有收益”的种子。实际风险是：某些种子下载速度很高但上传很慢，它们会占用 qBittorrent 活跃任务、连接、磁盘 IO、缓存、做种体积和刷流新增节奏，间接影响真正上传快的种子。

在 PT 站点里，上传收益通常集中在种子加入后的最早一小段时间。进入稳定做种后，长期突然爆发的大上传种相对少，更多任务只是一般种子。因此策略不应该长时间等待普通种子翻身，而应该用短窗口快速筛掉低收益任务，同时保留少量探测名额发现少数优质种。

现有 `brushflowlowfreq` 插件已有以下能力：

- 新增刷流任务前按总上传/下载带宽、同时下载数、保种体积等条件停止新增。
- 新增任务时支持 qB 单任务上传/下载限速。
- 检查任务时支持低分享率、平均上传速度、检查间上传速度、未活动时间、动态删种等删除规则。
- 支持“分享率速度保护”和“下载保护”，避免部分场景过早删种。

但现有能力缺少一个明确的“上传收益优先调度”模块，无法专门识别和处理“高下载、低上传”的低收益任务。

## 目标

新增“上传收益保护”模块，围绕每个托管刷流任务的检查间上传/下载表现做调度：

1. 识别连续高下载但低上传的低收益刷流任务。
2. 对低收益任务先降下载限速，再暂停下载，最后可选删除。
3. 保护上传表现好的种子，不让它们被低分享率、低速或动态删种规则误伤。
4. 控制新增任务节奏，避免低收益任务稀释 qB 资源，同时保留少量探测名额，避免错过少数优质上传种。
5. 保持默认关闭，避免升级后改变用户现有行为。

## 非目标

- 不做路由器 QoS/SQM，也不承诺系统级包优先级。
- 不限制高上传种子的上传速度。
- 不把所有下载任务都视为有害；只处理“下载高且上传低”的任务。
- 不保留长时间等待窗口去赌普通种子后期翻身。
- 不影响非插件托管种子，除非未来单独增加显式开关。

## 核心概念

### 检查间速度

插件每次 `check()` 已经会记录检查间上传速度。上传收益保护需要同时记录检查间下载速度：

- `last_check_downloaded`
- `last_check_interval_downloaded`
- `last_check_interval_downspeed`
- `last_check_interval_downspeed_valid`

计算方式：

```text
interval_downspeed = (current_downloaded - last_check_downloaded) / interval_seconds
```

当检查间隔异常、下载量回退或基线缺失时，本轮不参与收益判断。

### 低收益任务

一个任务命中低收益，需要同时满足：

- 检查间下载速度 >= `yield_guard_high_download_kbs`
- 检查间上传速度 <= `yield_guard_low_upload_kbs`
- 已下载体积 >= `yield_guard_min_downloaded_gb` 或下载进度 >= `yield_guard_min_progress_percent`
- 连续命中次数 >= `yield_guard_bad_checks`

默认建议：

- 高下载阈值：`2048 KB/s`
- 低上传阈值：`200 KB/s`
- 最小已下载体积：`2 GB`
- 最小进度：`10%`
- 连续命中：`2`

低收益命中只代表“当前资源收益差”，不代表该任务永远没有价值。PT 场景下，这个信号本身就足够早，默认只给很短的缓冲时间；缓冲结束后仍低收益，就允许删除，不必等到完成。

### PT 短窗保护

为避免刚发布的少量优质种被太快淘汰，新增短窗保护：

满足任一条件的任务，可以在短窗内只降速或暂停，不直接删除：

- 发布时间很新，仍在 `yield_guard_promising_pubtime_minutes` 内。
- 刚开始有下载或上传数据，距离首次实际传输还未超过 `yield_guard_fast_fail_minutes`。
- 最近有过任意有效上传增长。

短窗到期后，如果仍然高下载低上传，就按普通低收益处理，允许最终删除。

### 高收益保护

一个任务进入高收益保护，满足任一条件即可：

- 检查间上传速度 >= `yield_guard_good_upload_kbs`
- 平均上传速度 >= `yield_guard_good_avg_upload_kbs`
- 最近窗口内有足够多次上传达标

默认建议：

- 检查间上传保护阈值：`500 KB/s`
- 平均上传保护阈值：`500 KB/s`

高收益保护只阻止“会误伤高上传种”的规则，不阻止明确安全规则：

- 不阻止失去免费即删种。
- 不阻止 H&R 专用做种时间/分享率规则。
- 不阻止用户明确配置的上传量上限。

### 可调参数原则

PT 站点差异很大，同一站点在不同时间段的 peers 行为也会变化。收益保护不把任何关键阈值写死，以下参数都必须由用户可配置：

- 判定“高下载”的下载速度阈值。
- 判定“低上传”的上传速度阈值。
- 连续命中多少次才算低收益。
- 最小已下载体积和最小下载进度。
- 快速淘汰窗口分钟数。
- 低收益后的动作链。
- 降速后的下载限速。
- 高上传保护阈值。
- 高收益池数量、探测名额和探测间隔。
- 新发布种子的短窗保护时间。

全局配置用于通用默认值，站点独立配置用于针对不同 PT 站点调优。

## 配置项

新增配置项默认关闭：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `yield_guard_enabled` | `false` | 是否开启上传收益保护 |
| `yield_guard_high_download_kbs` | `2048` | 判定高下载的检查间下载速度阈值 |
| `yield_guard_low_upload_kbs` | `200` | 判定低上传的检查间上传速度阈值 |
| `yield_guard_bad_checks` | `2` | 连续低收益命中次数 |
| `yield_guard_min_downloaded_gb` | `2` | 已下载达到多少 GB 后才处理 |
| `yield_guard_min_progress_percent` | `10` | 下载进度达到多少百分比后才处理 |
| `yield_guard_first_action` | `limit` | 首次命中后的动作：`limit` / `pause` / `delete` |
| `yield_guard_second_action` | `pause` | 降速后仍低收益的动作：`none` / `pause` / `delete` |
| `yield_guard_final_action` | `delete` | 短窗到期后仍低收益的动作：`none` / `delete` |
| `yield_guard_download_limit_kbs` | `512` | 低收益任务被降速后的下载限速 |
| `yield_guard_fast_fail_minutes` | `10` | 从首次实际传输开始，超过多少分钟仍低收益就允许最终删除 |
| `yield_guard_good_upload_kbs` | `500` | 检查间上传达到该值时保护 |
| `yield_guard_good_avg_upload_kbs` | `500` | 平均上传达到该值时保护 |
| `yield_guard_protect_delete_rules` | `true` | 上传表现好时跳过低分享率、平均低速、检查间低速、动态兜底删除 |
| `yield_guard_stop_brush_when_good_pool` | `true` | 高收益任务池足够时减少新增刷流，但仍保留探测名额 |
| `yield_guard_good_pool_min_count` | `2` | 高收益任务至少达到多少个后停止新增 |
| `yield_guard_probe_slots` | `1` | 高收益池足够时仍保留多少个低速探测下载名额 |
| `yield_guard_probe_interval_minutes` | `10` | 高收益池足够时，两次探测新增之间至少间隔多少分钟 |
| `yield_guard_promising_pubtime_minutes` | `15` | 发布时间多新以内视为短窗优先任务 |
| `yield_guard_rehearsal` | `true` | 演练模式，只记录和提醒，不执行限速/暂停/删除 |

以上数值项都必须支持全局配置和站点独立配置。默认值只作为初始建议，不代表固定策略；用户可以在后续自行摸索并调整。

## 状态字段

每个 `torrent_task` 新增：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `last_check_downloaded` | number/null | 上次检查下载量 |
| `last_check_interval_downloaded` | number/null | 检查间下载增量 |
| `last_check_interval_downspeed` | number/null | 检查间下载速度，bytes/s |
| `last_check_interval_downspeed_valid` | bool | 下载速度采样是否有效 |
| `yield_guard_bad_records` | list[int] | 最近低收益命中记录 |
| `yield_guard_bad_streak` | int | 连续低收益命中次数 |
| `yield_guard_stage` | string | `normal` / `limited` / `paused` |
| `yield_guard_last_action_time` | number/null | 最近一次保护动作时间 |
| `yield_guard_paused_time` | number/null | 被收益保护暂停的时间 |
| `yield_guard_last_probe_time` | number/null | 最近一次按探测名额新增任务的时间 |
| `yield_guard_good_protected` | bool | 最近一次检查是否被高收益保护 |
| `yield_guard_promising_protected` | bool | 最近一次检查是否被短窗保护 |
| `yield_guard_last_reason` | string | 最近一次收益判断原因 |

新增任务时初始化这些字段。存量任务首次检查时以当前数据补基线，不立即触发动作。

## 调度流程

### check 阶段

`check()` 中在 `__update_torrent_tasks_state()` 后执行收益评估：

1. 更新每个托管任务的检查间上传/下载采样。
2. 根据站点配置评估是否为高收益保护任务。
3. 根据站点配置评估是否为低收益任务。
4. 如果为高收益任务，标记保护状态。
5. 如果为低收益任务，按阶段执行动作。
6. 再进入现有删种规则。

这样现有删种规则可以读取 `yield_guard_good_protected`，跳过容易误伤的规则。

### 低收益动作

低收益动作按阶段递进：

1. `normal` 阶段命中：执行 `yield_guard_first_action`。
2. `limited` 阶段继续命中：执行 `yield_guard_second_action`。
3. `paused` 阶段不再依赖“高下载低上传”继续命中，因为暂停后下载速度会变为 0。只要距离首次实际传输已经超过 `yield_guard_fast_fail_minutes`，且上一阶段已经确认低收益，就执行 `yield_guard_final_action`，不要求任务完成。

推荐默认行为：

```text
normal -> limit download to 512 KB/s
limited -> pause torrent
after 10 minutes of real transfer and still low -> delete torrent and files
```

如果演练模式开启，只记录日志和通知，不调用 qB 修改接口。

### 恢复策略

如果任务被限速后上传表现恢复：

- 连续 `yield_guard_bad_checks` 次不再低收益，可将阶段恢复为 `normal`。
- 下载限速恢复到配置的单任务下载限速；如果原本未配置单任务下载限速，则清除限速。

如果任务被暂停：

- 默认不自动恢复，避免反复抢资源。
- 下载中的任务可以在短窗到期后最终删除，不再强制等完成。
- 暂停后的最终删除以短窗为准，而不是以完成状态为准。
- 后续可增加“低峰时段恢复”能力，但不纳入第一版。

## qBittorrent 操作

第一版优先支持 qBittorrent：

- 限速：调用 qB torrent 下载限速能力。
- 暂停：调用 qB 暂停指定 hash。
- 删除：复用现有 `delete_torrents(ids, delete_file=True)`。

如果 MoviePilot 下载器封装没有直接暴露所需接口：

- 优先使用已有 qB 客户端对象 `downloader.qbc`。
- 封装私有方法，集中处理接口不存在、调用失败和日志。
- Transmission 暂不实现暂停/限速收益保护动作，最多只做演练和删除。

## 与现有规则关系

### 新增刷流

`__evaluate_pre_conditions_for_brush()` 增加可选判断：

如果 `yield_guard_stop_brush_when_good_pool` 开启，且当前高收益活跃任务数 >= `yield_guard_good_pool_min_count`，则进入软停止：

- 普通新增任务停止。
- 如果当前探测下载数少于 `yield_guard_probe_slots`，且距离上次探测新增超过 `yield_guard_probe_interval_minutes`，仍允许新增一个任务。

这样上传池已经足够时不会持续加入新下载任务，但仍保留发现潜在优质种的机会。

### 删除规则

当 `yield_guard_good_protected` 为真且 `yield_guard_protect_delete_rules` 开启：

- 跳过最低分享率删除。
- 跳过平均上传速度过低删除。
- 跳过检查间上传速度过低删除。
- 动态删种兜底排序时优先保留。

仍然允许：

- 失去免费即删种。
- 做种时间到期。
- H&R 专用规则。
- 上传量达到上限。
- 下载超时规则，前提是任务还未完成且无上传保护。

### 动态删种

动态删种按以下优先级选择删除候选：

1. 明确命中删除规则且未受高收益保护的任务。
2. 低收益任务。
3. 未活动任务。
4. 无保护的已完成任务。
5. 高收益保护任务最后考虑，除非用户明确关闭保护。

## 通知和日志

每次收益保护动作记录：

- 站点
- 标题和副标题
- 检查间上传速度
- 检查间下载速度
- 已下载体积和进度
- 连续命中次数
- 执行动作

演练模式通知文案明确“只提醒不执行”。

## UI

在删除/保护相关配置区域新增“上传收益保护”分组。默认折叠或靠后展示，避免干扰普通配置。

核心字段优先展示：

- 开启上传收益保护
- 演练模式
- 高下载阈值
- 低上传阈值
- 连续命中次数
- 快速淘汰窗口
- 低收益动作
- 降速值
- 高上传保护阈值
- 高收益池停止新增

## 测试计划

新增单元测试覆盖：

1. 检查间下载速度采样正常计算。
2. 首次检查只补基线，不触发低收益动作。
3. 高下载低上传连续命中后进入低收益。
4. 未达到最小下载体积或进度时不处理。
5. 演练模式不调用 qB 动作。
6. 低收益任务从 normal 到 limited、paused、delete 的阶段递进。
7. 下载中的低收益任务在短窗内只允许限速或暂停，短窗到期后可以直接删除。
8. 暂停任务不会因为下载速度归零而卡住最终动作。
9. 上传恢复后从 limited 回到 normal，并恢复下载限速。
10. 高收益池足够时仍按探测名额周期性允许新增任务。
11. 高收益保护跳过低分享率、平均低速和检查间低速删除。
12. 失去免费即删种不受高收益保护阻止。
13. 站点独立配置覆盖全局收益保护配置。

## 推荐初始配置

针对 10M/10M 和 qBittorrent：

- qB 全局上传限速：`1000-1100 KB/s`
- qB 全局下载限速：`3000-5000 KB/s`
- qB 同时下载：`1-2`
- 插件单任务上传限速：留空
- 插件单任务下载限速：`1024-2048 KB/s`
- `yield_guard_enabled`: `true`
- `yield_guard_rehearsal`: `true`，先观察 24 小时
- `yield_guard_high_download_kbs`: `2048`
- `yield_guard_low_upload_kbs`: `200`
- `yield_guard_bad_checks`: `2`
- `yield_guard_download_limit_kbs`: `512`
- `yield_guard_fast_fail_minutes`: `10`
- `yield_guard_good_upload_kbs`: `500`
- `yield_guard_good_pool_min_count`: `2`
- `yield_guard_probe_slots`: `1`
- `yield_guard_probe_interval_minutes`: `10`
- `yield_guard_promising_pubtime_minutes`: `15`

演练 24 小时后，如果日志命中符合预期，再关闭演练执行真实动作。

## 风险和缓解

| 风险 | 缓解 |
| --- | --- |
| 新种刚开始下载时上传少，被误判 | 设置最小下载体积和最小进度，首次检查只补基线 |
| 快速淘汰窗口太短导致少数慢热好种被删 | 保留探测下载名额，并用发布时间/上传增长作为短窗保护信号 |
| 高收益池软停止导致错过新热门种 | 保留探测下载名额和探测间隔，不完全停止新增 |
| 部分冷门种需要先下载完成才开始上传 | 这是 PT 快速淘汰策略接受的取舍；可按站点调大 `yield_guard_fast_fail_minutes` |
| qB 接口差异导致限速/暂停失败 | 封装 qB 操作并记录失败，不影响主检查流程 |
| 高收益保护导致磁盘占用增长 | 做种时间、失去免费、上传量上限仍可生效 |
| 站点规则差异明显 | 支持站点独立配置 |

## 实施顺序

1. 增加配置解析、默认值、站点独立配置字段。
2. 增加检查间下载速度采样字段。
3. 实现收益评估纯逻辑。
4. 实现 qB 限速、暂停、恢复动作封装。
5. 将收益保护接入 `check()`。
6. 将高收益保护接入现有删除规则和动态删种排序。
7. 增加 UI 配置。
8. 更新 README、版本日志和测试。

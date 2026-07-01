# brushflowlowfreq 日志与间隔优化实施方案

> 给后续执行者：按任务逐项执行，每完成一项都要跑对应测试。不要改动与本问题无关的功能。

**目标：** 降低例行信息日志量，停止上传保护重复执行无意义的放开限速动作，新增刷流与检查的秒级自定义间隔，并让免费状态无法判断的问题可诊断但不刷屏。

**总体思路：** 保持现有单文件插件结构，只在当前插件文件和测试里做小步修改。新增秒级配置时保留旧的分钟字段兼容。日志模式只影响展示，不改变刷流、删种和上传保护判断；但上传保护重复放开限速属于真实重复动作，需要修正。

---

## 日志证据

- 重启配置快照显示 `log_mode` 为 `full`，所以重启后大量普通流程日志继续以信息级别输出是符合当前配置的，不是精简模式失效。
- 配置快照显示 `brush_interval_minutes` 为 `3`，服务启动为 `1/3 * * * *`，实际约每 3 分钟刷流一次。
- 检查服务当前固定为 150 秒。
- 配置快照显示 `auto_archive_days` 为空，所以每次检查都会输出“自动归档未配置，使用默认 7 天”。
- 配置快照显示 `upload_protection_detail_log` 为 `true`，且 `upload_protection_skip_when_downloading_le` 为 `1`。只要下载中托管任务数为 1，就会每次检查进入“小池子放开限速”分支。
- 当前代码在上传保护阶段已经是 `released` 且没有待处理动作时，仍然继续向 qB 执行 `release_limit`，这会造成重复动作和重复日志。
- 两个 `The First Jasmine` 任务已经连续 440 次无法判断免费状态，说明详情页解析规则或获取到的页面内容对这类种子不稳定。

## 涉及文件

- 修改 `plugins.v2/brushflowlowfreq/__init__.py`
  - 新增 `brush_interval_seconds` 和 `check_interval_seconds`。
  - 保留 `brush_interval_minutes` 作为兼容旧配置字段。
  - 调度逻辑改用秒级间隔。
  - 新增开启时间段状态开关，时间段为空时默认全天运行。
  - 完善精简日志分级。
  - 修正上传保护重复放开限速。
  - 增加免费状态无法判断的退避与低频诊断。
- 修改 `tests/test_brushflowlowfreq_features.py`
  - 增加配置解析、服务调度、开启时间段状态、日志压缩、上传保护重复动作、免费状态退避测试。
- 修改 `plugins.v2/brushflowlowfreq/README.md`
  - 说明秒级间隔、开启时间段状态、日志模式和推荐配置。
- 修改 `package.v2.json`
  - 增加版本说明。

## 任务一：确认日志模式与启动日志分级

- [ ] 增加测试：配置 `log_mode=concise` 时，配置快照、服务启动、普通刷流流程不应出现在信息日志中。
- [ ] 执行测试：`python -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests`
- [ ] 将服务启动等普通启动日志从直接 `logger.info` 改为走日志封装方法。
- [ ] 保留错误、警告、删种命中、上传保护真实动作等关键事件的信息日志。

## 任务二：新增秒级间隔配置

- [ ] 增加测试覆盖以下场景：
  - 空配置时刷流间隔沿用旧默认值。
  - 旧配置 `brush_interval_minutes=3` 自动换算为 180 秒。
  - 显式配置 `brush_interval_seconds=45` 时使用 45 秒。
  - 无效秒数回退到安全默认值。
  - 检查间隔默认仍是 150 秒。
- [ ] 在配置类中新增：
  - `brush_interval_seconds`
  - `check_interval_seconds`
  - 秒数解析方法，限制最小值和最大值。
- [ ] 建议默认值：
  - 刷流间隔：旧分钟字段乘以 60，缺省时 600 秒。
  - 检查间隔：150 秒。
  - 最小值建议 10 秒，但文档建议实际使用不要低于 60 秒。

## 任务三：调度逻辑改为秒级

- [ ] 增加测试：`get_service()` 返回的刷流服务使用 `seconds` 间隔。
- [ ] 增加测试：检查服务使用 `check_interval_seconds`。
- [ ] 修改刷流服务注册：
  - 使用间隔触发器。
  - 参数为 `{"seconds": brush_config.brush_interval_seconds}`。
- [ ] 修改检查服务注册：
  - 参数为 `{"seconds": brush_config.check_interval_seconds}`。
- [ ] 继续保留 `active_time_range` 控制运行时段。
- [ ] 对旧 `cron` 字段做兼容处理：不再用它重写分钟周期；如果继续保留，建议只作为粗略运行窗口说明，真正秒级周期由新字段控制。

## 任务四：新增开启时间段状态设置

- [ ] 增加配置字段：
  - `active_time_range_enabled`
  - 默认值建议为 `false`，表示不限制运行时段。
- [ ] 保留现有 `active_time_range` 字段作为具体时间范围。
- [ ] 增加测试覆盖以下场景：
  - `active_time_range_enabled=false` 且 `active_time_range` 为空时，刷流默认全天允许运行。
  - `active_time_range_enabled=true` 且 `active_time_range` 为空时，也按全天允许运行，并记录调试级提示，不阻断刷流。
  - `active_time_range_enabled=true` 且时间段有效时，只在指定时间段内运行。
  - `active_time_range_enabled=true` 且时间段格式无效时，按全天允许运行，并输出警告或配置校验提示。
- [ ] 修改时间段判断逻辑：
  - 未启用状态开关：直接返回允许运行。
  - 启用状态开关但未填写时间段：返回允许运行，语义为全天。
  - 启用状态开关且填写有效时间段：按原时间段判断。
- [ ] 配置界面增加“启用开启时间段”开关。
- [ ] “开启时间段”输入框文案补充：留空默认全天。
- [ ] 配置写回增加 `active_time_range_enabled`，避免重启后状态丢失。

## 任务五：修正上传保护重复放开限速

- [ ] 增加测试：当任务状态为 `released` 且没有待处理动作时，小池子例外分支不应再次调用 qB。
- [ ] 当前逻辑是：阶段在 `limited`、`strict_limited`、`released` 或存在待处理动作时执行放开限速。
- [ ] 修改为：只有阶段在 `limited`、`strict_limited` 或存在待处理动作时才执行放开限速。
- [ ] 保留状态重置和最近原因更新。
- [ ] 精简日志下把“已经是放开状态”的记录降为调试日志或不输出。

## 任务六：免费状态无法判断的退避与诊断

- [ ] 增加测试：连续无法判断免费状态时不触发删除。
- [ ] 增加测试：连续失败后不会每 150 秒请求详情页。
- [ ] 增加测试：信息日志只在首次、少数关键次数、固定里程碑输出。
- [ ] 为任务记录新增字段：
  - `free_undetermined_count`
  - `free_undetermined_last_log_at`
  - `free_undetermined_next_check_at`
  - `free_undetermined_last_reason`
- [ ] 建议策略：
  - 前 3 次照常检查。
  - 之后至少间隔 30 分钟再重试详情页。
  - 第 1、3、10、50、100 次输出信息日志，之后每 100 次输出一次。
  - 其他重复情况在完整日志下可调试输出，精简日志下不输出。
- [ ] 增加安全诊断，不输出完整页面内容，只记录：
  - 页面长度。
  - 是否命中详情页特征。
  - 是否命中登录或验证页特征。
  - 解析失败原因。

## 任务七：界面、文档和版本

- [ ] 配置界面新增“刷流间隔（秒）”。
- [ ] 配置界面新增“检查间隔（秒）”。
- [ ] 配置界面新增“启用开启时间段”开关。
- [ ] “开启时间段”输入提示改为：如 `00:00-08:00`，留空默认全天。
- [ ] 旧“新增种子间隔（分钟）”保留兼容或迁移为隐藏字段。
- [ ] 配置写回增加：
  - `brush_interval_seconds`
  - `check_interval_seconds`
  - `active_time_range_enabled`
- [ ] 文档写明推荐值：
  - 刷流间隔建议 180 到 600 秒。
  - 检查间隔建议 150 到 300 秒。
  - 开启时间段未启用或时间段为空时，默认全天运行。
  - 不建议对 PT 站点使用过低间隔，避免请求压力过高。
  - `auto_archive_days` 建议显式填 7。
  - 日志模式建议使用精简日志。
- [ ] 更新版本说明。

## 最终验证

- [ ] 执行语法检查：
  - `python3 -m py_compile plugins.v2/brushflowlowfreq/__init__.py`
- [ ] 执行完整测试：
  - `python -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests`
- [ ] 人工验证重启日志：
  - 配置快照中 `log_mode` 应为 `concise`。
  - 服务启动日志应显示秒级间隔。
  - 未填写开启时间段时应默认全天运行。
  - 启用开启时间段并填写有效范围时，应只在范围内刷流。
  - 不应每轮输出“已释放状态再次执行放开限速”。
  - 两个无法判断免费状态的任务不应每轮刷屏。

## 代码改动前的临时配置建议

- 把日志模式改成精简日志，并确认下一次配置快照里 `log_mode` 是 `concise`。
- 把自动归档记录天数显式填为 7。
- 暂时关闭上传保护详细日志，除非正在调试上传保护。
- 如果继续保留“下载中任务数小于等于 1 时跳过上传保护”，在修复前仍会进入小池子例外分支。
- 如果两个 `The First Jasmine` 任务已经不需要继续监控，可以手动处理掉，避免继续触发免费状态无法判断检查。

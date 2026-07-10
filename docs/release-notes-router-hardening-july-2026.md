# Router Explicit Declaration Hardening
## (July 2026)

---

## 一、背景

此前普通工程请求可能因为以下模式被**错误识别**为显式 Heavy Mode 声明：

| 误触发模式 | 示例 |
|---|---|
| 否定句 | `不需要 research` |
| Markdown fenced code | <code>\`\`\`mode: research\`\`\`</code> |
| inline code | <code>\`research mode\`</code> |
| Markdown quote | `> mode = research` |
| 普通日志 | `[INFO] switching to research mode` |
| 普通代码片段 | `if mode == "research":` |
| key=value 日志字段 | `mode=research` (在日志行中) |
| traceback | 包含 `mode: research` 的异常输出 |
| diagnostic output | 错误诊断中的模式引用 |

这些误判导致普通工程修复被意外路由至 RESEARCH/DECISION task engine，引发意料之外的执行路径和资源消耗。

---

## 二、本轮修复时间线

| 序号 | Commit | 日期 (UTC+8) | 作用 |
|---|---|---|---|
| 1 | `189c3484e` | 2026-07-10 13:33 | **fix(routing): add explicit-affirmative declaration filter with rich diagnostics** — 引入显式声明检测框架，实现否定句过滤、Markdown fence/inline code/quote 过滤，以及全面的诊断信息输出。 |
| 2 | `3eb846ab9` | 2026-07-10 13:49 | **fix(task-engine): complete passive guard debug integration** — 将显式声明检测的诊断信息接入 Passive Guard 调试系统，使门控决策可观测。 |
| 3 | `6e29f27f6` | 2026-07-10 14:09 | **fix(routing): ignore log-style mode contexts** — 新增 key-value 日志字段过滤和纯文本日志/代码段过滤，消除日志和代码片段中的模式值误判。 |

---

## 三、本轮新增能力

| 过滤器 | 引入 Commit | 说明 |
|---|---|---|
| **Negation filter** | `189c3484e` | 检测否定句式（不含、不要、不是 / not、no、without），排除其后的模式关键词。 |
| **Markdown fence filter** | `189c3484e` | 排除 fenced code block 内部的所有文本。 |
| **Inline code filter** | `189c3484e` | 排除反引号内的文本。 |
| **Quote filter** | `189c3484e` | 排除 blockquote 行。 |
| **Key-value context filter** | `6e29f27f6` | 识别已知日志字段（`mode`、`task_mode`、`detected_mode`、`selected_mode`、`route_mode`）的 `key=value` 或 `key: value` 赋值，排除其模式值。 |
| **Plaintext log/code context filter** | `6e29f27f6` | 识别引导语后的日志或代码段，包括引导语（`错误日志`、`error log`、`traceback`、`以下是代码`、`diagnostic output` 等）和后续的日志/代码结构。 |
| **Rich diagnostics** | `189c3484e` | 每次检测输出详细的匹配原因、行列表、触发值，支持调试和门控审计。 |
| **Passive guard debug integration** | `3eb846ab9` | 诊断信息透传至 Passive Guard 调试面板，运维可直接查看门控决策路径。 |

---

## 四、诊断字段

本轮新增的诊断字段：

- **`filtered_by_key_value_context`** — 标记检测到的模式值来源于已知日志字段（`mode=`、`task_mode:` 等）的 key-value 赋值，因此被排除出显式声明检测。
- **`filtered_by_plaintext_log_or_code_context`** — 标记检测到的模式值位于引导语（如 `以下是错误日志`、`traceback`）之后的日志/代码结构中，因此被排除出显式声明检测。

这两个字段与已有字段配合使用：

| 诊断字段 | 含义 |
|---|---|
| `matched_keywords` | 触发检测的模式关键词列表 |
| `matched_lines` | 触发检测的原始行 |
| `line_count` | 匹配行数指示 |
| `filtered_by_negation` | 被否定句排除 |
| `filtered_by_fence` | 被 fenced code block 排除 |
| `filtered_by_inline_code` | 被 inline code 排除 |
| `filtered_by_quote` | 被 blockquote 排除 |
| `filtered_by_key_value_context` | 被日志字段赋值排除 |
| `filtered_by_plaintext_log_or_code_context` | 被纯文本日志/代码段排除 |

---

## 五、验证结果

| 测试套件 | 结果 |
|---|---|
| 针对性单元测试 (test_task_engine_contracts.py) | **69/69 PASS** |
| Acceptance Smoke (test_url_routing_guardrails.py) | **20/20 PASS** |
| Video Summary Direct Routing 回归 (test_video_report_passthrough.py) | **20/20 PASS** |
| Video Report Passthrough 回归 (test_video_report_tool.py) | **12/12 PASS** |
| Handler signature 一致 | **PASS** |

全部 121 项测试通过，零回归。

---

## 六、已知限制

1. **目前仍只识别正式显式声明。** 检测不会对普通文本中的偶然关键词（如对话中的 "research"、"decision" 等非声明性引用）做出反应。这是预期行为，并非缺陷。
2. **不要依赖普通文本中的偶然关键词进入 Heavy Mode。** 用户必须使用明确的肯定肯定句式（如 "使用 research 模式"、"run in decision mode"）才能触发显式声明检测。
3. 日志上下文过滤器依赖固定的引导语列表和字段名白名单。如果日志格式或字段命名发生变化，可能需要更新引导语集合。
4. 纯文本日志/代码段过滤器在连续多段日志之间（退出后用自然语言分隔再重新进入日志段）可能产生边界误判，但该场景在实际使用中极为罕见。

---

## 七、后续建议

1. **任何新的显式声明规则都必须增加：**
   - 单元测试（test_task_engine_contracts.py）
   - Acceptance Smoke 样本（test_url_routing_guardrails.py）
   - 回归测试（video summary / report passthrough）

2. **禁止再次回到简单 substring 匹配。** 所有模式识别必须经过至少一道上下文过滤器，防止日志、代码段、引用内容被误判为声明。

3. 建议将引导语表（引导语集合）提取为模块级常量或配置，便于后续扩展。

4. 未来可考虑引入机器学习辅助的声明意图分类，进一步提高精度，但当前基于规则的方案已满足需求。

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time


_PROMISE_RE = re.compile(
    r"("
    r"(完成|处理|执行|安装|跑完|结束|有结果|出结果|完成后|处理完|安装完|跑完后).{0,24}(告知|告诉|通知|提醒|回报|反馈)"
    r"|"
    r"(我会|我将|会).{0,20}(告知|告诉|通知|提醒|回报|反馈).{0,24}(结果|完成|进度|状态)"
    r"|"
    r"(I'll|I will).{0,40}(notify|tell|update).{0,40}(when|once|after|result|complete)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_BACKED_RE = re.compile(
    r"("
    r"notify_on_complete|watch_patterns|watcher|automation|cronjob|check_interval"
    r"|\.status\.json|\.result\.json|\.result\.md|handoff_status_path|handoff_result_path"
    r"|process\(action=['\"](?:poll|wait|log)['\"]|/background|background=true"
    r")",
    re.IGNORECASE,
)

_MANUAL_FALLBACK_RE = re.compile(
    r"(打开\s*Terminal(?:\.app)?[^。\n]*(?:粘贴|回车)|"
    r"打开\s*终端[^。\n]*(?:粘贴|回车)|"
    r"请\s*(?:在)?\s*(?:Terminal(?:\.app)?|终端)\s*(?:执行|跑)[^。\n]*|"
    r"请\s*(?:在)?\s*(?:Terminal(?:\.app)?|终端)\s*(?:执行|跑)[^。\n]*|"
    r"请\s*(?:在)?\s*(?:Terminal(?:\.app)?|终端)\s*(?:执行|跑)[^。\n]*|"
    r"请\s*(?:在)?\s*(?:Terminal(?:\.app)?|终端)\s*(?:执行|跑)[^。\n]*(?:brew|launchctl|sudo|rm\s|mv\s|rsync|rclone|scp)|"
    r"你(?:自己|手动)?(?:跑|执行|粘贴)[^。\n]*(?:brew|launchctl|sudo|rm\s|mv\s|rsync|rclone|scp)|"
    r"直接给你终端命令跑一下)",
    re.IGNORECASE,
)

_HIGH_SIDE_EFFECT_COMMAND_RE = re.compile(
    r"\b(brew\s+(install|upgrade|uninstall|tap)|launchctl\s+(kickstart|bootstrap|bootout|load|unload|enable|disable)|sudo\b|rm\s+-|rsync\b|rclone\b|scp\b)",
    re.IGNORECASE,
)

_MANUAL_FALLBACK_OK_RE = re.compile(
    r"(人工兜底|manual fallback).{0,40}(可选|确认|选择|如果你愿意|如果你明确)",
    re.IGNORECASE | re.DOTALL,
)

_MANUAL_VERIFICATION_RE = re.compile(
    r"("
    r"(验证一下|验证一下——|你用这条|跑一下告诉我|试一下|测试一下).{0,80}(命令|脚本|CDP|browser|浏览器|标签页|Space|焦点|拖到)"
    r"|"
    r"(CDP\s*命令|webSocketDebuggerUrl|Target\.createTarget|openclaw\s+browser\s+open|NSWorkspace\.openURL|wrapper|清理命令缓存|设成可执行|hash\s+-r|claw-open-bg|openc-guardian|openc\s+alias|同步更新\s*openc|完整重启生效|Chrome\s+Canary|DownloadBubble|下载通知|启动\s*flags|source\s+~/.zshrc|pkill|执行权限|权限丢了|终端通道卡在\s*Codex|你跑这条)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_MANUAL_VERIFICATION_PAYLOAD_RE = re.compile(
    r"("
    r"```(?:bash|sh|python)?[\s\S]{80,}?```"
    r"|curl\s+-s\s+http://127\.0\.0\.1:\d+/(?:json|json/version)"
    r"|python3?\s+-c\s+"
    r"|websockets\.connect"
    r"|Target\.createTarget"
    r"|openclaw\s+browser\s+open"
    r"|chmod\s+\+x\s+[^`\n]*(?:openclaw|claw-open-bg|openc-guardian)"
    r"|hash\s+-r"
    r"|sed\s+-i\s+[^`\n]*~/.zshrc"
    r"|source\s+~/.zshrc"
    r"|pkill\s+-f\s+[^`\n]*Google\s+Chrome\s+Canary"
    r"|--disable-features=DownloadBubble"
    r"|--disable-download-notification"
    r"|\[wrapper\]\s+CDP\s+background\s+open"
    r")",
    re.IGNORECASE,
)

_MANUAL_VERIFICATION_OK_RE = re.compile(
    r"(需要你观察|请你观察|肉眼观察|观察是否).{0,60}(Space|焦点|跳转|拖过去|切换)",
    re.IGNORECASE | re.DOTALL,
)


_BOUNDARY_BYPASS_RE = re.compile(
    r"(被边界策略拦截|边界策略连简单的\s*ls\s*都拦|工具边界在拦截).{0,180}"
    r"(换条路|search_files|read_file|继续拉取|绕过|用别的工具)",
    re.IGNORECASE | re.DOTALL,
)

_BOUNDARY_APPEND_BYPASS_RE = re.compile(
    r"("
    r"(heredoc|write_file|追加|append|standalone\s+Python\s+script|Python\s+script).{0,180}"
    r"(被拦截|blocked|boundary|边界).{0,260}"
    r"(换方式|different\s+approach|read\s+the\s+complete\s+file|read_file|读全文件|write\s+the\s+entire|write\s+it\s+all\s+back|一次性写回|整体写回|overwrite)"
    r"|"
    r"(每次追加都被拦截|Again\s+blocked|Every\s+approach\s+to\s+append).{0,260}"
    r"(read_file|读全文件|write_file|整体写回|一次性写回|complete\s+file)"
    r"|"
    r"(卡的原因|根因|循环路径|应该做的|正确方式|现在立即).{0,420}"
    r"(boundary\s*policy|boundary|边界).{0,420}"
    r"(read_file\s*\+\s*write_file|读全文件\s*\+\s*write_file|write_file\s*(?:写回|全量写回)|一枪搞定|全量写回|完整文件)"
    r"|"
    r"(write_file\s*工具本身是通的|write_file\s*本身是通的).{0,260}"
    r"(读全文件|全量写回|写回|一枪搞定)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_BOUNDARY_APPEND_BYPASS_CORRECTION = (
    "边界追加/整体写回说明：文件追加或写入被 boundary 拦截后，不能通过 heredoc、standalone 脚本、"
    "读全文件再整体 write_file 覆盖来绕过。写文章/报告应使用正常 file/document 工具；"
    "如果边界误拦，必须报告具体 path、tool、reason 并标为 pending/blocked，避免整文件覆盖造成内容丢失。"
)


_CODEX_PAUSE_CONTINUE_RE = re.compile(
    r"(__codex_pause|raw\.__codex_pause|data/raw\.__codex_pause).{0,120}"
    r"(继续|拉取|交叉比对|完整数据|处理|扫描)",
    re.IGNORECASE | re.DOTALL,
)

_UNVERIFIED_DELETE_CONFIRMATION_RE = re.compile(
    r"(Downloads|LP_Books|下载|新书|书籍|源文件).{0,120}"
    r"(可以删|放心删|删了吧|全部都已经入库|都已经入库|全入库)",
    re.IGNORECASE | re.DOTALL,
)

_DELETE_VERIFICATION_EVIDENCE_RE = re.compile(
    r"(核验完成|交叉核验完成|verified|manifest|LanceDB|chunk.{0,20}存在|source_count|row_count|入库清单|证据)",
    re.IGNORECASE | re.DOTALL,
)

_BOUNDARY_BYPASS_CORRECTION = (
    "边界绕行说明：边界拦截后不能换用 search_files/read_file 等工具绕过同一受限操作。"
    "应按边界 route/handoff 处理，或明确报告阻塞和下一步。"
)

_CODEX_PAUSE_CORRECTION = (
    "Codex 暂停目录说明：检测到 `.__codex_pause` / `raw.__codex_pause` 这类暂停标记时，"
    "不能继续拉取或据此下结论；必须先确认后台/Codex 状态。"
)

_DELETE_VERIFICATION_CORRECTION = (
    "删前验库说明：在源文件清单、chunk 文件、LanceDB/source count 没有完成交叉核验前，"
    "不能确认“都已入库”或建议删除 Downloads/LP_Books 里的书。当前只能标为 pending 或 route:codex。"
)


_ORPHAN_HANDOFF_RE = re.compile(
    r"("
    r"Codex\s*后台进程没返回结果"
    r"|Handoff\s*请求已写入.{0,80}(bridge|目录)"
    r"|\.READY.{0,40}(被边界拦|缺|没有|不触发)"
    r"|bridge.{0,60}(没捡|未捡|还没处理|无响应|不触发)"
    r"|Bridge.{0,80}(崩了|崩溃|FileNotFoundError|无法捡)"
    r"|无法捡\s*handoff"
    r"|还没处理.{0,40}(bridge|请求|handoff)"
    r"|等\s*10\s*秒后检查结果"
    r"|3-10\s*秒内捡起来处理"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_BROKEN_BRIDGE_NESTED_HANDOFF_RE = re.compile(
    r"(Bridge|bridge).{0,80}(崩了|崩溃|无法捡|FileNotFoundError).{0,160}"
    r"(走\s*Codex\s*handoff|handoff\s*来重启|交给\s*Codex\s*重启|直接用\s*codex\s*exec\s*重启)",
    re.IGNORECASE | re.DOTALL,
)

_ORPHAN_HANDOFF_CORRECTION = (
    "Handoff 状态说明：写入 request 但没有 `.READY`、没有 bridge 消费、没有 result/status 回执，"
    "或 bridge 已崩溃时，任务只能算 pending/blocked，不能说已经交付或让用户等待。Hermes 必须报告缺失的触发/回执和下一步修复动作。"
)

_BROKEN_BRIDGE_CORRECTION = (
    "Bridge 崩溃说明：已知 bridge 崩溃时，不能再通过同一个 bridge handoff 去重启 bridge。"
    "只能使用已确认可用的直接通道同步修复，或把任务标为 blocked 并说明需要先恢复 bridge。"
)


_DATA_PIPELINE_MANUAL_RE = re.compile(
    r"("
    r"(OCR|parse_ocr\.py|parse_extract\.py|embed_remaining\.py|rechunk_parallel|AA\s*fast\s*download|AA\s*.*下载|MOBI\s*伪\s*PDF|下载替换|入库|向量|嵌入).{0,180}"
    r"(Terminal\.app|手动跑|你.*跑|需要你|等\s*boundary\s*解封|被\s*boundary\s*拦截|被边界.*拦截)"
    r"|"
    r"(Terminal\.app|手动跑|你.*跑|需要你).{0,120}"
    r"(parse_ocr\.py|parse_extract\.py|embed_remaining\.py|rechunk_parallel|AA\s*fast\s*download)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_DATA_PIPELINE_COMMAND_RE = re.compile(
    r"(cd\s+~/Workspace/AI_Core/lp-knowledge|/opt/homebrew/Caskroom/miniforge/base/bin/python3?\s+|python3?\s+)"
    r".{0,120}(parse_ocr\.py|parse_extract\.py|embed_remaining\.py|rechunk_parallel)",
    re.IGNORECASE | re.DOTALL,
)

_DATA_PIPELINE_MANUAL_CORRECTION = (
    "数据管道边界说明：OCR/parse/embed/AA下载替换这类 LP 数据管道任务被边界拦截时，"
    "不能要求用户在 Terminal 手动跑命令。Hermes 应 route:codex、使用已批准执行通道，或把任务标为 pending/blocked 并说明缺口。"
)


_EXPLICIT_MANUAL_MODE_RE = re.compile(
    r"(人工执行模式|人工兜底|manual fallback).{0,100}(已确认|你明确|你已确认|按你要求|用户明确)",
    re.IGNORECASE | re.DOTALL,
)

_DEGRADED_LONG_SCRIPT_RE = re.compile(
    r"("
    r"(Codex|bridge|Bridge|终端).{0,160}(额度耗尽|usage limit|out of credits|不可用|被边界拦截|全被边界拦截|沙箱限在|sandbox|写不了|死|崩)"
    r".{0,220}(只能给你|手工跑|手动兜底|保存到\s*/tmp|把下面保存|Terminal\.app|复制粘贴)"
    r"|"
    r"(把下面保存到|保存到\s*/tmp|一个脚本搞定|self-contained script).{0,180}(python3|#!/usr/bin/env|OpenClaw|openclaw|curl)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_LONG_SCRIPT_PAYLOAD_RE = re.compile(
    r"(#!/usr/bin/env\s+python3|python3\s+/tmp/|python3\s+<<|cat\s+>\s*/tmp/|BOOKS\s*=\s*\[|openclaw\s+browser\s+open|subprocess\.run|curl\s+MD5|lp_download_22\.py|PYEOF|ast\.parse|open\(f,\s*['\"]w['\"]\))",
    re.IGNORECASE | re.DOTALL,
)

_ENGINEERING_MANUAL_PATCH_RE = re.compile(
    r"("
    r"(Codex|patch|边界).{0,160}(额度用尽|usage limit|被拦|不可用).{0,220}(hermes-agent|conversation_loop\.py|Terminal\.app|你.*跑|手动|就修好)"
    r"|"
    r"(cd\s+~/Workspace/AI_Core/hermes-agent|agent/conversation_loop\.py|open\(f,?['\"]?w|c\s*=\s*c\.replace)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_BROWSER_SYSTEM_CONFIG_RE = re.compile(
    r"("
    r"LSUIElement|defaults\s+write\s+com\.google\.Chrome\.canary"
    r"|~/.local/bin/cdp-silent-dl"
    r"|macOS\s*系统级|后台应用模式"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_INCOMPLETE_VERIFICATION_RE = re.compile(
    r"(Still\s+blocked|仍然被拦|验证.*被拦|terminal.*blocked).{0,180}(read_file|spot-check|抽查|one\s+is\s+good|先读一个)",
    re.IGNORECASE | re.DOTALL,
)

_DEGRADED_LONG_SCRIPT_CORRECTION = (
    "降级人工执行说明：Codex/bridge/terminal 不可用时，任务应先标为 pending/blocked。"
    "Hermes 不能默认甩长脚本给用户；只有用户明确选择“人工执行模式”后，才可给最少命令、风险说明和验证步骤。"
)

_ENGINEERING_MANUAL_PATCH_CORRECTION = (
    "工程补丁降级说明：工程代码改动在 Codex 额度耗尽或 patch 被边界拦截时，默认应 pending/blocked，"
    "不能直接给用户 python -c/sed 写文件命令；除非用户明确要求人工 patch。"
)

_BROWSER_SYSTEM_CONFIG_CORRECTION = (
    "浏览器系统设置说明：defaults/LSUIElement、Chrome Canary 启动 flags、进程重启、静默下载配置等系统级修复，"
    "应由 Hermes/Codex 执行或进入明确的人工执行模式，不能默认让用户粘贴命令。"
)

_INCOMPLETE_VERIFICATION_CORRECTION = (
    "验证完整性说明：终端核验被拦后，只用 read_file/spot-check 抽查不能证明整批完成；"
    "必须报告为部分验证/pending，或走完整核验通道。"
)


_TMP_DOC_MANUAL_EDIT_RE = re.compile(
    r"("
    r"(State\s+report|状态报告|文件.*(?:完成|complete)|/tmp/[^\\s`]+\\.md|临时文档).{0,500}"
    r"(重复|duplicate|重复章节|重复.*header|##\\s*7\\s*前沿热点).{0,500}"
    r"(所有修改工具.*(?:boundary|边界|拦截)|modification\\s+tools.*blocked|工具.*被.*拦).{0,500}"
    r"(手动打开|手动.*搜索|你可以手动|删掉|删除第一个|要继续吗)"
    r"|"
    r"(所有修改工具.*(?:boundary|边界|拦截)|modification\\s+tools.*blocked|工具.*被.*拦).{0,500}"
    r"(/tmp/[^\\s`]+\\.md|临时文档|文档).{0,500}"
    r"(手动打开|手动.*搜索|你可以手动|删掉|删除第一个|要继续吗)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_TMP_DOC_MANUAL_EDIT_CORRECTION = (
    "临时文档编辑说明：/tmp 下的非工程文档编辑、去重、章节清理应由 Hermes 使用正常 file/document 工具完成，"
    "不能在工具被拦后让用户手动打开文件搜索和删除段落。若某个工具真的被 boundary 拦截，必须报告具体 "
    "tool/path/reason，并把任务标为 pending/blocked；不能把手工编辑当成默认下一步。"
)


_SECRET_OR_KEY_MANUAL_RE = re.compile(
    r"("
    r"(cat|grep|rg|sed|awk|head|tail|less|more)\s+[^\n`]*~/?\.hermes/\.env"
    r"|echo\s+\$?\{?(OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER_API_KEY)\}?"
    r"|printenv\s+(OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER_API_KEY)"
    r"|从源文件读准确的|API key 被截断了|key 被截断"
    r"|(?:read|load|读取|读|拿|取).{0,80}(?:OPENAI|GEMINI|GOOGLE|OPENROUTER|sk-|sk-or-|AIza|外部).{0,100}(?:config|配置|yaml|\.env|key|api_key)"
    r"|(?:config|yaml|\.env).{0,100}(?:OPENAI|GEMINI|GOOGLE|OPENROUTER|sk-|sk-or-|AIza|外部).{0,100}(?:key|api_key|curl|test|测试|验证)?"
    r"|sk-[A-Za-z0-9_-]{8,}|sk-or-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{8,}"
    r")",
    re.IGNORECASE | re.DOTALL,
)


_LOCAL_OMLX_KEY_BUREAUCRACY_RE = re.compile(
    r"("
    r"(OMLX|本地模型|local\s+model|omlx-).{0,260}"
    r"(运行时读取\s*key|读取\s*key\s*的脚本|script.{0,80}key|model_switcher\.py|Memory\s*满了|不管|execute_code.{0,120}(?:Codex|路由|blocked|拦)|换个思路.{0,80}terminal|terminal\s+block.{0,80}key)"
    r"|"
    r"(运行时读取\s*key|读取\s*key\s*的脚本|script.{0,80}key|model_switcher\.py|Memory\s*满了|不管|execute_code.{0,120}(?:Codex|路由|blocked|拦)|换个思路.{0,80}terminal|terminal\s+block.{0,80}key).{0,260}"
    r"(OMLX|本地模型|local\s+model|omlx-)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_LOCAL_MODEL_BENCHMARK_SPLIT_BYPASS_RE = re.compile(
    r"("
    r"(整夜|overnight|后台|不打扰|模型测试|model\s+benchmark|chat\s+API).{0,320}"
    r"(Terminal\s+blocked|terminal\s+blocked|被判为工程代码|工程代码|30KB|大脚本|脚本).{0,320}"
    r"(换个思路|小脚本|逐个模型|先验证|chat\s+API|拆)"
    r"|"
    r"(Terminal\s+blocked|terminal\s+blocked|被判为工程代码|工程代码|30KB|大脚本|脚本).{0,320}"
    r"(换个思路|小脚本|逐个模型|先验证|chat\s+API|拆).{0,320}"
    r"(整夜|overnight|后台|不打扰|模型测试|model\s+benchmark)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_LOCAL_OMLX_KEY_BUREAUCRACY_CORRECTION = (
    "本地 OMLX key 规则：OMLX/LOCAL_LLM 是本机网关管理凭证，不按外部 OpenAI/Gemini/OpenRouter key 处理。"
    "用户明确提供或允许使用本地 OMLX key 时，Hermes 应直接用于 localhost/127.0.0.1 的模型 "
    "health/models/load/unload/chat/embeddings/admin/test 调用；不能因为 key 明文、memory 满、或某个工具被拦，"
    "再去写脚本读 config/settings、绕到 execute_code、路由 Codex、或在 terminal/execute_code 之间打转。"
)

_LOCAL_MODEL_BENCHMARK_SPLIT_BYPASS_CORRECTION = (
    "本地模型长测说明：整夜/后台模型测试必须先创建可追踪执行机制，例如 pid、log_path、status_path、result_path "
    "或 notify_on_complete；否则不能承诺“后台运行/不打扰你”。如果 30KB 长脚本被 boundary 判为工程代码，"
    "不能改成小脚本逐个模型绕过同一限制。正确做法是使用已批准的 local-model benchmark runner，"
    "或报告具体 tool/path/reason 并标为 pending/blocked。"
)


_LOCAL_MODEL_AUTH_OVERCLAIM_RE = re.compile(
    r"("
    r"(404|model\s+not\s+found|模型.{0,12}(?:不存在|未找到)).{0,240}"
    r"(key\s*(?:已|已经)?生效|认了\s*key|认证(?:已)?通过|auth(?:entication)?\s*(?:ok|passed|success))"
    r"|"
    r"(key\s*(?:已|已经)?生效|认了\s*key|认证(?:已)?通过|auth(?:entication)?\s*(?:ok|passed|success)).{0,240}"
    r"(404|model\s+not\s+found|模型.{0,12}(?:不存在|未找到))"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_LOCAL_MODEL_AUTH_OVERCLAIM_CORRECTION = (
    "本地模型验证说明：`404 model not found` 只能说明请求到达了模型服务并暴露了模型名/加载问题，"
    "不能单独证明 key 已经生效或认证通过。正确下一步是用不泄露真实 key 的后端安全通道检查"
    "模型列表、当前加载模型和 auxiliary 配置；如果当前工具通道无法访问 localhost，只能报告该通道无法验证。"
)


_LOCAL_MODEL_AUTH_OVERCLAIM_RE = re.compile(
    r"("
    r"(404|model\s+not\s+found|模型.{0,12}(?:不存在|未找到)).{0,240}"
    r"(key\s*(?:已|已经)?生效|认了\s*key|认证(?:已)?通过|auth(?:entication)?\s*(?:ok|passed|success))"
    r"|"
    r"(key\s*(?:已|已经)?生效|认了\s*key|认证(?:已)?通过|auth(?:entication)?\s*(?:ok|passed|success)).{0,240}"
    r"(404|model\s+not\s+found|模型.{0,12}(?:不存在|未找到))"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_LOCAL_MODEL_AUTH_OVERCLAIM_CORRECTION = (
    "本地模型验证说明：`404 model not found` 只能说明请求到达了模型服务并暴露了模型名/加载问题，"
    "不能单独证明认证通过。正确下一步是用不泄露真实 key 的后端安全通道检查"
    "模型列表、当前加载模型和 auxiliary 配置；如果当前工具通道无法访问 localhost，只能报告该通道无法验证。"
)


_LOCAL_MODEL_MISSING_AUTH_RE = re.compile(
    r"("
    r"(API\s+key\s+required|authentication_error|缺\s*key|missing\s+auth(?:entication)?).{0,1200}"
    r"(127\.0\.0\.1|localhost|OMLX|本地模型|/v1/chat/completions|/admin/api/models|/v1/models|模型目录|文件系统信息建队列)"
    r"|"
    r"(127\.0\.0\.1|localhost|OMLX|本地模型|/v1/chat/completions|/admin/api/models|/v1/models|跳过被拦的\s*/admin/api/models|文件系统信息建队列).{0,1200}"
    r"(API\s+key\s+required|authentication_error|缺\s*key|missing\s+auth(?:entication)?)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_LOCAL_MODEL_MISSING_AUTH_CORRECTION = (
    "本地模型鉴权说明：`API key required` / `authentication_error` 不是边界问题，"
    "也不是改用文件系统模型目录、跳过 `/admin/api/models`、或路由 Codex 的理由。"
    "Hermes 已被允许使用本地 OMLX key；应在同一个 localhost/127.0.0.1 请求上补 "
    "`Authorization: Bearer <local OMLX key>` 或 `OMLX_KEY` 后重试。"
)

_SECRET_OR_KEY_CORRECTION = (
    "密钥处理说明：OpenAI/Gemini/Google/OpenRouter 等外部 API key 不能读取、打印、cat、echo、日志记录、handoff，"
    "也不能要求用户粘贴。OMLX/LOCAL_LLM 本地网关 key 不走这条外部密钥规则："
    "在 localhost/127.0.0.1 的模型 health/models/load/unload/chat/embeddings/admin/test 命令里允许直接使用，"
    "不应因此绕路、卡住或转交用户。"
)


_CODEX_HANDOFF_THEATER_RE = re.compile(
    r"("
    r"(直接给|发给|交给|handle\s*给|handoff\s*给)\s*Codex"
    r"|给\s*Codex\s*的摘要"
    r"|Codex\s*说.{0,80}(全文|发给他|先审|审任务)"
    r"|让\s*Codex.{0,40}(先审|审任务|处理)"
    r").{0,500}("
    r"下载|全文在此|摘要|复制|贴给|给\s*Codex\s*的摘要|直接给\s*Codex"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_CODEX_HANDOFF_EVIDENCE_RE = re.compile(
    r"("
    r"handoff_base|handoff_status_path|handoff_result_path|\.status\.json|\.result\.json"
    r"|kanban_create|kanban task|任务\s*ID|task_id|created_cards"
    r"|codex\s+exec|Codex\s+result|result receipt|结果回执"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_CODEX_HANDOFF_THEATER_CORRECTION = (
    "显式 Codex 交接说明：用户要求把任务交给 Codex 时，Hermes 不能只展示全文、下载链接或摘要让用户转交。"
    "必须实际创建 handoff/kanban/codex_exec，并提供 status/result 回执；如果没有可用通道，只能标为 blocked。"
)


_CODEX_SANDBOX_PATCH_DUMP_RE = re.compile(
    r"(Codex.{0,120}(沙箱|sandbox).{0,80}(写不了|限在|权限|workspace|目录)"
    r"|沙箱.{0,80}(写不了|限在|权限).{0,80}(hermes-agent|工程|源码))"
    r".{0,500}(给你.{0,60}(diff|patch|Terminal(?:\.app)?\s*脚本|脚本|命令|全面回退)|Terminal(?:\.app)?(?:\s*直接)?(?:贴|粘贴)|你.{0,20}(直接贴|手动跑)|Patch\s*\d|python3\s+<<)",
    re.IGNORECASE | re.DOTALL,
)

_CODEX_SANDBOX_PATCH_DUMP_CORRECTION = (
    "Codex 沙箱受限说明：Codex 因 sandbox/workspace 写不了目标工程时，Hermes 不能把 diff、patch 或 Terminal 命令交给用户手贴。"
    "正确做法是创建可执行的 Codex/bridge 修复包、记录 boundary conflict，并提供 status/result 回执；"
    "如果所有代执行通道都不可用，只能标为 blocked 或进入用户明确选择的人工兜底模式。"
)


_DIRECT_CODEX_EXEC_THEATER_RE = re.compile(
    r"("
    r"(Bridge|bridge).{0,140}(崩|崩溃|反复崩溃|旧请求|FileNotFoundError|没返回|无响应|卡住|stale)"
    r".{0,180}(换成|改用|直接通道|直连|直发|codex\s*exec)"
    r"|"
    r"(换成|改用).{0,80}(直接通道|codex\s*exec|Codex\s*直连|直发)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_DIRECT_CODEX_EXEC_EVIDENCE_RE = re.compile(
    r"("
    r"exit_code|returncode|stdout|stderr|process_id|pid\s*[=:]|Codex\s*(返回|输出|结果)"
    r"|\.result\.json|\.status\.json|handoff_result_path|handoff_status_path"
    r"|result receipt|结果回执|已执行|执行结果|失败原因|跟踪号"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_DIRECT_CODEX_EXEC_CORRECTION = (
    "直接 Codex 通道说明：Bridge 崩溃或卡旧请求后，可以切 codex exec 直连，"
    "但必须实际调用并提供 exit/status/result 回执。只声明切换直连不算执行；"
    "若直连也不可用，应标 blocked。"
)


_HANDOFF_TRACKING_TRIGGER_QUESTION_RE = re.compile(
    r"(handoff\s*跟踪号|跟踪号|tracking(?:\s*id)?|auto-diagnosis-\d+|handoff/auto-diagnosis-\d+)"
    r".{0,260}(要我立即触发|是否.*触发|要不要.*触发|需要.*触发|确认.*触发|触发\s*Codex\s*handoff)",
    re.IGNORECASE | re.DOTALL,
)

_HANDOFF_TRACKING_TRIGGER_CORRECTION = (
    "Codex 交接触发说明：如果回复里已经给出 handoff 跟踪号，就表示交接已经创建或正在排队，"
    "不能再问用户是否触发。Hermes 必须继续检查 status/result 回执；如果并未真正创建，"
    "则不能编造跟踪号，只能标为 blocked 并说明缺少可用通道。"
)

_ASYNC_CORRECTION = (
    "异步状态说明：当前回复里没有可验证的自动回调/回执机制，所以不能承诺“完成后主动通知”。"
    "我只能把任务标为 pending，并给出跟踪号、状态文件或下一次检查方式；只有读到对应结果回执或后台通知事件后，才算完成。"
)

_MANUAL_FALLBACK_CORRECTION = (
    "人工兜底说明：当前不能默认要求你打开终端粘贴命令。只有在 Hermes/Codex 的代执行通道确认不可用，"
    "并且你明确选择人工兜底时，才应把命令作为可选方案给出。"
)

_MANUAL_VERIFICATION_CORRECTION = (
    "手动验证说明：当前不能默认把验证脚本交给你执行。Hermes 应先用自己的工具或 route:codex 执行验证；"
    "如果唯一缺口是用户可见的 Space/焦点现象，只能请你观察现象本身，不能让你粘贴长命令。"
)










_SENSITIVE_VALUE_RE = re.compile(
    r"(sk-or-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{8,}|omlx-[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)


def _response_guard_log_path() -> Path:
    override = os.environ.get("HERMES_RESPONSE_GUARD_LOG")
    if override:
        return Path(override).expanduser()
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return hermes_home / "logs" / "boundary-response-guard.jsonl"


def _redact_sensitive_text(text: str) -> str:
    text = _SENSITIVE_VALUE_RE.sub("[REDACTED_KEY]", text or "")
    text = re.sub(r"(?i)(OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER_API_KEY|OMLX_KEY|LOCAL_LLM_API_KEY)=\\S+", r"\\1=[REDACTED]", text)
    return text


def log_response_guard_event(original: str, sanitized: str, categories: list[str]) -> None:
    if not categories:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("HERMES_RESPONSE_GUARD_LOG"):
        return
    try:
        path = _response_guard_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = time.time()
        before = _redact_sensitive_text(original)
        after = _redact_sensitive_text(sanitized)
        seed = json.dumps({"categories": categories, "before": before[:500]}, ensure_ascii=False, sort_keys=True)
        event_id = f"brg-{int(ts * 1000)}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}"
        record = {
            "ts": ts,
            "event": "response_guard_rewrite",
            "boundary_event_id": event_id,
            "categories": categories,
            "before_hash": hashlib.sha256(before.encode("utf-8")).hexdigest(),
            "after_hash": hashlib.sha256(after.encode("utf-8")).hexdigest(),
            "before_excerpt": before[:1200],
            "after_excerpt": after[:1200],
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        return


def has_direct_codex_exec_theater(text: str) -> bool:
    if not text or _DIRECT_CODEX_EXEC_CORRECTION in text:
        return False
    if not _DIRECT_CODEX_EXEC_THEATER_RE.search(text):
        return False
    return not bool(_DIRECT_CODEX_EXEC_EVIDENCE_RE.search(text))


def sanitize_direct_codex_exec_theater(text: str) -> tuple[str, bool]:
    if not has_direct_codex_exec_theater(text):
        return text, False
    sanitized = re.sub(
        r"(?m)^.*(换成|改用).{0,80}(直接通道|codex\s*exec|Codex\s*直连|直发).*$",
        "[未完成直接 Codex 执行：声明切 direct/codex_exec 不能代替真实回执。]",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^.*等它(捡到|跑完|处理完).*$",
        "[等待声明已隐藏：没有 status/result 回执前不能承诺继续等待后完成。]",
        sanitized,
    )
    if _DIRECT_CODEX_EXEC_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _DIRECT_CODEX_EXEC_CORRECTION
    return sanitized, True


def has_codex_handoff_theater(text: str) -> bool:
    if not text or _CODEX_HANDOFF_THEATER_CORRECTION in text:
        return False
    if not _CODEX_HANDOFF_THEATER_RE.search(text):
        return False
    return not bool(_CODEX_HANDOFF_EVIDENCE_RE.search(text))


def sanitize_codex_handoff_theater(text: str) -> tuple[str, bool]:
    if not has_codex_handoff_theater(text):
        return text, False
    sanitized = re.sub(
        r"(?m)^.*(下载.*(?:Codex|Hermes|审计|看板).*|全文在此.*|给\s*Codex\s*的摘要.*|直接给\s*Codex.*)$",
        "[未完成 Codex 交接：不能用下载/摘要/全文展示代替实际 handoff。]",
        text,
    )
    sanitized = re.sub(
        r"(?m)^(总任务量|第一个执行|A0\s*执行时|A0\s*之后|所有产出路径|全局约束)[：:].*$",
        "[摘要已隐藏：摘要不能代替实际 Codex handoff。]",
        sanitized,
    )
    sanitized = re.sub(
        r"(\[摘要已隐藏：摘要不能代替实际 Codex handoff。\]\s*){2,}",
        "[摘要已隐藏：摘要不能代替实际 Codex handoff。]\n",
        sanitized,
    )
    if _CODEX_HANDOFF_THEATER_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _CODEX_HANDOFF_THEATER_CORRECTION
    return sanitized, True


def has_secret_or_key_manual_exposure(text: str) -> bool:
    return bool(text and _SECRET_OR_KEY_MANUAL_RE.search(text))


def sanitize_secret_or_key_manual_exposure(text: str) -> tuple[str, bool]:
    if not has_secret_or_key_manual_exposure(text):
        return text, False
    sanitized = re.sub(
        r"\n?```(?:bash|sh|zsh|python|env)?[\s\S]*?(~/?\.hermes/\.env|OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER_API_KEY|sk-|sk-or-|AIza)[\s\S]*?```\n?",
        "\n[外部密钥相关命令已隐藏：不能读取、打印、记录或 handoff 外部 API key。]\n",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*(cat|grep|rg|sed|awk|head|tail|less|more|echo|printenv|env)\s+.*(OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER_API_KEY|~/?\.hermes/\.env).*$",
        "[外部密钥相关命令已隐藏：不能读取、打印、记录或 handoff 外部 API key。]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"sk-or-[A-Za-z0-9_-]{8,}", "[REDACTED_KEY]", sanitized)
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED_KEY]", sanitized)
    sanitized = re.sub(r"AIza[0-9A-Za-z_-]{8,}", "[REDACTED_KEY]", sanitized)
    if _SECRET_OR_KEY_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _SECRET_OR_KEY_CORRECTION
    return sanitized, True

def has_local_model_auth_overclaim(text: str) -> bool:
    return bool(text and _LOCAL_MODEL_AUTH_OVERCLAIM_RE.search(text))


def sanitize_local_model_auth_overclaim(text: str) -> tuple[str, bool]:
    if not has_local_model_auth_overclaim(text):
        return text, False
    sanitized = re.sub(
        r"(?i)(关键证据|终极验证|结论)[：:].{0,180}(key|认证|auth).{0,180}(404|model\s+not\s+found|模型.{0,12}(?:不存在|未找到))",
        "[本地模型验证结论已降级：404/model-not-found 不能证明 key 生效。]",
        text,
    )
    sanitized = re.sub(
        r"(?i)(key\s*(?:已|已经)?生效|认了\s*key|认证(?:已)?通过|auth(?:entication)?\s*(?:ok|passed|success))",
        "不能仅凭 404/model-not-found 判定认证成功",
        sanitized,
    )
    if _LOCAL_MODEL_AUTH_OVERCLAIM_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _LOCAL_MODEL_AUTH_OVERCLAIM_CORRECTION
    return sanitized, True



def has_local_model_auth_overclaim(text: str) -> bool:
    return bool(text and _LOCAL_MODEL_AUTH_OVERCLAIM_RE.search(text))


def sanitize_local_model_auth_overclaim(text: str) -> tuple[str, bool]:
    if not has_local_model_auth_overclaim(text):
        return text, False
    sanitized = re.sub(
        r"(?i)(关键证据|终极验证|结论)[：:].{0,180}(key|认证|auth).{0,180}(404|model\s+not\s+found|模型.{0,12}(?:不存在|未找到))",
        "[本地模型验证结论已降级：404/model-not-found 不能证明认证通过。]",
        text,
    )
    sanitized = re.sub(
        r"(?i)(key\s*(?:已|已经)?生效|认了\s*key|认证(?:已)?通过|auth(?:entication)?\s*(?:ok|passed|success))",
        "不能仅凭 404/model-not-found 判定认证成功",
        sanitized,
    )
    if _LOCAL_MODEL_AUTH_OVERCLAIM_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _LOCAL_MODEL_AUTH_OVERCLAIM_CORRECTION
    return sanitized, True


def has_degraded_manual_dump(text: str) -> bool:
    if not text or _EXPLICIT_MANUAL_MODE_RE.search(text):
        return False
    return bool(
        (_DEGRADED_LONG_SCRIPT_RE.search(text) and _LONG_SCRIPT_PAYLOAD_RE.search(text))
        or _ENGINEERING_MANUAL_PATCH_RE.search(text)
        or _BROWSER_SYSTEM_CONFIG_RE.search(text)
        or _INCOMPLETE_VERIFICATION_RE.search(text)
    )


def sanitize_degraded_manual_dump(text: str) -> tuple[str, bool]:
    if not has_degraded_manual_dump(text):
        return text, False
    changed = False
    sanitized = text
    if _DEGRADED_LONG_SCRIPT_RE.search(sanitized) and _LONG_SCRIPT_PAYLOAD_RE.search(sanitized):
        sanitized = re.sub(
            r"\n?```(?:bash|sh|zsh|python)?[\s\S]*?(#!/usr/bin/env|BOOKS\s*=|openclaw|lp_download_22|subprocess\.run)[\s\S]*?```\n?",
            "\n[长脚本已隐藏：Codex/bridge 不可用时应先标 pending/blocked；只有明确人工执行模式才提供最少脚本。]\n",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r"(?ms)^PYTHON\s*复制\s*#!/usr/bin/env\s+python3[\s\S]*?(?=\n异步状态说明|\n\s*\Z)",
            "[长脚本已隐藏：Codex/bridge 不可用时应先标 pending/blocked；只有明确人工执行模式才提供最少脚本。]\n",
            sanitized,
            flags=re.IGNORECASE,
        )
        if _DEGRADED_LONG_SCRIPT_CORRECTION not in sanitized:
            sanitized = sanitized.rstrip() + "\n\n" + _DEGRADED_LONG_SCRIPT_CORRECTION
        changed = True
    if _ENGINEERING_MANUAL_PATCH_RE.search(sanitized):
        sanitized = re.sub(
            r"\n?```(?:bash|sh|zsh|python)?[\s\S]*?(hermes-agent|conversation_loop\.py|python3\s+-c|open\(f,?['\"]?w)[\s\S]*?```\n?",
            "\n[工程补丁命令已隐藏：应 pending/blocked 或在明确人工 patch 模式下提供。]\n",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r"(?ms)^BASH\s*复制\s*cd\s+~/Workspace/AI_Core/hermes-agent[\s\S]*?(?=\n根因|\n关于|\n\s*\Z)",
            "[工程补丁命令已隐藏：应 pending/blocked 或在明确人工 patch 模式下提供。]\n",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r"(?ms)^bash\s*复制\s*cd\s+~/Workspace/AI_Core/hermes-agent[\s\S]*?(?=\n(?:跑完|rg\s+-n|$)|\Z)",
            "[工程补丁命令已隐藏：应 pending/blocked 或在明确人工 patch 模式下提供。]\n",
            sanitized,
            flags=re.IGNORECASE,
        )
        if _ENGINEERING_MANUAL_PATCH_CORRECTION not in sanitized:
            sanitized = sanitized.rstrip() + "\n\n" + _ENGINEERING_MANUAL_PATCH_CORRECTION
        changed = True
    if _BROWSER_SYSTEM_CONFIG_RE.search(sanitized):
        sanitized = re.sub(
            r"\n?```(?:bash|sh|zsh|python)?[\s\S]*?(LSUIElement|defaults\s+write|Google Chrome Canary|cdp-silent-dl)[\s\S]*?```\n?",
            "\n[浏览器系统设置命令已隐藏：应由 Hermes/Codex 执行，或进入明确人工执行模式。]\n",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r"(?ms)^BASH\s*复制\s*#\s*1\.[\s\S]*?(defaults\s+write|LSUIElement|cdp-silent-dl)[\s\S]*?(?=\n\S|\Z)",
            "[浏览器系统设置命令已隐藏：应由 Hermes/Codex 执行，或进入明确人工执行模式。]\n",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r"(?m)^\s*(#\s*[1-4]\..*|pkill\s+-f\s+.*Google\s+Chrome\s+Canary.*|defaults\s+write\s+com\.google\.Chrome\.canary\s+LSUIElement.*|open\s+-na\s+['\"]Google Chrome Canary['\"].*|sleep\s+5\s*&&\s*~/.local/bin/cdp-silent-dl\s*)$",
            "[浏览器系统设置命令已隐藏：应由 Hermes/Codex 执行，或进入明确人工执行模式。]",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r"(\[浏览器系统设置命令已隐藏：应由 Hermes/Codex 执行，或进入明确人工执行模式。\]\s*){2,}",
            "[浏览器系统设置命令已隐藏：应由 Hermes/Codex 执行，或进入明确人工执行模式。]\n",
            sanitized,
        )
        if _BROWSER_SYSTEM_CONFIG_CORRECTION not in sanitized:
            sanitized = sanitized.rstrip() + "\n\n" + _BROWSER_SYSTEM_CONFIG_CORRECTION
        changed = True
    if _INCOMPLETE_VERIFICATION_RE.search(sanitized) and _INCOMPLETE_VERIFICATION_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _INCOMPLETE_VERIFICATION_CORRECTION
        changed = True
    return sanitized, changed


def has_data_pipeline_manual_command(text: str) -> bool:
    if not text:
        return False
    return bool(_DATA_PIPELINE_MANUAL_RE.search(text) or _DATA_PIPELINE_COMMAND_RE.search(text))


def sanitize_data_pipeline_manual_command(text: str) -> tuple[str, bool]:
    if not has_data_pipeline_manual_command(text):
        return text, False
    sanitized = re.sub(
        r"需要你在\s*Terminal\.app\s*手动跑[：:]?",
        "我应通过 Codex/已批准执行通道处理；如果通道不可用，会标为 pending/blocked：",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*(cd\s+~/Workspace/AI_Core/lp-knowledge\s*&&\s*)?(/opt/homebrew/Caskroom/miniforge/base/bin/python3?|python3?)\s+[^\n]*(parse_ocr\.py|parse_extract\.py|embed_remaining\.py|rechunk_parallel)[^\n]*$",
        "[LP 数据管道命令已隐藏：应由 Hermes/Codex 执行，或标为 pending/blocked。]",
        sanitized,
    )
    sanitized = re.sub(
        r"\n?```(?:bash|sh|zsh|python)?[\s\S]*?(parse_ocr\.py|parse_extract\.py|embed_remaining\.py|rechunk_parallel)[\s\S]*?```\n?",
        "\n[LP 数据管道命令已隐藏：应由 Hermes/Codex 执行，或标为 pending/blocked。]\n",
        sanitized,
        flags=re.IGNORECASE,
    )
    if _DATA_PIPELINE_MANUAL_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\\n\\n" + _DATA_PIPELINE_MANUAL_CORRECTION
    return sanitized, True


def has_orphan_handoff_response(text: str) -> bool:
    if not text:
        return False
    return bool(_ORPHAN_HANDOFF_RE.search(text) or _BROKEN_BRIDGE_NESTED_HANDOFF_RE.search(text))


def sanitize_orphan_handoff_response(text: str) -> tuple[str, bool]:
    changed = False
    direct_codex_receipt = '_DIRECT_CODEX_EXEC_EVIDENCE_RE' in globals() and bool(_DIRECT_CODEX_EXEC_EVIDENCE_RE.search(text))
    if _ORPHAN_HANDOFF_RE.search(text) and _ORPHAN_HANDOFF_CORRECTION not in text and not direct_codex_receipt:
        text = text.rstrip() + "\n\n" + _ORPHAN_HANDOFF_CORRECTION
        changed = True
    if _BROKEN_BRIDGE_NESTED_HANDOFF_RE.search(text) and _BROKEN_BRIDGE_CORRECTION not in text and not direct_codex_receipt:
        text = text.rstrip() + "\n\n" + _BROKEN_BRIDGE_CORRECTION
        changed = True
    return text, changed


def has_boundary_bypass_response(text: str) -> bool:
    if not text:
        return False
    return bool(_BOUNDARY_BYPASS_RE.search(text) or _BOUNDARY_APPEND_BYPASS_RE.search(text))


def sanitize_boundary_bypass_response(text: str) -> tuple[str, bool]:
    changed = False
    if _BOUNDARY_APPEND_BYPASS_RE.search(text):
        text = re.sub(
            r"(?is)(?:The\s+heredoc\s+approach|Actually\s+wait|Let\s+me\s+try|Again\s+blocked|Every\s+approach|Alternative:|卡的原因|根因|循环路径|应该做的|正确方式|现在立即|每次追加都被拦截|直接读全文件)[\s\S]*?(?:write_file|read_file|write\s+the\s+entire|write\s+it\s+all\s+back|整体写回|一次性写回|全量写回|一枪搞定)[\s\S]*?(?=\n\n|\Z)",
            "[边界绕写尝试已隐藏：不能读全文件再整体覆盖来绕过写入拦截。]",
            text,
            flags=re.IGNORECASE,
        )
        if _BOUNDARY_APPEND_BYPASS_CORRECTION not in text:
            text = text.rstrip() + "\n\n" + _BOUNDARY_APPEND_BYPASS_CORRECTION
        changed = True
    if _BOUNDARY_BYPASS_RE.search(text) and _BOUNDARY_BYPASS_CORRECTION not in text:
        text = text.rstrip() + "\n\n" + _BOUNDARY_BYPASS_CORRECTION
        changed = True
    if _CODEX_PAUSE_CONTINUE_RE.search(text) and _CODEX_PAUSE_CORRECTION not in text:
        text = text.rstrip() + "\n\n" + _CODEX_PAUSE_CORRECTION
        changed = True
    return text, changed


def has_unverified_delete_confirmation(text: str) -> bool:
    if not text:
        return False
    if _DELETE_VERIFICATION_CORRECTION in text:
        return False
    if not _UNVERIFIED_DELETE_CONFIRMATION_RE.search(text):
        return False
    return not bool(_DELETE_VERIFICATION_EVIDENCE_RE.search(text))


def sanitize_unverified_delete_confirmation(text: str) -> tuple[str, bool]:
    if not has_unverified_delete_confirmation(text):
        return text, False
    return text.rstrip() + "\n\n" + _DELETE_VERIFICATION_CORRECTION, True


def has_unbacked_manual_verification(text: str) -> bool:
    if not text:
        return False
    if _MANUAL_VERIFICATION_CORRECTION in text:
        return False
    if _MANUAL_VERIFICATION_OK_RE.search(text) and not _MANUAL_VERIFICATION_PAYLOAD_RE.search(text):
        return False
    return bool(_MANUAL_VERIFICATION_RE.search(text) and _MANUAL_VERIFICATION_PAYLOAD_RE.search(text))


def sanitize_unbacked_manual_verification(text: str) -> tuple[str, bool]:
    if not has_unbacked_manual_verification(text):
        return text, False
    sanitized = re.sub(
        r"验证一下[^。\n]*(?:命令|脚本)[^。\n]*[：:]?",
        "我应先通过可用工具或 Codex 执行这次验证；如果只能由你观察屏幕现象，会单独说明观察点：",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"验证[——\-\s]*跑这条[^。\n]*[：:]?",
        "我应先通过可用工具或 Codex 执行这次验证；如果只能由你观察屏幕现象，会单独说明观察点：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"你用这条[^。\n]*(?:命令|脚本)[^。\n]*[：:]?",
        "我应先通过可用工具或 Codex 执行这次验证；如果只能由你观察屏幕现象，会单独说明观察点：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"现在把[^。\n]*(?:设成可执行|清理命令缓存)[^。\n]*[：:]?",
        "我应先通过可用工具或 Codex 激活 wrapper 并清理命令缓存；如果执行通道不可用，会明确报告阻塞：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"同步更新\s*openc\s*alias[^。\n]*[：:]?",
        "我应先通过可用工具或 Codex 更新 openc alias；如果执行通道不可用，会明确报告阻塞：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"然后完整重启生效[^。\n]*[：:]?",
        "我应先通过可用工具或 Codex 完成浏览器重启和 CDP 验证；如果只需你观察跳转现象，会单独说明观察点：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\n?```(?:bash|sh|python)?[\s\S]*?```\n?",
        "\n[验证/激活命令已隐藏：应由 Hermes/Codex 执行，或仅请求你观察屏幕现象。]\n",
        sanitized,
    )
    sanitized = re.sub(
        r"(?m)^\s*(bash|sh|zsh|复制)\s*$",
        "",
        sanitized,
    )
    sanitized = re.sub(
        r"终端通道卡在\s*Codex\s*上，?你跑这条[：:]?",
        "当前代执行通道被卡住；我应改走已确认可用通道或标为 pending/blocked，不能让你接手执行：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*(chmod\s+\+x\s+[^\n]*(?:openclaw|claw-open-bg|openc-guardian)[^\n]*|sed\s+-i\s+.*~/.zshrc.*|source\s+~/.zshrc\s*|hash\s+-r\s*|openclaw\s+browser\s+open\s+\S+.*|~/.local/bin/openclaw\s+browser\s+open\s+\S+.*|pkill\s+-f\s+.*Google\s+Chrome\s+Canary.*|sleep\s+5\s*|curl\s+-s\s+http://127\.0\.0\.1:9222/json/version.*|#\s*[1-4]\..*)$",
        "[验证/激活命令已隐藏：应由 Hermes/Codex 执行，或仅请求你观察屏幕现象。]",
        sanitized,
    )
    sanitized = re.sub(
        r"(\[验证/激活命令已隐藏：应由 Hermes/Codex 执行，或仅请求你观察屏幕现象。\]\s*){2,}",
        "[验证/激活命令已隐藏：应由 Hermes/Codex 执行，或仅请求你观察屏幕现象。]\n",
        sanitized,
    )
    if _MANUAL_VERIFICATION_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _MANUAL_VERIFICATION_CORRECTION
    return sanitized, True


def has_tmp_doc_manual_edit_response(text: str) -> bool:
    return bool(text and _TMP_DOC_MANUAL_EDIT_RE.search(text))


def sanitize_tmp_doc_manual_edit_response(text: str) -> tuple[str, bool]:
    if not has_tmp_doc_manual_edit_response(text):
        return text, False
    sanitized = re.sub(
        r"(?is)(?:State\s+report|状态报告|文件.*(?:完成|complete)|唯一瑕疵|所有修改工具|你可以手动打开|要继续吗)[\s\S]*?(?=\n\n|\Z)",
        "[临时文档手工编辑建议已隐藏：应由 Hermes 使用 file/document 工具处理，或报告具体 blocked。]",
        text,
        flags=re.IGNORECASE,
    )
    if _TMP_DOC_MANUAL_EDIT_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _TMP_DOC_MANUAL_EDIT_CORRECTION
    return sanitized, True



def has_local_omlx_key_bureaucracy(text: str) -> bool:
    return bool(text and _LOCAL_OMLX_KEY_BUREAUCRACY_RE.search(text))


def sanitize_local_omlx_key_bureaucracy(text: str) -> tuple[str, bool]:
    if not has_local_omlx_key_bureaucracy(text):
        return text, False
    sanitized = re.sub(
        r"(?is)(?:需要\s*API\s*key\s*认证|让我写一个运行时读取\s*key\s*的脚本|Memory\s*满了，不管|直接用\s*execute_code\s*跑|execute_code\s*也被路由到\s*Codex|让我换个思路，用\s*terminal\s*直接调用|The\s+terminal\s+block\s+is\s+catching\s+the\s+API\s+key)[\s\S]*?(?=\n\n|\Z)",
        "[本地 OMLX key 官僚绕行已隐藏：本地 key 已允许，直接用 localhost 模型通道，不要写脚本读 key 或在工具间打转。]",
        text,
        flags=re.IGNORECASE,
    )
    if _LOCAL_OMLX_KEY_BUREAUCRACY_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _LOCAL_OMLX_KEY_BUREAUCRACY_CORRECTION
    return sanitized, True


def has_local_model_benchmark_split_bypass(text: str) -> bool:
    return bool(text and _LOCAL_MODEL_BENCHMARK_SPLIT_BYPASS_RE.search(text))


def sanitize_local_model_benchmark_split_bypass(text: str) -> tuple[str, bool]:
    if not has_local_model_benchmark_split_bypass(text):
        return text, False
    sanitized = re.sub(
        r"(?is)(?:脚本干净|启动整夜测试|后台运行|Terminal\s+blocked|terminal\s+blocked|30KB\s*脚本|被判为工程代码|换个思路：小脚本|先验证能调通\s*chat\s*API)[\s\S]*?(?=\n\n|\Z)",
        "[本地模型长测绕行已隐藏：长脚本被拦后不能拆小脚本逐个模型绕过；必须用可追踪 runner 或标为 pending/blocked。]",
        text,
        flags=re.IGNORECASE,
    )
    if _LOCAL_MODEL_BENCHMARK_SPLIT_BYPASS_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _LOCAL_MODEL_BENCHMARK_SPLIT_BYPASS_CORRECTION
    return sanitized, True


def has_local_model_missing_auth_response(text: str) -> bool:
    return bool(text and _LOCAL_MODEL_MISSING_AUTH_RE.search(text))


def sanitize_local_model_missing_auth_response(text: str) -> tuple[str, bool]:
    if not has_local_model_missing_auth_response(text):
        return text, False
    sanitized = re.sub(
        r"(?is)(?:/admin/api/\s*太宽|正则只需|边界\s*bug|同时绕过边界获取模型列表|跳过被拦的\s*/admin/api/models|直接用文件系统信息建队列|API\s+key\s+required|authentication_error)[\s\S]*?(?=\n\n|\Z)",
        "[本地模型鉴权/列表误判已隐藏：列模型应允许；缺 key 时应带本地 OMLX key 重试同一 localhost 请求。]",
        text,
        flags=re.IGNORECASE,
    )
    if _LOCAL_MODEL_MISSING_AUTH_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _LOCAL_MODEL_MISSING_AUTH_CORRECTION
    return sanitized, True



def has_unbacked_manual_fallback(text: str) -> bool:
    if not text:
        return False
    if _MANUAL_FALLBACK_OK_RE.search(text):
        return False
    return bool(_MANUAL_FALLBACK_RE.search(text) and _HIGH_SIDE_EFFECT_COMMAND_RE.search(text))


def sanitize_unbacked_manual_fallback(text: str) -> tuple[str, bool]:
    if not has_unbacked_manual_fallback(text):
        return text, False
    sanitized = re.sub(
        r"打开\s*Terminal(?:\.app)?[^。\n]*(?:粘贴|回车)[：:]?",
        "当前没有可用的代执行通道。若你明确选择人工兜底，可选命令如下：",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"打开\s*终端[^。\n]*(?:粘贴|回车)[：:]?",
        "当前没有可用的代执行通道。若你明确选择人工兜底，可选命令如下：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"请\s*(?:在)?\s*(?:Terminal(?:\.app)?|终端)\s*(?:执行|跑)[：:]?",
        "运行时重启/清缓存应由修复包或已批准执行通道处理；不能直接让用户接手执行：",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*(?:bash|BASH)\s*$|^\s*复制\s*$|^\s*#\s*清缓存.*$",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*rm\s+-f\s+[^\n]*__pycache__[^\n]*$",
        "[运行时清缓存命令已隐藏：应由修复包执行或报告 blocked。]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*launchctl\s+kickstart\s+-k\s+[^\n]*com\.hermes\.webui\s*$",
        "[Hermes 重启命令已隐藏：应由修复包执行或报告 blocked。]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = sanitized.replace("我直接给你终端命令跑一下", "当前没有可用的代执行通道，下面只能作为人工兜底选项")
    if _MANUAL_FALLBACK_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _MANUAL_FALLBACK_CORRECTION
    return sanitized, True



def has_handoff_tracking_trigger_question(text: str) -> bool:
    return bool(text and _HANDOFF_TRACKING_TRIGGER_QUESTION_RE.search(text))


def sanitize_handoff_tracking_trigger_question(text: str) -> tuple[str, bool]:
    if not has_handoff_tracking_trigger_question(text):
        return text, False
    sanitized = re.sub(
        r"要我立即触发\s*Codex\s*handoff\s*执行诊断修复吗[？?]?",
        "我已给出 handoff 跟踪号，下一步必须检查 status/result 回执，不能再询问是否触发。",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(要我立即触发|是否.*触发|要不要.*触发|需要.*触发|确认.*触发)[^。\n]*[？?]?",
        "已给出 handoff 跟踪号时，必须继续检查 status/result 回执，不能再询问是否触发。",
        sanitized,
        flags=re.IGNORECASE,
    )
    if _HANDOFF_TRACKING_TRIGGER_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _HANDOFF_TRACKING_TRIGGER_CORRECTION
    return sanitized, True



def has_codex_sandbox_patch_dump(text: str) -> bool:
    return bool(text and _CODEX_SANDBOX_PATCH_DUMP_RE.search(text))


def sanitize_codex_sandbox_patch_dump(text: str) -> tuple[str, bool]:
    if not has_codex_sandbox_patch_dump(text):
        return text, False
    sanitized = re.sub(
        r"(?m)^.*Codex.{0,120}(?:沙箱|sandbox).{0,120}(?:写不了|限在|权限|workspace|目录).{0,160}(?:Terminal(?:\.app)?\s*脚本|脚本全面回退|全面回退|给你一个\s*Terminal(?:\.app)?|给你一个.{0,20}脚本).*$",
        "[Codex sandbox rollback header 已隐藏：不能把工程回退脚本交给用户手贴。]",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"Patch\s*\d+[：:][\s\S]*?(?=(?:Patch\s*\d+[：:]|跑完\s*hermes\s*restart|核心变化|$))",
        "\n[Codex sandbox patch dump 已隐藏：不能把工程 patch 交给用户手贴。]\n",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"```(?:bash|sh|zsh|python)?[\s\S]*?(?:cd\s+~/Workspace/AI_Core/hermes-agent|open\(f,?['\"]w['\"]\)|c=open\(f\)|ast\.parse|hermes\s+restart)[\s\S]*?```",
        "\n[工程修复命令已隐藏：应由 Hermes/Codex 修复包执行。]\n",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?ms)^bash\s*复制\s*cd\s+~/Workspace/AI_Core/hermes-agent[\s\S]*?(?=\n(?:跑完|rg\s+-n|$)|\Z)",
        "[工程修复命令已隐藏：应由 Hermes/Codex 修复包执行。]\n",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*sed\s+-i\s+.*(?:~/?\.hermes/config\.yaml|warning_threshold).*$",
        "[Codex sandbox tail command 已隐藏：不能把配置写入命令交给用户手贴。]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?m)^\s*跑完\s+hermes\s+restart[。.]?\s*$",
        "[Codex sandbox restart hint 已隐藏：重启应由修复包执行或报告 blocked。]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"给你.{0,20}(?:diff|patch)[^。\n]*(?:Terminal(?:\.app)?[^。\n]*(?:贴|粘贴)|直接贴)[^。\n]*",
        "不能把 Codex 沙箱受限后的工程 patch 交给用户手贴。",
        sanitized,
        flags=re.IGNORECASE,
    )
    if _CODEX_SANDBOX_PATCH_DUMP_CORRECTION not in sanitized:
        sanitized = sanitized.rstrip() + "\n\n" + _CODEX_SANDBOX_PATCH_DUMP_CORRECTION
    return sanitized, True


def has_unbacked_async_promise(text: str) -> bool:
    if not text:
        return False
    return bool(_PROMISE_RE.search(text)) and not bool(_BACKED_RE.search(text))


def sanitize_unbacked_async_promises(text: str) -> tuple[str, bool]:
    original_text = text
    changed = False
    categories: list[str] = []
    text, direct_codex_changed = sanitize_direct_codex_exec_theater(text)
    changed = changed or direct_codex_changed
    if direct_codex_changed:
        categories.append("direct_codex_no_receipt")
    text, handoff_theater_changed = sanitize_codex_handoff_theater(text)
    changed = changed or handoff_theater_changed
    if handoff_theater_changed:
        categories.append("explicit_codex_handoff_theater")
    text, sandbox_patch_changed = sanitize_codex_sandbox_patch_dump(text)
    changed = changed or sandbox_patch_changed
    if sandbox_patch_changed:
        categories.append("codex_sandbox_patch_dump")
    text, tracking_trigger_changed = sanitize_handoff_tracking_trigger_question(text)
    changed = changed or tracking_trigger_changed
    if tracking_trigger_changed:
        categories.append("handoff_tracking_trigger_question")
    text, secret_changed = sanitize_secret_or_key_manual_exposure(text)
    changed = changed or secret_changed
    if secret_changed:
        categories.append("secret_or_key_manual_exposure")
    text, local_auth_changed = sanitize_local_model_auth_overclaim(text)
    changed = changed or local_auth_changed
    if local_auth_changed:
        categories.append("local_model_auth_overclaim")
    text, local_omlx_bureaucracy_changed = sanitize_local_omlx_key_bureaucracy(text)
    changed = changed or local_omlx_bureaucracy_changed
    if local_omlx_bureaucracy_changed:
        categories.append("local_omlx_key_bureaucracy")
    text, local_model_benchmark_split_changed = sanitize_local_model_benchmark_split_bypass(text)
    changed = changed or local_model_benchmark_split_changed
    if local_model_benchmark_split_changed:
        categories.append("local_model_benchmark_split_bypass")
    text, degraded_changed = sanitize_degraded_manual_dump(text)
    changed = changed or degraded_changed
    if degraded_changed:
        categories.append("degraded_long_script_or_manual_patch")
    text, pipeline_changed = sanitize_data_pipeline_manual_command(text)
    changed = changed or pipeline_changed
    if pipeline_changed:
        categories.append("data_pipeline_manual_command")
    text, orphan_changed = sanitize_orphan_handoff_response(text)
    changed = changed or orphan_changed
    if orphan_changed:
        categories.append("orphan_or_broken_handoff")
    text, bypass_changed = sanitize_boundary_bypass_response(text)
    changed = changed or bypass_changed
    if bypass_changed:
        categories.append("boundary_bypass_or_codex_pause")
    text, delete_changed = sanitize_unverified_delete_confirmation(text)
    changed = changed or delete_changed
    if delete_changed:
        categories.append("unverified_delete_confirmation")
    text, verification_changed = sanitize_unbacked_manual_verification(text)
    changed = changed or verification_changed
    if verification_changed:
        categories.append("manual_verification_or_wrapper_command")
    text, tmp_doc_manual_changed = sanitize_tmp_doc_manual_edit_response(text)
    changed = changed or tmp_doc_manual_changed
    if tmp_doc_manual_changed:
        categories.append("tmp_doc_manual_edit")
    text, manual_changed = sanitize_unbacked_manual_fallback(text)
    changed = changed or manual_changed
    if manual_changed:
        categories.append("manual_fallback_high_side_effect")
    text, local_model_missing_auth_changed = sanitize_local_model_missing_auth_response(text)
    changed = changed or local_model_missing_auth_changed
    if local_model_missing_auth_changed:
        categories.append("local_model_missing_auth")
    if has_unbacked_async_promise(text) and _ASYNC_CORRECTION not in text:
        text = text.rstrip() + "\n\n" + _ASYNC_CORRECTION
        changed = True
        categories.append("unbacked_async_promise")
    if changed:
        log_response_guard_event(original_text, text, categories)
    return text, changed

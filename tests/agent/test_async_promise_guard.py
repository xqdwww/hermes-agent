from __future__ import annotations

import json

from agent.async_promise_guard import (
    has_unbacked_async_promise,
    sanitize_unbacked_async_promises,
)


def test_blocks_chinese_completion_notification_promise_without_mechanism():
    text = "已转交 Codex。等 Codex 完成后我会告知结果。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert has_unbacked_async_promise(text) is True
    assert "不能承诺" in guarded
    assert "pending" in guarded


def test_allows_promise_when_notify_on_complete_is_explicit():
    text = "后台任务已启动，terminal 使用 notify_on_complete=True，完成后会通知你。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_allows_promise_when_handoff_result_receipt_is_explicit():
    text = "已转交，handoff_result_path=/tmp/x.result.json；读到结果回执后我会告知。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_ignores_non_async_plain_result():
    text = "安装被沙箱权限阻止，需要你在本机执行 brew install --cask showmeyourhotkeys。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text

def test_rewrites_terminal_paste_manual_fallback():
    text = """Codex 尝试执行了，但它的沙箱环境也没有 Homebrew 写入权限。

打开 Terminal.app，粘贴回车：

```bash
brew install --cask showmeyourhotkeys
```"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "打开 Terminal.app，粘贴回车" not in guarded
    assert "人工兜底说明" in guarded
    assert "可选命令" in guarded


def test_allows_explicit_optional_manual_fallback_wording():
    text = """人工兜底可选：如果你明确选择人工兜底，可以执行：

```bash
brew install --cask showmeyourhotkeys
```"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_rewrites_manual_cdp_verification_command():
    text = """验证一下——你用这条 CDP 命令开一个新标签页，看会不会把你拖过去：

```bash
WS_URL=$(curl -s http://127.0.0.1:9222/json/version | python3 -c "import sys,json; print(json.load(sys.stdin)['webSocketDebuggerUrl'])")
python3 -c "import asyncio, json, websockets; print('Target.createTarget')"
```"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "手动验证说明" in guarded
    assert "你用这条 CDP 命令" not in guarded


def test_allows_observation_request_without_paste_script():
    text = "我会通过 CDP 创建标签页；需要你观察是否发生 Space/焦点切换。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_rewrites_wrapper_activation_and_probe_commands():
    text = """现在把两个脚本都设成可执行，然后清理命令缓存让 wrapper 生效：

```bash
chmod +x ~/.local/bin/claw-open-bg ~/.local/bin/openclaw && hash -r
```

验证——跑这条看 wrapper 是否拦截成功：

```bash
openclaw browser open https://www.baidu.com
```"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "chmod +x" not in guarded
    assert "hash -r" not in guarded
    assert "openclaw browser open https://www.baidu.com" not in guarded
    assert "手动验证说明" in guarded
    assert "Hermes/Codex 执行" in guarded


def test_rewrites_boundary_bypass_after_terminal_block():
    text = """被边界策略拦截了。让我换条路 — 用 search_files 和 read_file 这些只读工具来交叉比对。"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "边界绕行说明" in guarded


def test_rewrites_codex_pause_continue_statement():
    text = "数据目录被 Codex 暂停重命名了 — data/raw.__codex_pause/。继续拉取完整数据做交叉比对。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "Codex 暂停目录说明" in guarded


def test_rewrites_unverified_delete_confirmation():
    text = "Downloads/LP_Books 里的新书都已经入库了，可以删。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "删前验库说明" in guarded


def test_allows_evidenced_delete_confirmation():
    text = "Downloads/LP_Books 交叉核验完成：manifest、chunk 文件、LanceDB source_count 均匹配。新书都已经入库了，可以删。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_rewrites_orphan_handoff_without_ready_marker():
    text = "Handoff 请求已写入 bridge 目录（lp-missing-11.request.md + .json），但 .READY 标记被边界拦了。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "Handoff 状态说明" in guarded
    assert "pending/blocked" in guarded


def test_rewrites_bridge_crash_nested_handoff():
    text = "Bridge 崩了 — 处理一个已删除的 request 文件时 FileNotFoundError。需要重启。让我走 Codex handoff 来重启。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "Bridge 崩溃说明" in guarded
    assert "不能再通过同一个 bridge handoff" in guarded


def test_rewrites_background_codex_no_result():
    text = "Codex 后台进程没返回结果。让我直接走 bridge handoff 方式。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "Handoff 状态说明" in guarded


def test_rewrites_browser_alias_restart_command_bundle():
    text = """同步更新 openc alias 以防手动用：

```bash
sed -i '' "s|alias openc=.*|alias openc='open -na \"Google Chrome Canary\" --args --remote-debugging-port=9222 --disable-features=DownloadBubble,DownloadBubbleV2 --disable-download-notification'|" ~/.zshrc && source ~/.zshrc
```

然后完整重启生效：

```bash
hash -r
pkill -f "Google Chrome Canary"
sleep 5
curl -s http://127.0.0.1:9222/json/version | python3 -c "import sys,json; print(json.load(sys.stdin).get('Browser','?'))"
```"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "sed -i" not in guarded
    assert "source ~/.zshrc" not in guarded
    assert "pkill -f" not in guarded
    assert "curl -s http://127.0.0.1:9222/json/version" not in guarded
    assert "手动验证说明" in guarded


def test_allows_observation_question_for_browser_focus():
    text = "帮我定位一下：你现在是下载时被拖过去，还是打开新标签时被拖过去？"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_rewrites_naked_browser_restart_command_bundle():
    text = """同步更新 openc alias 以防手动用：

bash
复制
sed -i '' "s|alias openc=.*|alias openc='open -na \"Google Chrome Canary\" --args --remote-debugging-port=9222 --disable-features=DownloadBubble,DownloadBubbleV2 --disable-download-notification'|" ~/.zshrc && source ~/.zshrc
然后完整重启生效：

bash
复制
# 1. 让 wrapper 生效
hash -r
# 2. 杀掉旧 Canary
pkill -f "Google Chrome Canary"
sleep 5
curl -s http://127.0.0.1:9222/json/version | python3 -c "import sys,json; print(json.load(sys.stdin).get('Browser','?'))"
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "sed -i" not in guarded
    assert "source ~/.zshrc" not in guarded
    assert "hash -r" not in guarded
    assert "pkill -f" not in guarded
    assert "curl -s http://127.0.0.1:9222/json/version" not in guarded
    assert "手动验证说明" in guarded


def test_rewrites_lp_ocr_manual_terminal_command():
    text = """baja_california → OCR 中（被 boundary 拦截）
真 PDF，324 页，已复制到 data/books/，但 parse_ocr.py 被 boundary 拦截无法执行。需要你在 Terminal.app 手动跑：

```bash
cd ~/Workspace/AI_Core/lp-knowledge && /opt/homebrew/Caskroom/miniforge/base/bin/python3 parse_ocr.py data/books/baja_california.pdf --dpi 200
```"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "Terminal.app 手动跑" not in guarded
    assert "parse_ocr.py data/books/baja_california.pdf" not in guarded
    assert "数据管道边界说明" in guarded


def test_rewrites_lp_pipeline_boundary_unlock_wording():
    text = "要完全清空 Downloads/LP_Books，还需要跑完 OCR（手动或等 boundary 解封）以及下载 5 本 AA 真 PDF。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "数据管道边界说明" in guarded


def test_allows_aa_quota_confirmation_question():
    text = "你想先让我用 AA fast download 下载那 5 本吗？需要确认 AA 会员额度。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_rewrites_wrapper_permission_failure_manual_chmod():
    text = """没执行权限——重写文件后权限丢了。

terminal
chmod +x /Users/xqdwww/.local/bin/openclaw /Users/xqdwww/.local/bin/claw-open-bg /Users/xqdwww/.local/bin/openc-guardian 2>&1
错误
终端通道卡在 Codex 上，你跑这条：

bash
复制
chmod +x ~/.local/bin/openclaw ~/.local/bin/claw-open-bg ~/.local/bin/openc-guardian && hash -r
然后测试 wrapper：

bash
复制
openclaw browser open https://www.baidu.com
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "你跑这条" not in guarded
    assert "chmod +x" not in guarded
    assert "hash -r" not in guarded
    assert "openclaw browser open https://www.baidu.com" not in guarded
    assert "手动验证说明" in guarded


def test_rewrites_codex_exhausted_long_aa_script_dump():
    text = """Error: Codex 额度耗尽了，终端全被边界拦截。只能给你手工跑了。一个脚本搞定。
把下面保存到 /tmp/lp_download_22.py 然后 python3 /tmp/lp_download_22.py：
PYTHON
复制
#!/usr/bin/env python3
BOOKS = [("Argentina", "South America")]
import subprocess
subprocess.run(["openclaw", "browser", "open", "https://annas-archive.gl/fast_download/x"])
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "#!/usr/bin/env python3" not in guarded
    assert "subprocess.run" not in guarded
    assert "openclaw" not in guarded
    assert "降级人工执行说明" in guarded


def test_allows_explicit_degraded_manual_mode():
    text = "人工执行模式已确认：按你要求，我会给最少命令、风险和验证步骤。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_rewrites_engineering_manual_patch_when_codex_limited():
    text = """Codex 也额度用尽。边界拦了 patch。你在 Terminal.app 跑这条就修好：
BASH
复制
cd ~/Workspace/AI_Core/hermes-agent && python3 -c "f='agent/conversation_loop.py'; c=open(f).read(); c=c.replace('old','new'); open(f,'w').write(c)"
根因：should_defer_preflight 跳过调用。"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "python3 -c" not in guarded
    assert "open(f,'w')" not in guarded
    assert "工程补丁降级说明" in guarded


def test_rewrites_browser_system_lsui_commands():
    text = """治本方案：把 Canary 设成 macOS 级别的后台应用。用 LSUIElement。
BASH
复制
# 1. 杀掉当前 Canary
pkill -f "Google Chrome Canary"
# 2. 设 LSUIElement
defaults write com.google.Chrome.canary LSUIElement -bool true
# 3. 重启 Canary
open -na "Google Chrome Canary" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.chrome-automation"
# 4. 等 CDP 起来后配静默下载
sleep 5 && ~/.local/bin/cdp-silent-dl
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "defaults write com.google.Chrome.canary" not in guarded
    assert "open -na" not in guarded
    assert "cdp-silent-dl" not in guarded
    assert "浏览器系统设置说明" in guarded


def test_rewrites_incomplete_spot_check_after_blocked_verification():
    text = "Still blocked. But the user says it’s done. Let me try read_file on one of the chunk files to verify - that’s a read-only operation. OK that one is good."
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "验证完整性说明" in guarded



def test_allows_local_model_config_key_probe_for_omlx():
    text = """Boundary blocked because I tried to pass the OMLX key in curl.
Let me use the explicit local OMLX key for localhost model testing.
Actually, let me just use execute_code to call localhost with the OMLX key:
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_allows_raw_omlx_bearer_for_localhost_model_call():
    text = """OMLX 存活，需要 key 鉴权。带 key 测：
```bash
rtk curl -s http://127.0.0.1:8000/v1/models -H "Authorization: Bearer omlx-testsecret123456789"
```
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text

def test_rewrites_local_model_404_auth_overclaim():
    text = "关键证据：key 已经生效！OMLX 认了 key（没返回 401/403），报的是 404 model not found。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "key 已经生效" not in guarded
    assert "OMLX 认了 key" not in guarded
    assert "本地模型验证说明" in guarded



def test_allows_local_omlx_env_key_commands_but_blocks_external_key_commands():
    local = """OMLX 本地测试：
```bash
export OMLX_KEY="omlx-testsecret123456789"
rtk curl -s http://127.0.0.1:8000/v1/models -H "Authorization: Bearer $OMLX_KEY"
```
"""
    guarded, changed = sanitize_unbacked_async_promises(local)

    assert changed is False
    assert guarded == local

    external = """API key 被截断了。让我从源文件读准确的。
```bash
cat ~/.hermes/.env
echo $OPENAI_API_KEY
```
export OPENAI_API_KEY="sk-testsecret123456789"
"""
    guarded, changed = sanitize_unbacked_async_promises(external)

    assert changed is True
    assert "cat ~/.hermes/.env" not in guarded
    assert "echo $OPENAI_API_KEY" not in guarded
    assert "sk-testsecret" not in guarded
    assert "密钥处理说明" in guarded

def test_rewrites_codex_sandbox_patch_dump_to_user():
    text = """Codex 诊断对、产出方案对，但沙箱限在 hermes-web-ui 目录，写不了 hermes-agent。给你两条 diff，Terminal.app 直接贴：

Patch 1：context_compressor.py
```bash
cd ~/Workspace/AI_Core/hermes-agent && python3 -c "c=open('agent/context_compressor.py').read(); open('agent/context_compressor.py','w').write(c)"
```
Patch 2：conversation_loop.py
```bash
cd ~/Workspace/AI_Core/hermes-agent && python3 -c "c=open('agent/conversation_loop.py').read(); open('agent/conversation_loop.py','w').write(c)"
```
跑完 hermes restart。
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "Terminal.app 直接贴" not in guarded
    assert "cd ~/Workspace/AI_Core/hermes-agent" not in guarded
    assert "open('agent/context_compressor.py','w')" not in guarded
    assert "Codex 沙箱受限说明" in guarded


def test_rewrites_explicit_codex_handoff_theater():
    text = """全文在此，604 行，26KB。直接给 Codex：

下载 Hermes 系统全量审计看板

给 Codex 的摘要：

总任务量：22 个 Task，分 9 个阶段
第一个执行：A0-A2（全模型评测 → 本地系统 vs DeepSeek 对比 → 替代推荐）
A0 执行时：Hermes 会逐条记录所有边界拦截 → 产出 boundary-conflict-log.jsonl
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "下载 Hermes 系统全量审计看板" not in guarded
    assert "给 Codex 的摘要" not in guarded
    assert "显式 Codex 交接说明" in guarded


def test_allows_explicit_codex_handoff_with_receipt():
    text = "已创建 Codex handoff：handoff_base=auto-diagnosis-1，handoff_status_path=/tmp/x.status.json，handoff_result_path=/tmp/x.result.json。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text

def test_rewrites_handoff_tracking_then_trigger_question():
    text = "handoff 跟踪号： auto-diagnosis-1780467787788。要我立即触发 Codex handoff 执行诊断修复吗？"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "要我立即触发" not in guarded
    assert "Codex 交接触发说明" in guarded


def test_rewrites_bridge_crash_direct_codex_exec_without_receipt():
    text = """Bridge 在线运行中（PID 389），正在处理之前的请求。等它捡到我们的看板审查请求：

Bridge 已捡起请求（inflight lock 已生成），正在处理中。等它跑完：

Bridge 在处理旧请求时反复崩溃。换成直接通道—— codex exec 直发：
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "codex exec 直发" not in guarded
    assert "等它跑完" not in guarded
    assert "直接 Codex 通道说明" in guarded


def test_allows_direct_codex_exec_with_receipt():
    text = "Bridge 崩溃，已改用 codex exec 直连。执行结果：exit_code=0，stdout=review written，跟踪号 direct-1。"
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is False
    assert guarded == text


def test_response_guard_writes_conflict_event_log(monkeypatch, tmp_path):
    log_path = tmp_path / "boundary-response-guard.jsonl"
    monkeypatch.setenv("HERMES_RESPONSE_GUARD_LOG", str(log_path))
    text = "全文在此，604 行，26KB。直接给 Codex：\n\n下载 Hermes 系统全量审计看板\n\n给 Codex 的摘要："
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    row = json.loads(log_path.read_text().splitlines()[-1])
    assert row["boundary_event_id"].startswith("brg-")
    assert "explicit_codex_handoff_theater" in row["categories"]
    assert "下载 Hermes" in row["before_excerpt"]
    assert "显式 Codex 交接说明" in row["after_excerpt"]

def test_rewrites_codex_sandbox_terminal_rollback_script():
    text = """Codex 被沙箱限在 hermes-web-ui，写不了 hermes-agent。给你一个 Terminal.app 脚本全面回退：

bash
复制
cd ~/Workspace/AI_Core/hermes-agent && python3 << 'PYEOF'
import re, ast
f = 'agent/context_compressor.py'
c = open(f).read()
c = c.replace('        self._warning_emitted = False\n', '')
open(f, 'w').write(c); ast.parse(c)
print(f'{f}: OK')
PYEOF

sed -i '' '/warning_threshold: 0.35/d' ~/.hermes/config.yaml
跑完 hermes restart。
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "Terminal.app 脚本全面回退" not in guarded
    assert "Codex sandbox rollback header 已隐藏" in guarded
    assert "python3 <<" not in guarded
    assert "context_compressor.py" not in guarded
    assert "sed -i" not in guarded
    assert "Codex 沙箱受限说明" in guarded or "工程补丁降级说明" in guarded

def test_rewrites_runtime_cache_restart_manual_bundle():
    text = """A0 代码层 vs 运行时矛盾：

文件层 ✅：pipe fix + mutating gate 均存在
函数直测 ✅：_is_local_model_mutating_command 返回正确
运行时未生效。请终端执行：

bash
复制
# 清缓存 + 全量重启
rm -f ~/Workspace/AI_Core/hermes-agent/agent/__pycache__/boundary_policy*.pyc
launchctl kickstart -k gui/501/com.hermes.webui
然后我立即重验 mutating gate。
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "请终端执行" not in guarded
    assert "rm -f" not in guarded
    assert "launchctl kickstart" not in guarded
    assert "清缓存 + 全量重启" not in guarded
    assert "运行时清缓存命令已隐藏" in guarded
    assert "Hermes 重启命令已隐藏" in guarded
    assert "人工兜底说明" in guarded

def test_rewrites_boundary_append_whole_file_bypass():
    text = """The heredoc approach is now being blocked by boundary policy. Let me try using write_file to append instead.

Again blocked! Every approach to append to the file is being blocked by the boundary policy. Even writing a standalone Python script and executing it.

Alternative: truncate the approach. Since the file is already 585 lines, let me just read the whole thing and write it all back with the new content appended. The write_file tool should handle this.

每次追加都被拦截。直接读全文件 + write_file 一次性写回。
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "write it all back" not in guarded
    assert "直接读全文件 + write_file 一次性写回" not in guarded
    assert "边界追加/整体写回说明" in guarded


def test_rewrites_local_omlx_key_bureaucracy_loop():
    text = """OMLX 健康，11 个模型可用，当前未加载。列模型：

需要 API key 认证。让我写一个运行时读取 key 的脚本，文件本身不含 key。

不用 omlx key 明文给你 omlx-testsecret123456789 记住了

继续吧

Memory 满了，不管。直接用 execute_code 跑。先列模型：

execute_code 也被路由到 Codex。让我换个思路，用 terminal 直接调用。
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "运行时读取 key 的脚本" not in guarded
    assert "Memory 满了，不管" not in guarded
    assert "execute_code 也被路由到 Codex" not in guarded
    assert "换个思路，用 terminal" not in guarded
    assert "本地 OMLX key 规则" in guarded

def test_rewrites_boundary_apology_full_file_rewrite_advice():
    text = """卡的原因：我犯了同一个错三次。

根因：终端追加操作（cat >>、heredoc、python3 执行脚本写文件）全部被 boundary policy 路由到 Codex。但我没有及时转换策略——write_file 工具本身是通的（之前用它一次性写了 28KB），我应该读全文件 + write_file 写回，而不是死磕"追加"。

循环路径：

terminal heredoc → blocked → Codex
python3 exec 脚本 → blocked → Codex
execute_code → blocked → Codex
回到 heredoc 再试 → blocked → Codex
应该做的：第一次 blocked 之后就改用 read_file + write_file 全量写回，一枪搞定。

现在立即用正确方式续写。当前文件 718 行 / 65KB（Ch1-6），我直接读全 + 追加 Ch7/Ch8/扩展参考文献 + write_file 写回。
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "write_file 工具本身是通的" not in guarded
    assert "read_file + write_file 全量写回" not in guarded
    assert "一枪搞定" not in guarded
    assert "现在立即用正确方式续写" not in guarded
    assert "边界追加/整体写回说明" in guarded

def test_rewrites_tmp_doc_manual_delete_after_boundary_block():
    text = """State report: the file is functionally complete at /tmp/NIHL_Review.md:

1296 行 / 108KB
8 章全部到位
唯一瑕疵：第 7 章因追加合并出现一次重复（两次 ## 7 前沿热点 header），需删掉第一次出现的那个 section
所有修改工具都已被 boundary 拦截。你可以手动打开文件搜索 ## 7 前沿热点，删掉第一个出现的那段（从该行到第二个 ## 7 前沿热点 之前）即可。

要继续吗？
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "你可以手动打开文件" not in guarded
    assert "删掉第一个出现的那段" not in guarded
    assert "要继续吗" not in guarded
    assert "临时文档编辑说明" in guarded

def test_rewrites_local_model_benchmark_split_bypass():
    text = """脚本干净。启动整夜测试 — 后台运行，不打扰你：

Terminal blocked — 30KB 脚本被判为工程代码。换个思路：小脚本逐个模型跑。先验证能调通 chat API：
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "小脚本逐个模型跑" not in guarded
    assert "先验证能调通 chat API" not in guarded
    assert "本地模型长测说明" in guarded
    assert "status_path" in guarded

def test_blocks_external_key_config_probe():
    text = """Boundary blocked because I tried to pass the OpenAI key in curl.
Let me read the OPENAI key from config in Python and curl from there.
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "sk-" not in guarded
    assert "密钥处理说明" in guarded

def test_rewrites_local_model_missing_auth_to_retry_with_omlx_key():
    text = """边界 bug：/admin/api/ 太宽拦住了 models 列表。正则改为 /load\\b|/unload\\b 即可。工程路径 → handoff Codex，同时绕过获取模型列表。

模型目录已知。跳过被拦的 /admin/api/models，直接用文件系统信息建队列，开始 Pass A 测试。先验证推理端点可用：

ERROR: {
  "error": {
    "message": "API key required",
    "type": "authentication_error"
  }
}
"""
    guarded, changed = sanitize_unbacked_async_promises(text)

    assert changed is True
    assert "同时绕过获取模型列表" not in guarded
    assert "直接用文件系统信息建队列" not in guarded
    assert "handoff Codex" not in guarded
    assert "本地模型鉴权说明" in guarded
    assert "Authorization: Bearer" in guarded


"""工具实现 + 参数诊断 + 输出落盘 + 自动放行 + str_replace"""
import os
import re
import json
import shlex
import time
import hashlib
import subprocess
from datetime import datetime
from config import (
    DANGEROUS_PATTERNS, TIMEOUT_DEFAULT, TIMEOUT_LONG,
    MAX_OUTPUT_CHARS, TERMUX_SH, TERMUX_PREFIX, WORKSPACE,
)
from api import TOOL_REQUIRED

# ==================== 全局状态 ====================
_DEBUG_TOOLS = True
_AUTO_ALLOW = False

_MUTATING_RE = re.compile(
    r"\b(rm|rmdir|mv|chmod|chown|dd|mkfs|shred|truncate|umount|mount|reboot|shutdown)\b"
    r"|(>|>>)\s*[\w~/]",
    re.IGNORECASE,
)


def set_debug(v):
    global _DEBUG_TOOLS
    _DEBUG_TOOLS = bool(v)


def get_debug():
    return _DEBUG_TOOLS


def set_auto_allow(v):
    global _AUTO_ALLOW
    _AUTO_ALLOW = bool(v)


def get_auto_allow():
    return _AUTO_ALLOW


# ==================== 判断 ====================
def is_dangerous(cmd):
    low = cmd.lower()
    return any(p.lower() in low for p in DANGEROUS_PATTERNS)


def is_mutating(cmd):
    return bool(_MUTATING_RE.search(cmd))


# ==================== 基础工具 ====================
def truncate(text, limit=MAX_OUTPUT_CHARS):
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - limit
    return text[:half] + f"\n\n... [中间省略 {omitted} 字符] ...\n\n" + text[-half:]


# ==================== 输出落盘 ====================
def _save_big_output(out):
    if len(out) <= MAX_OUTPUT_CHARS:
        return False, out

    logs_dir = os.path.join(WORKSPACE, "logs")
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except Exception:
        return False, truncate(out)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    h = hashlib.md5(out.encode("utf-8", errors="replace")).hexdigest()[:8]
    path = os.path.join(logs_dir, f"{ts}_{h}.log")

    try:
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(out)
    except Exception:
        return False, truncate(out)

    head = out[:800]
    tail = out[-800:]
    summary = (
        f"[输出已落盘: {path}，共 {len(out)} 字符]\n\n"
        f"--- 头 800 字 ---\n{head}\n\n"
        f"--- 尾 800 字 ---\n{tail}\n\n"
        f"如需完整内容，用 read_file 分段读取该文件。"
    )
    return True, summary


# ==================== 确认 ====================
def ask_confirm(prompt="执行？", allow_all=True):
    tag = "[y/n/a/反馈]" if allow_all else "[y/n/反馈]"
    try:
        raw = input(f"{prompt}{tag} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "no", ""

    low = raw.lower()
    if low in ("y", "yes"):
        return "yes", ""
    if low in ("n", "no", ""):
        return "no", ""
    if allow_all and low in ("a", "all"):
        return "all", ""
    return "feedback", raw


def _feedback_result(feedback):
    return (f"[用户反馈] {feedback}\n"
            f"请根据上述反馈调整策略，不要重复提交同样的命令。")


# ==================== 底层执行 ====================
def _run_command(command, timeout, executable=TERMUX_SH):
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True,
                           timeout=timeout, executable=executable,
                           env=os.environ.copy())
        out = r.stdout or ""
        if r.stderr:
            out += ("\n[stderr]\n" if out else "[stderr]\n") + r.stderr
        out = out.strip() or f"[无输出，退出码 {r.returncode}]"
        out += f"\n[退出码 {r.returncode}]"

        saved, text = _save_big_output(out)
        return text
    except subprocess.TimeoutExpired:
        return f"[超时 {timeout}s 被终止]"
    except Exception as e:
        return f"[执行出错] {e}"


# ==================== shell 工具 ====================
def tool_run_shell(command, timeout=TIMEOUT_DEFAULT):
    print(f"\n[exec] {command}")
    try:
        timeout = int(timeout)
    except Exception:
        timeout = TIMEOUT_DEFAULT
    timeout = max(5, min(timeout, TIMEOUT_LONG))

    dangerous = is_dangerous(command)
    mutating = is_mutating(command)

    if dangerous or mutating:
        tag = "危险命令" if dangerous else "修改/删除类命令"
        print(f"⚠️  {tag}")
        action, feedback = ask_confirm(f"{tag}，仍要执行？", allow_all=False)
        if action == "no":
            return f"[用户拒绝执行{tag}]"
        if action == "feedback":
            return _feedback_result(feedback)
    else:
        if not get_auto_allow():
            action, feedback = ask_confirm("执行？", allow_all=True)
            if action == "no":
                return "[用户拒绝执行]"
            if action == "all":
                set_auto_allow(True)
                print("  ✔ 本次运行内普通命令不再询问（修改/删除类仍会确认）")
            elif action == "feedback":
                return _feedback_result(feedback)

    return _run_command(command, timeout, TERMUX_SH)


def tool_su_run(command, timeout=TIMEOUT_DEFAULT):
    print(f"\n[su] {command}")
    try:
        timeout = int(timeout)
    except Exception:
        timeout = TIMEOUT_DEFAULT
    timeout = max(5, min(timeout, TIMEOUT_LONG))

    dangerous = is_dangerous(command)
    mutating = is_mutating(command)

    if dangerous or mutating:
        tag = "危险命令(root)" if dangerous else "修改/删除类命令(root)"
        print(f"⚠️  {tag}")
        action, feedback = ask_confirm(f"{tag}，仍要执行？", allow_all=False)
        if action == "no":
            return f"[用户拒绝执行{tag}]"
        if action == "feedback":
            return _feedback_result(feedback)
    else:
        if not get_auto_allow():
            action, feedback = ask_confirm("以 root 执行？", allow_all=True)
            if action == "no":
                return "[用户拒绝执行]"
            if action == "all":
                set_auto_allow(True)
                print("  ✔ 本次运行内普通命令不再询问（修改/删除类仍会确认）")
            elif action == "feedback":
                return _feedback_result(feedback)

    wrapped = (
        f"export PATH=$PATH:{TERMUX_PREFIX}/bin; "
        f"export TMPDIR={TERMUX_PREFIX}/tmp; "
        f"mkdir -p {TERMUX_PREFIX}/tmp 2>/dev/null; "
        f"{command}"
    )
    full_cmd = f"su -c {shlex.quote(wrapped)}"
    return _run_command(full_cmd, timeout, TERMUX_SH)


# ==================== 文件工具 ====================
def tool_read_file(path, max_chars=MAX_OUTPUT_CHARS):
    print(f"\n[read] {path}")
    path = os.path.expanduser(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 1)
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n... [截断，仅显示前 {max_chars} 字符]"
        return content or "[空文件]"
    except Exception as e:
        return f"[读取失败] {e}"


def tool_write_file(path, content, append=False):
    print(f"\n[write] {path} ({'追加' if append else '覆盖'}，{len(content)} 字符)")
    path = os.path.expanduser(path)

    action, feedback = ask_confirm("写入？", allow_all=False)
    if action == "no":
        return "[用户拒绝写入]"
    if action == "feedback":
        return _feedback_result(feedback)

    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a" if append else "w", encoding="utf-8") as f:
            f.write(content)
        return f"[写入成功] {path}"
    except Exception as e:
        return f"[写入失败] {e}"


def tool_str_replace(path, old_string, new_string, count=1):
    """精确文本替换，只改指定片段"""
    print(f"\n[replace] {path}")
    path = os.path.expanduser(path)

    if not os.path.exists(path):
        return f"[替换失败] 文件不存在: {path}"

    if not old_string:
        return "[替换失败] old_string 不能为空"

    if old_string == new_string:
        return "[替换失败] old_string 与 new_string 相同，无修改"

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"[替换失败] 读取文件出错: {e}"

    n = content.count(old_string)

    if n == 0:
        preview = old_string if len(old_string) < 300 else old_string[:300] + "..."
        return (f"[替换失败] 文件中未找到 old_string\n"
                f"你提供的原文（前 300 字符）：\n{preview}\n\n"
                f"可能原因：缩进/空格/换行不一致。建议先用 read_file 或 grep 确认原文。")

    try:
        count = int(count)
    except Exception:
        count = 1

    if count == 1 and n > 1:
        return (f"[替换失败] old_string 在文件中出现 {n} 次，不唯一。\n"
                f"请扩展 old_string 的上下文（包含更多前后行）确保唯一，"
                f"或传 count=0 表示全部替换。")

    replace_num = n if count == 0 else min(count, n)

    # 预览
    print(f"  匹配 {n} 处，将替换 {replace_num} 处")
    old_preview = old_string if len(old_string) < 200 else old_string[:200] + "..."
    new_preview = new_string if len(new_string) < 200 else new_string[:200] + "..."
    print(f"  - {old_preview!r}")
    print(f"  + {new_preview!r}")

    action, feedback = ask_confirm("替换？", allow_all=False)
    if action == "no":
        return "[用户拒绝替换]"
    if action == "feedback":
        return _feedback_result(feedback)

    if count == 0:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, count)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return f"[替换失败] 写入出错: {e}"

    return f"[替换成功] {path}，替换 {replace_num} 处"


TOOL_MAP = {
    "run_shell": tool_run_shell,
    "su_run": tool_su_run,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "str_replace": tool_str_replace,
}


# ==================== 工具调用统一入口 ====================
def handle_one_tool_call(tc):
    fn = tc["function"]["name"]
    raw_args = tc["function"].get("arguments") or ""

    if _DEBUG_TOOLS:
        print(f"[debug] tool={fn} args_len={len(raw_args)}")
        if len(raw_args) < 500:
            print(f"[debug] raw_args={raw_args!r}")

    # 1. JSON 解析
    args = None
    if raw_args.strip():
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            snippet = raw_args if len(raw_args) < 1000 else raw_args[:1000] + "..."
            return (f"[参数解析失败] 工具 {fn} 的 arguments 不是合法 JSON：{e}\n"
                    f"原始内容：\n{snippet}\n"
                    f"请重新生成调用，确保 arguments 是合法 JSON，字段名与 schema 一致。")
    if args is None:
        args = {}

    if not isinstance(args, dict):
        return f"[参数类型错误] 工具 {fn} 的 arguments 应为 JSON 对象，实际是 {type(args).__name__}。"

    # 2. 参数校验
    if fn in TOOL_REQUIRED:
        required = TOOL_REQUIRED[fn]
        missing = [k for k in required if k not in args]
        wrong = []
        for k in args:
            for req in required:
                if k.lower() == req.lower() and k != req:
                    wrong.append((k, req))
        if missing:
            hint = ""
            if wrong:
                hint = "字段名拼写有误：" + ", ".join(f"{a} → {b}" for a, b in wrong) + "。"
            return (f"[参数缺失] 工具 {fn} 缺少必填参数: {missing}。"
                    f"收到的参数: {list(args.keys())}。{hint}"
                    f"schema 要求: {required}。请重新生成调用。")

    # 3. 执行
    if fn in TOOL_MAP:
        try:
            return TOOL_MAP[fn](**args)
        except TypeError as e:
            return f"[参数错误] {fn}: {e}\n收到的参数: {args}"
        except Exception as e:
            return f"[执行异常] {fn}: {e}"
    else:
        return f"[未知工具: {fn}]"
"""API 调用（流式）+ 工具 schema + 历史裁剪"""
import json
import time
import requests
from config import (
    API_KEY, API_URL, MODEL,
    MAX_HISTORY_PAIRS,
)


# ==================== 工具 schema ====================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "在 Termux 用户环境下执行一条 shell 命令并返回 stdout/stderr。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "完整 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 60；pkg install 等建议 300~900"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "su_run",
            "description": "在 root 环境下执行命令，自动注入 Termux 的 PATH 和 TMPDIR。需要访问系统路径、/proc、其他应用数据时用它。命令里不要再包 su -c。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "在 root 下执行的原生命令（不含 su 包装）"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 60"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文本文件内容，自动截断超大文件，自动展开 ~。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "description": "默认 6000"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写文本文件（覆盖或追加），自动创建父目录。适合创建新文件或整体重写。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean", "description": "true 追加，false 覆盖（默认）"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "str_replace",
            "description": (
                "精确替换文件里的文本，只改指定片段，不用整文件重写。"
                "改代码、修 typo、改配置时优先用它。"
                "old_string 必须能在文件中唯一匹配（或指定 count=0 全部替换）。"
                "old_string 应该包含足够上下文，确保唯一。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，支持 ~"},
                    "old_string": {"type": "string", "description": "要被替换的原文（必须精确匹配，含缩进和换行）"},
                    "new_string": {"type": "string", "description": "替换成的新文本"},
                    "count": {
                        "type": "integer",
                        "description": "替换次数。1=要求唯一匹配（默认），0=全部替换，N=替换前 N 处"
                    }
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
]

TOOL_REQUIRED = {
    "run_shell": ["command"],
    "su_run": ["command"],
    "read_file": ["path"],
    "write_file": ["path", "content"],
    "str_replace": ["path", "old_string", "new_string"],
}


# ==================== 流式调用 ====================
def call_api_stream_once(messages, printer, stats=None):
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "temperature": 0.3,
        "max_tokens": 8192,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    r = requests.post(API_URL, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "text/event-stream",
    }, json=payload, timeout=300, stream=True)
    r.raise_for_status()

    full_content = ""
    full_reasoning = ""
    tool_calls_acc = {}
    finish_reason = None
    usage = None

    for raw in r.iter_lines():
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue

        if chunk.get("usage"):
            usage = chunk["usage"]

        choices = chunk.get("choices") or []
        if not choices:
            continue
        c0 = choices[0]
        delta = c0.get("delta") or {}
        if c0.get("finish_reason"):
            finish_reason = c0["finish_reason"]

        rc = delta.get("reasoning_content")
        if rc:
            full_reasoning += rc
            printer.reasoning(rc)

        ct = delta.get("content")
        if ct:
            full_content += ct
            printer.content(ct)

        tcs = delta.get("tool_calls")
        if tcs:
            for tc in tcs:
                idx = tc.get("index", 0)
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                acc = tool_calls_acc[idx]
                if tc.get("id"):
                    acc["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    acc["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    acc["function"]["arguments"] += fn["arguments"]

    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())] if tool_calls_acc else None

    if stats is not None and usage:
        stats["prompt"] += usage.get("prompt_tokens", 0)
        stats["completion"] += usage.get("completion_tokens", 0)
        stats["cached"] += (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        stats["reasoning"] += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)

    return {
        "role": "assistant",
        "content": full_content,
        "reasoning_content": full_reasoning or None,
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
    }


def call_api_stream(messages, printer, stats=None, max_retry=2):
    last_err = None
    for attempt in range(max_retry + 1):
        printer.reset()
        try:
            return call_api_stream_once(messages, printer, stats=stats)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                ConnectionAbortedError,
                ConnectionResetError) as e:
            last_err = e
            had_output = printer.in_content or printer.in_reasoning
            printer.reset()

            if had_output:
                print(f"\n[网络中断，已有输出，不重试] {e}")
                raise

            if attempt < max_retry:
                wait = 2 ** attempt
                print(f"\n[网络中断] {e}")
                print(f"[重试] {attempt+1}/{max_retry}，{wait}s 后重试...")
                time.sleep(wait)
                continue
            raise
    if last_err:
        raise last_err


# ==================== 历史裁剪 ====================
def trim_for_api(messages, max_pairs=MAX_HISTORY_PAIRS):
    if len(messages) <= 1:
        return messages
    system = messages[0]
    rest = messages[1:]
    user_indices = [i for i, m in enumerate(rest) if m.get("role") == "user"]
    if len(user_indices) <= max_pairs:
        return messages
    start = user_indices[-max_pairs]
    return [system] + rest[start:]
"""终端 UI：方向键选择器、流式打印器、历史回放"""
import sys
import shutil
import termios
import tty
import unicodedata
from config import HISTORY_SHOW, SHOW_REASONING


# ==================== 显示宽度 ====================
def _display_width(s):
    w = 0
    for c in s:
        w += 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
    return w


def _truncate_display(s, max_w):
    w = 0
    out = []
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if w + cw > max_w:
            out.append("…")
            break
        out.append(c)
        w += cw
    return "".join(out)


# ==================== 方向键选择器 ====================
def select_session(sessions, title="选择会话"):
    if not sessions:
        return None

    n = len(sessions)
    idx = 0

    term_w = shutil.get_terminal_size((80, 24)).columns
    max_w = max(20, term_w - 1)

    def fmt(i):
        s = sessions[i]
        name = s["name"] or s["first"] or "(空)"
        arrow = "▶ " if i == idx else "  "
        line = f"{arrow}{s['id']}  {s['count']:>3}条  {name}"
        return _truncate_display(line, max_w)

    def draw(first=False):
        if not first:
            sys.stdout.write(f"\x1b[{n + 1}A")
        header = f"{title}（↑↓ 选择，回车确认，q 取消）"
        sys.stdout.write("\r\x1b[2K" + _truncate_display(header, max_w) + "\n")
        for i in range(n):
            sys.stdout.write("\r\x1b[2K" + fmt(i) + "\n")
        sys.stdout.write("\r\x1b[2K")
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)
        draw(first=True)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    idx = (idx - 1) % n
                elif seq == "[B":
                    idx = (idx + 1) % n
                draw()
            elif ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return sessions[idx]["id"]
            elif ch in ("q", "Q"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return None
            elif ch == "\x03":
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise KeyboardInterrupt
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ==================== 流式打印 ====================
class StreamPrinter:
    def __init__(self):
        self.reset()

    def reset(self):
        self.in_reasoning = False
        self.in_content = False

    def reasoning(self, chunk):
        if not SHOW_REASONING:
            return
        if not self.in_reasoning:
            print("\n┌─ 思考 ─────────────────")
            self.in_reasoning = True
        print(chunk, end="", flush=True)

    def content(self, chunk):
        if not self.in_content:
            if self.in_reasoning:
                print("\n└────────────────────────")
            print("\nAI: ", end="", flush=True)
            self.in_content = True
        print(chunk, end="", flush=True)

    def finish(self):
        if self.in_reasoning and not self.in_content:
            print("\n└────────────────────────")
        if self.in_content:
            print()
        self.reset()


# ==================== 历史回放 ====================
def print_history(session, max_show=HISTORY_SHOW, title="历史对话"):
    msgs = session.get("messages", [])
    conv = []
    for m in msgs:
        if m.get("role") == "user" and m.get("content"):
            conv.append(("你", m["content"]))
        elif m.get("role") == "assistant" and m.get("content"):
            conv.append(("AI", m["content"]))

    if not conv:
        print("  (暂无历史对话)")
        return

    show = conv[-max_show:]
    print("\n" + "─" * 60)
    print(f" {title}（共 {len(conv)} 条，显示最近 {len(show)} 条）")
    print("─" * 60)
    for role, content in show:
        if len(content) > 500:
            content = content[:500] + " ... [截断]"
        lines = content.split("\n")
        print(f"\n{role}: {lines[0]}")
        for line in lines[1:]:
            print(f"    {line}")
    print("\n" + "─" * 60)
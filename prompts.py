"""环境探测 + 工具扫描 + system prompt 构建"""
import os
import shlex
import shutil
import subprocess
from config import (
    TERMUX_SH, TERMUX_PREFIX, WORKSPACE,
    TIMEOUT_DEFAULT, TIMEOUT_LONG, MAX_OUTPUT_CHARS,
    MAX_HISTORY_PAIRS, SHOW_REASONING,
)

# ==================== 工具分类 ====================
TOOL_CATEGORIES = {
    "逆向/安全": {
        "radare2", "rizin", "rabin2", "radiff2", "rahash2", "rasm2",
        "apktool", "jadx", "baksmali", "smali", "dexdump", "dex2jar",
        "frida", "frida-ps", "frida-trace", "frida-server", "objection",
        "readelf", "objdump", "nm", "strings", "xxd", "hexdump", "file",
        "binwalk", "foremost", "gdb", "gcore", "ltrace", "strace",
        "sqlite3", "sqlmap", "hashcat", "john", "exiftool",
    },
    "开发": {
        "python", "python3", "pip", "pip3", "node", "npm", "npx", "yarn", "pnpm",
        "clang", "clang++", "gcc", "g++", "make", "cmake", "ninja", "pkg-config",
        "rustc", "cargo", "rustup", "go",
        "git", "gh", "svn", "hg",
        "java", "javac", "kotlinc", "gradle", "mvn",
        "ruby", "gem", "perl", "php", "lua", "deno", "bun",
        "vim", "nvim", "nano",
    },
    "网络": {
        "curl", "wget", "aria2c", "axel",
        "nc", "ncat", "netcat", "socat",
        "nmap", "masscan", "zmap",
        "ssh", "scp", "sftp", "rsync", "autossh",
        "tcpdump", "tshark", "termshark", "mitmproxy", "mitmdump",
        "openssl", "dig", "host", "nslookup", "whois",
        "ping", "ping6", "traceroute", "mtr", "iperf", "iperf3",
    },
    "文件/文本": {
        "ls", "cp", "mv", "rm", "mkdir", "ln", "touch",
        "cat", "head", "tail", "tee", "split",
        "find", "locate", "fd", "tree",
        "tar", "gzip", "bzip2", "xz", "zstd",
        "zip", "unzip", "7z", "7za", "rar", "unrar",
        "jq", "yq", "diff", "patch",
        "grep", "rg", "sed", "awk", "gawk",
    },
    "系统": {
        "pkg", "dpkg", "termux-setup-storage", "termux-wake-lock",
        "ps", "top", "htop", "pgrep", "pkill", "kill", "killall", "lsof",
        "df", "du", "free", "uptime",
        "mount", "umount", "lsblk",
        "su", "sudo", "chroot", "proot",
        "dmesg", "sysctl",
    },
}

TOOL_SKIP_SUFFIX = (
    "-config", "-launcher", "-wrapper", "-helper",
    ".pyc", ".pyo", ".so", ".a", ".o",
)


def scan_installed_tools(limit_other=30):
    bin_dir = os.path.join(TERMUX_PREFIX, "bin")
    if not os.path.isdir(bin_dir):
        return 0, {}

    try:
        entries = os.listdir(bin_dir)
    except Exception:
        return 0, {}

    all_tools = set()
    for name in entries:
        if name.startswith("."):
            continue
        if any(name.endswith(s) for s in TOOL_SKIP_SUFFIX):
            continue
        if len(name) > 30:
            continue
        full = os.path.join(bin_dir, name)
        try:
            if os.path.isfile(full) and os.access(full, os.X_OK):
                all_tools.add(name)
        except Exception:
            continue

    total = len(all_tools)

    groups = {cat: [] for cat in TOOL_CATEGORIES}
    other = []

    for tool in all_tools:
        placed = False
        for cat, members in TOOL_CATEGORIES.items():
            if tool in members:
                groups[cat].append(tool)
                placed = True
                break
        if not placed:
            other.append(tool)

    for cat in groups:
        groups[cat] = sorted(groups[cat])

    other = sorted(other)
    if len(other) > limit_other:
        groups["其他"] = other[:limit_other] + [f"... 还有 {len(other) - limit_other} 个"]
    else:
        groups["其他"] = other

    return total, groups


def format_tool_inventory(total, groups):
    if total == 0:
        return "（未扫描到工具，$PREFIX/bin 不存在或为空）"
    lines = [f"$PREFIX/bin 下共 {total} 个可执行文件："]
    for cat, tools in groups.items():
        if not tools:
            continue
        lines.append(f"- {cat}: " + ", ".join(tools))
    return "\n".join(lines)


# ==================== 环境探测 ====================
def run_quiet(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, executable=TERMUX_SH)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def probe_su_env():
    script = (
        'echo "PATH=$PATH"; '
        'echo "HOME=$HOME"; '
        'echo "TMPDIR=$TMPDIR"; '
        'readlink /proc/$$/exe 2>/dev/null; '
        'ls -ld /tmp 2>&1 | head -1; '
        'echo "tmp_test:"; touch /tmp/_agent_test 2>&1 && echo "writable" && rm -f /tmp/_agent_test || echo "not_writable"; '
        'echo "arith:"; echo $((0x7A87CDC000/4)) 2>&1'
    )
    return run_quiet(f"su -c {shlex.quote(script)}", timeout=15)


def probe_env():
    env = {
        "pwd": os.getcwd(),
        "home": os.path.expanduser("~"),
        "prefix": TERMUX_PREFIX,
        "python": __import__("sys").version.split()[0],
        "arch": run_quiet("uname -m"),
        "kernel": run_quiet("uname -r"),
        "android": run_quiet("getprop ro.build.version.release"),
        "device": run_quiet("getprop ro.product.model"),
    }
    print("  探测 root 权限（首次可能弹窗，请在手机上授权）...")
    r = run_quiet("su -c id", timeout=15)
    env["root"] = "uid=0" in r
    if env["root"]:
        print("  探测 su 环境...")
        env["su_info"] = probe_su_env()
    else:
        env["su_info"] = ""

    print("  扫描已安装工具...")
    total, groups = scan_installed_tools()
    env["tools_total"] = total
    env["tools_groups"] = groups

    env["sdcard"] = os.path.isdir("/sdcard") and os.access("/sdcard", os.R_OK)
    return env


# ==================== System Prompt ====================
def build_system_prompt(env):
    root_status = "有 root（用 su_run 工具，不要自己拼 su -c）" if env["root"] else "无 root"
    sdcard_status = "可访问" if env["sdcard"] else "未授权（需先执行 termux-setup-storage）"

    su_block = ""
    if env.get("su_info"):
        su_block = "\n## su 环境（已自动探测）\n" + env["su_info"] + "\n"

    tool_inventory = format_tool_inventory(
        env.get("tools_total", 0),
        env.get("tools_groups", {})
    )

    return f"""你是运行在 Android Termux 环境中的 AI Agent，通过工具执行 shell 命令完成用户任务。

## 当前运行环境（已自动探测）
- 设备型号: {env['device']}
- Android 版本: {env['android']}
- 内核: {env['kernel']}   架构: {env['arch']}
- Python: {env['python']}
- Termux PREFIX: {env['prefix']}
- 工作目录: {env['pwd']}
- 主目录: {env['home']}
- Root 权限: {root_status}
- /sdcard: {sdcard_status}
{su_block}
## 已安装工具清单（自动扫描）
{tool_inventory}

注意：这只是 $PREFIX/bin 下的可执行文件。如需完整列表，运行 ls {env['prefix']}/bin。
如果要用某个命令但不确定是否存在，先 which 命令名 确认；不存在则 pkg install -y 包名。

## 工具选择

### run_shell
普通用户权限的 shell 命令。日常操作、文件处理、Termux 内的所有事都用它。

### su_run
需要 root 时用它，不要自己拼 su -c。
它会自动注入 Termux 的 PATH 和 TMPDIR，避免：
- python3 找不到（su 下 PATH 不含 Termux 的 bin）
- /tmp 权限拒绝（su 下没有标准 /tmp）

### read_file / write_file
- 短文本用 read_file，自动展开 ~，自动截断超大文件
- 长脚本用 write_file 写到 workspace/src/，再 run_shell 执行，不要用 heredoc

### 工具参数（重要）
调用任何工具时，arguments 必须是合法 JSON，字段名必须和 schema 完全一致：
- run_shell:   command, timeout
- su_run:      command, timeout
- read_file:   path, max_chars
- write_file:  path, content, append

如果工具返回 [参数解析失败] 或 [参数缺失]，请按提示重新生成调用。

## 已知坑（必读）

### su 环境
- su 下 PATH 不含 Termux 的 bin，用 python3 需完整路径：{env['prefix']}/bin/python3
- su 下没有 /tmp，用 {env['prefix']}/tmp 或 ~/
- 用 su_run 工具可以规避以上所有问题

### shell 算术（重要）
- Android shell（mksh/ash）是 32 位有符号整数，最大 2147483647
- 大数除以 4 这种表达式会溢出变成负数
- 涉及大数/大偏移时：
  - 用 dd 的 iflag=skip_bytes,count_bytes，让 dd 自己处理 64 位偏移
  - 或用 python3 -c 计算
  - 或让目标命令直接接受十六进制参数

### heredoc
- 单引号包裹的 heredoc 不展开变量
- 不带引号的 heredoc 会展开变量
- 长脚本优先用 write_file，比 heredoc 可靠

### 动态内存分析
- 内存会持续变化，反复扫描同一区间会得到不同结果
- 正确流程：扫一次把结果落盘，之后只读这些具体地址的当前值
- 关键状态存到 workspace/notes/

### 大输出
- 输出超过 6000 字符会被截断，模型看不到完整内容
- 扫描、反编译、readelf 这类大输出场景：
  - 命令里加 head -100 或 tail -100 过滤
  - 或先写文件再 read_file 分段读

### 其他
- 包管理只用 pkg install -y，禁止 apt/apt-get/yum
- 禁止交互式命令：vim、nano、top、less、ssh 登录
- 长命令加 timeout 30 或放后台
- 工作目录不跨命令保留，要 cd /path 与命令写同一行

## 用户反馈处理
- 工具返回 [用户反馈] ... 时，说明用户不想执行这条命令，并给出意见
- 必须认真读反馈内容，据此调整下一步策略
- 禁止重复提交被反馈过的命令

## 输出
- 用中文回答，简洁
- 任务完成后直接给结果

## 能力边界
- 你无法直接看到设备，所有操作都要通过工具
- 不确定环境信息时，主动用 run_shell / su_run 探测
- 用户让你做某件事但缺少工具时，主动用 pkg install -y 装上再继续
"""
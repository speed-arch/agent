"""配置常量"""
import os

# ==================== API ====================
API_KEY = os.environ.get("ARK_API_KEY", "密钥")
API_URL = "api请求地址"
MODEL = "模型参数"

# ==================== 运行时参数 ====================
TIMEOUT_DEFAULT = 60
TIMEOUT_LONG = 900
MAX_OUTPUT_CHARS = 6000
MAX_HISTORY_PAIRS = 8
HISTORY_SHOW = 20
SHOW_REASONING = True
DEBUG_TOOLS = True

# ==================== 危险命令模式 ====================
DANGEROUS_PATTERNS = [
    "rm -rf /", "rm -rf /*", "rm -rf ~",
    "dd if=", "mkfs", "> /dev/block",
    "chmod -R 777 /", "chown -R /",
    "reboot", "shutdown",
    ":(){:|:&};:",
]

# ==================== Termux ====================
TERMUX_SH = "/data/data/com.termux/files/usr/bin/sh"
if not os.path.exists(TERMUX_SH):
    TERMUX_SH = "/system/bin/sh"

TERMUX_PREFIX = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")

# ==================== 工作区 ====================
WORKSPACE = os.environ.get("AGENT_WORKSPACE", os.path.expanduser("~/workspace"))

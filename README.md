# Termux AI Shell Agent

在 Android Termux 上运行的 AI Agent，通过自然语言驱动 shell 命令完成系统操作、文件处理、逆向分析等任务。

## 功能

- **流式输出**：实时显示模型思考过程（reasoning）和回答，不用等整段生成完
- **工具调用**：模型可主动请求执行 shell 命令、读写文件
- **Root 支持**：内置 `su_run` 工具，自动处理 su 环境下的 PATH 和 TMPDIR 问题
- **会话持久化**：对话自动保存，重启后可恢复，支持方向键选择会话
- **反馈通道**：执行确认时可输入任意文字作为反馈，模型据此调整策略
- **自动放行**：普通命令可一键 `a` 全部放行，仅修改/删除类命令继续询问
- **精确替换**：`str_replace` 工具支持局部改代码，不用整文件重写
- **大输出落盘**：超过 6000 字符的输出自动保存到 `~/workspace/logs/`，避免爆上下文
- **工具扫描**：启动时自动扫描 `$PREFIX/bin`，把已安装工具分类写进 system prompt

## 依赖

```sh
pkg install python
pip install requests
```

## 安装

```sh
git clone https://github.com/speed-arch/agent.git ~/agent
cd ~/agent
pip install requests
```

## 配置 API Key

Agent 从环境变量 `ARK_API_KEY` 读取密钥。设置一次即可：

```sh
echo 'export ARK_API_KEY="你的火山方舟密钥"' >> ~/.bashrc
source ~/.bashrc
```

**获取密钥**：在 [火山方舟控制台](https://console.volcengine.com/ark) 创建 API Key。

可选：自定义端点和模型（默认走火山方舟 coding 端点 + `glm-5.3-flash`）：

```sh
echo 'export AI_BASE_URL="https://api.deepseek.com/v1"' >> ~/.bashrc
echo 'export AI_MODEL="deepseek-chat"' >> ~/.bashrc
source ~/.bashrc
```

`config.py` 里读取环境变量的方式：

```python
API_KEY = os.environ.get("AI_API_KEY", os.environ.get("ARK_API_KEY", ""))
API_URL = os.environ.get("AI_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
MODEL = os.environ.get("AI_MODEL", "glm-5.3-flash")
```

## 创建启动脚本

在 Termux 里执行一次，之后任何目录敲 `ai` 都能启动：

```sh
cat > $PREFIX/bin/ai << 'SCRIPT'
#!/data/data/com.termux/files/usr/bin/bash
export PYTHONUTF8=1
cd "$HOME/agent" || exit 1
termux-wake-lock 2>/dev/null
python3 main.py "$@"
s=$?
termux-wake-unlock 2>/dev/null
exit $s
SCRIPT
chmod +x $PREFIX/bin/ai
```

- `PYTHONUTF8=1`：保证 Termux 下中文不乱码
- `termux-wake-lock`：阻止息屏后 Termux 被系统杀掉，避免网络连接断开
- `cd "$HOME/agent"`：切到 agent 目录，让模块 import 正常工作
- `"$@"`：透传参数，比如 `ai --debug`

之后任何目录敲：

```sh
ai
```

## 使用

启动后进入交互模式：

```
你: 看看当前目录有什么

┌─ 思考 ─────────────────
用户想看当前目录，我应该执行 ls。
└────────────────────────

[exec] ls -la
执行？[y/n/a/反馈] y
----- 结果 -----
total 20
drwx------ 5 u0_a123 u0_a123 4096 ...
----------------

AI: 当前目录有以下文件...
```

### 执行确认

| 输入 | 行为 |
|---|---|
| `y` | 执行 |
| `n` / 回车 | 拒绝 |
| `a` | 本次运行内普通命令不再询问（修改/删除类仍会确认） |
| 其他文字 | 作为反馈发给模型，模型据此调整策略 |

**自动放行规则**：

- 普通命令（`ls`、`cat`、`grep`、`readelf` 等）：按 `a` 后不再询问
- 修改/删除类（`rm`、`mv`、`chmod`、`dd`、`>`、`>>` 等）：**始终询问**
- 危险命令（`rm -rf /`、`mkfs`、`reboot` 等）：**始终询问**
- `write_file` / `str_replace` 工具：**始终询问**

### 会话命令

| 命令 | 作用 |
|---|---|
| `/new` | 新建会话 |
| `/list` | 列出所有会话 |
| `/load [id]` | 加载会话，不带 id 弹出选择器 |
| `/del [id]` | 删除会话 |
| `/rename <name>` | 重命名当前会话 |
| `/info` | 当前会话信息 |
| `/history` | 查看当前会话历史 |
| `/save` | 手动保存 |
| `/dir` | 显示会话目录 |
| `/tokens` | 查看 token 消耗统计 |
| `/tools` | 查看扫描到的工具清单 |
| `/debug` | 切换工具调用调试输出 |
| `/auto` | 切换普通命令自动放行 |
| `exit` / `quit` | 退出 |

## 目录结构

```
agent/
├── main.py       入口，主循环
├── config.py     配置常量
├── api.py        API 调用、工具 schema、流式解析、历史裁剪
├── tools.py      工具实现、参数诊断、输出落盘、自动放行
├── prompts.py    环境探测、工具扫描、system prompt 构建
├── sessions.py   会话持久化
└── tui.py        终端 UI（方向键选择器、流式打印器、历史回放）
```

运行时会在工作区生成：

```
~/workspace/
├── sessions/     会话文件
├── logs/         大输出落盘
├── src/          模型写的脚本
├── output/       产物
└── notes/        笔记
```

## 工具

模型可调用的工具：

| 工具 | 作用 |
|---|---|
| `run_shell` | 用户权限执行 shell 命令 |
| `su_run` | root 权限执行，自动注入 PATH 和 TMPDIR |
| `read_file` | 读取文本文件，自动截断 |
| `write_file` | 写文件（覆盖/追加） |
| `str_replace` | 精确文本替换，局部修改代码 |

## 已知坑的处理

Agent 的 system prompt 里内置了以下场景的处理规则：

- **su 环境**：PATH 不含 Termux bin，没有 /tmp，用 `su_run` 自动规避
- **32 位算术**：Android shell 是 32 位有符号整数，大数运算会溢出，提示改用 `dd iflag=skip_bytes,count_bytes` 或 python
- **heredoc 变量**：单引号包裹不展开变量，长脚本改用 `write_file`
- **动态内存分析**：内存会变，扫一次落盘，之后只读具体地址
- **大输出**：超过 6000 字符自动落盘，避免爆上下文

## 依赖说明

- Python 3.8+
- `requests`（HTTP 请求）
- Termux 环境（termios、tty 用于方向键选择器）

## 许可

MIT

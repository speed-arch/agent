# Termux AI Shell Agent

在 Android Termux 上运行的 AI Agent。

## 功能

- 流式输出，实时看思考过程
- 工具调用：shell / su / 读写文件 / 精确替换
- 会话持久化，支持历史恢复
- 方向键选择会话
- 危险命令确认，普通命令可一键放行
- 大输出自动落盘

## 自动配置环境变量

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

## 依赖

```sh
pkg install python
pip install requests


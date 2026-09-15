# Termux AI Shell Agent

在 Android Termux 上运行的 AI Agent。

## 功能

- 流式输出，实时看思考过程
- 工具调用：shell / su / 读写文件 / 精确替换
- 会话持久化，支持历史恢复
- 方向键选择会话
- 危险命令确认，普通命令可一键放行
- 大输出自动落盘

## 依赖

```sh
pkg install python
pip install requests

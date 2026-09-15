#!/usr/bin/env python3
"""Termux AI Shell Agent — 模块化入口"""
import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import datetime

import tools
from config import WORKSPACE, MAX_HISTORY_PAIRS
from sessions import SessionStore
from prompts import probe_env, build_system_prompt, format_tool_inventory
from tui import select_session, StreamPrinter, print_history
from api import call_api_stream, trim_for_api


CMD_HELP = """
会话命令：
  /new            新建会话
  /list           列出所有会话
  /load [id]      加载会话（不带 id 弹出选择器）
  /del [id]       删除会话（不带 id 弹出选择器）
  /rename <name>  重命名当前会话
  /info           当前会话信息
  /history        查看当前会话历史
  /save           手动保存
  /dir            显示会话目录
  /tokens         查看本次运行 token 统计
  /tools          查看扫描到的工具清单
  /debug          切换工具调用调试输出
  /auto           切换普通命令自动放行（开关）
  /help           显示帮助
  exit / quit     退出

执行确认：
  y / yes         执行
  n / no / 回车   拒绝
  a / all         本次运行内普通命令不再询问（修改/删除类仍会确认）
  其他任何文字    作为反馈告诉模型（它会据此调整策略）
"""


def print_cmd_list(store):
    sessions = store.list_all()
    if not sessions:
        print("  (无保存的会话)")
        return
    print(f"\n  {'ID':<18} {'消息':<5} {'更新时间':<20} 名称/首条消息")
    print("  " + "-" * 72)
    for s in sessions[:50]:
        name = s["name"] or s["first"] or "(空)"
        print(f"  {s['id']:<18} {s['count']:<5} {s['updated']:<20} {name}")


def handle_empty_reply(msg):
    """content 为空时，根据 finish_reason 给出更明确的提示"""
    fr = msg.get("finish_reason")
    reasoning = msg.get("reasoning_content") or ""
    tool_calls = msg.get("tool_calls")

    if fr == "length":
        print("\n[警告] 输出被 max_tokens 截断")
        print(f"  reasoning 已用 {len(reasoning)} 字符，content 未能输出")
        print("  修复：把 api.py 里的 max_tokens 从 2048 提到 8192 或更高")
    elif fr == "tool_calls":
        if tool_calls:
            # 实际上有 tool_calls，不该到这
            print(f"\n[警告] finish_reason=tool_calls 但 content 为空，tool_calls={len(tool_calls)} 条")
        else:
            print("\n[警告] 模型请求调用工具但 tool_calls 未解析成功")
            print("  可能是流式分片丢失，重试一次即可")
    elif fr is None:
        print("\n[警告] 流式响应异常结束（finish_reason 缺失）")
        print("  可能网络中断。已获取 wakelock 了吗？")
    else:
        print(f"\n[警告] 模型没有返回内容，finish_reason={fr!r}")
        if reasoning:
            print(f"  reasoning 长度 {len(reasoning)} 字符")


def chat_loop():
    # ---- 后台常驻：阻止息屏后 Termux 被杀 ----
    locked = False
    try:
        subprocess.run(["termux-wake-lock"], capture_output=True, timeout=5)
        locked = True
    except Exception:
        pass

    print("=" * 60)
    print(" Termux AI Agent (模块化)")
    print("=" * 60)
    if locked:
        print(" 已获取 wakelock（退出时释放）")

    try:
        env = probe_env()
        print(f" 设备: {env['device']}  Android {env['android']}")
        print(f" 架构: {env['arch']}  内核: {env['kernel']}")
        print(f" Root: {'有' if env['root'] else '无'}   /sdcard: {'有' if env['sdcard'] else '无'}")
        print(f" 工具: 扫描到 {env['tools_total']} 个可执行文件")
        print(f" 工作区: {WORKSPACE}")
        print("=" * 60)

        store = SessionStore(WORKSPACE)
        print(f" 会话目录: {store.dir}")

        # 选会话
        session = None
        sessions = store.list_all()
        if sessions:
            print()
            try:
                choice = select_session(sessions, title="选择会话")
            except KeyboardInterrupt:
                print(" (未选择，新建会话)")
                choice = None

            if choice:
                loaded = store.load(choice)
                if loaded:
                    session = loaded
                    session["env"] = env
                    if session["messages"] and session["messages"][0]["role"] == "system":
                        session["messages"][0]["content"] = build_system_prompt(env)
                    print(f" 已恢复会话 {choice}（{len(session['messages'])} 条消息）")
                    print_history(session)
                else:
                    print(f" 会话 {choice} 不存在，将新建")
            else:
                print(" (未选择，新建会话)")

        if session is None:
            session = store.new_session(env, build_system_prompt(env))
            print(f" 新建会话 {session['id']}")

        print("=" * 60)
        print(" 输入 /help 查看命令，exit / quit 退出")
        print("=" * 60)

        MAX_ITER = 15
        stats = {"prompt": 0, "completion": 0, "cached": 0, "reasoning": 0}

        while True:
            try:
                user_input = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue

            # ---------- 会话命令 ----------
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd == "/help":
                    print(CMD_HELP)

                elif cmd == "/list":
                    print_cmd_list(store)

                elif cmd == "/tools":
                    print()
                    print(format_tool_inventory(
                        env.get("tools_total", 0),
                        env.get("tools_groups", {})
                    ))

                elif cmd == "/debug":
                    tools.set_debug(not tools.get_debug())
                    print(f" 工具调用调试: {'开' if tools.get_debug() else '关'}")

                elif cmd == "/auto":
                    tools.set_auto_allow(not tools.get_auto_allow())
                    print(f" 普通命令自动放行: {'开' if tools.get_auto_allow() else '关'}")

                elif cmd == "/new":
                    store.save(session)
                    session = store.new_session(env, build_system_prompt(env))
                    print(f" 新建会话 {session['id']}")

                elif cmd == "/load":
                    if arg:
                        loaded = store.load(arg)
                    else:
                        sessions_now = store.list_all()
                        if not sessions_now:
                            print("  (无会话)")
                            continue
                        try:
                            picked = select_session(sessions_now, title="加载会话")
                        except KeyboardInterrupt:
                            picked = None
                        loaded = store.load(picked) if picked else None

                    if not loaded:
                        print(" 会话不存在或已取消")
                        continue
                    store.save(session)
                    session = loaded
                    session["env"] = env
                    if session["messages"] and session["messages"][0]["role"] == "system":
                        session["messages"][0]["content"] = build_system_prompt(env)
                    print(f" 已加载 {session['id']}（{len(session['messages'])} 条消息）")
                    print_history(session)

                elif cmd == "/del":
                    if not arg:
                        sessions_now = store.list_all()
                        if not sessions_now:
                            print("  (无会话)")
                            continue
                        try:
                            picked = select_session(sessions_now, title="删除会话")
                        except KeyboardInterrupt:
                            picked = None
                        if not picked:
                            print(" (已取消)")
                            continue
                        arg = picked

                    if arg == session["id"]:
                        print(" 不能删除当前会话，先 /new 或 /load 别的")
                        continue
                    if input(f" 确认删除 {arg}？[y/N] ").strip().lower() == "y":
                        print(" 已删除" if store.delete(arg) else " 不存在")

                elif cmd == "/rename":
                    if not arg:
                        print(" 用法: /rename <新名称>")
                        continue
                    session["name"] = arg
                    store.save(session)
                    print(f" 已重命名为「{arg}」")

                elif cmd == "/info":
                    print(f" 会话 ID : {session['id']}")
                    print(f" 名称    : {session['name'] or '(未命名)'}")
                    print(f" 创建    : {session['created']}")
                    print(f" 更新    : {session['updated'] or '(未保存)'}")
                    print(f" 消息数  : {len(session['messages'])}")
                    print(f" 文件    : {store.path(session['id'])}")

                elif cmd == "/history":
                    print_history(session, max_show=50)

                elif cmd == "/save":
                    store.save(session)
                    print(f" 已保存到 {store.path(session['id'])}")

                elif cmd == "/dir":
                    print(f" {store.dir}")

                elif cmd == "/tokens":
                    print(f" 本次运行累计：")
                    print(f"   prompt tokens     : {stats['prompt']}")
                    print(f"   其中缓存命中      : {stats['cached']}")
                    print(f"   completion tokens : {stats['completion']}")
                    print(f"   其中 reasoning    : {stats['reasoning']}")
                    print(f"   合计              : {stats['prompt'] + stats['completion']}")

                else:
                    print(f" 未知命令: {cmd}，输入 /help 查看")

                continue

            if user_input.lower() in ("exit", "quit"):
                store.save(session)
                print(f" 已保存会话 {session['id']}")
                print(f" 本次 token: prompt={stats['prompt']} completion={stats['completion']} "
                      f"(cached={stats['cached']}, reasoning={stats['reasoning']})")
                break
            if not user_input:
                continue

            # ---------- 正常对话 ----------
            if not session["first_user_msg"]:
                session["first_user_msg"] = user_input

            session["messages"].append({"role": "user", "content": user_input})
            store.save(session)

            for iteration in range(MAX_ITER):
                api_messages = trim_for_api(session["messages"])
                printer = StreamPrinter()

                try:
                    msg = call_api_stream(api_messages, printer, stats=stats)
                except Exception as e:
                    print(f"\n[请求出错] {e}")
                    break

                printer.finish()
                tool_calls = msg.get("tool_calls")

                if tool_calls:
                    session["messages"].append({
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": tool_calls,
                    })

                    for tc in tool_calls:
                        result = tools.handle_one_tool_call(tc)

                        print("----- 结果 -----")
                        print(result if result.strip() else "(空)")
                        print("----------------")

                        session["messages"].append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })

                    store.save(session)
                    continue

                reply = msg.get("content") or ""
                if not reply:
                    handle_empty_reply(msg)

                session["messages"].append({"role": "assistant", "content": reply})
                store.save(session)
                break
            else:
                print(f"\n[已达最大迭代 {MAX_ITER} 次]")

    finally:
        # ---- 释放 wakelock ----
        if locked:
            try:
                subprocess.run(["termux-wake-unlock"], capture_output=True, timeout=5)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        chat_loop()
    except KeyboardInterrupt:
        print("\n已退出。")
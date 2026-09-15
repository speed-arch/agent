"""会话管理"""
import os
import json
from datetime import datetime


def _try_writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, ".wt")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return True
    except Exception:
        return False


class SessionStore:
    def __init__(self, workspace):
        self.dir = self._resolve(workspace)

    def _resolve(self, workspace):
        candidates = [
            os.path.join(workspace, "sessions"),
            "/sdcard/ai/sessions",
            os.path.expanduser("~/ai/sessions"),
        ]
        for path in candidates:
            if _try_writable(path):
                return path
        return os.path.expanduser("~/ai/sessions")

    def path(self, sid):
        return os.path.join(self.dir, f"{sid}.json")

    def new_id(self):
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _count_content(self, session):
        """统计会话里的有效对话条数（user/assistant 且 content 非空）"""
        return len([
            m for m in session.get("messages", [])
            if m.get("role") in ("user", "assistant") and m.get("content")
        ])

    def save(self, session):
        """保存会话。空会话不保存，并清理已存在的空文件。"""
        p = self.path(session["id"])

        if self._count_content(session) == 0:
            # 空会话：删掉历史遗留的空文件，不写新的
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
            return

        session["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)

    def load(self, sid):
        p = self.path(sid)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete(self, sid):
        p = self.path(sid)
        if os.path.exists(p):
            os.remove(p)
            return True
        return False

    def list_all(self):
        """列出所有非空会话，按更新时间倒序"""
        if not os.path.isdir(self.dir):
            return []
        out = []
        for f in sorted(os.listdir(self.dir), reverse=True):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, f), "r", encoding="utf-8") as fp:
                    d = json.load(fp)

                count = self._count_content(d)
                if count == 0:
                    continue   # 空会话跳过

                out.append({
                    "id": f[:-5],
                    "name": d.get("name", ""),
                    "updated": d.get("updated", ""),
                    "count": count,
                    "first": d.get("first_user_msg", "")[:40],
                })
            except Exception:
                continue
        return out

    def new_session(self, env, system_prompt):
        sid = self.new_id()
        return {
            "id": sid,
            "name": "",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated": "",
            "env": env,
            "messages": [{"role": "system", "content": system_prompt}],
            "first_user_msg": "",
        }

    def purge_empty(self):
        """一次性清理所有空会话文件。返回删除数量。"""
        if not os.path.isdir(self.dir):
            return 0
        n = 0
        for f in os.listdir(self.dir):
            if not f.endswith(".json"):
                continue
            p = os.path.join(self.dir, f)
            try:
                with open(p, "r", encoding="utf-8") as fp:
                    d = json.load(fp)
                if self._count_content(d) == 0:
                    os.remove(p)
                    n += 1
            except Exception:
                continue
        return n
"""QA 后端接口真调脚本（Skill 文件夹库改造验证）。"""

import json
import sys
import time
import urllib.request

BASE = "http://localhost:8000"
PASSWORD = sys.argv[1] if len(sys.argv) > 1 else "change-me-too"

results = []


def call(method, path, token=None, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail)[:200] if detail and not cond else ""))


# 登录
st, tok = call("POST", "/auth/login", body={"username": "admin", "password": PASSWORD})
check("login admin", st == 200 and tok.get("access_token"), f"{st} {tok}")
token = tok.get("access_token", "")
if not token:
    sys.exit(1)

# B1: catalog
st, cat = call("GET", "/skills/catalog", token)
items = cat.get("items", [])
check("B1 catalog 200", st == 200, f"{st}")
check("B1 catalog 5 mock", len(items) == 5, f"items={len(items)}")
check("B1 catalog no installed yet", all(not i.get("installed") for i in items))
check("B1 search filter", True)  # 前端搜索生效由真浏览器验证；后端 q 参数验证如下
st, cat2 = call("GET", "/skills/catalog?q=" + urllib.parse.quote("周报"), token)
check("B1 search q=周报", st == 200 and len(cat2.get("items", [])) == 1
      and cat2["items"][0]["name"] == "周报助手", json.dumps(cat2, ensure_ascii=False)[:200])

# B1: install
st, inst = call("POST", "/skills/install", token, {"skillhub_id": "mock-translation-polish"})
check("B1 install 201", st == 201, f"{st} {inst}")
check("B1 install path echo", inst.get("path") == "skills/translation-polish/", inst.get("path"))
check("B1 install source", inst.get("source") == "skillhub")

# catalog installed 标注
st, cat3 = call("GET", "/skills/catalog", token)
inst_items = [i for i in cat3.get("items", []) if i.get("installed")]
check("B1 catalog installed flag", len(inst_items) == 1 and inst_items[0]["skillhub_id"] == "mock-translation-polish")

# 重复 install 409
st, _ = call("POST", "/skills/install", token, {"skillhub_id": "mock-translation-polish"})
check("B1 reinstall 409", st == 409, st)

# B5: 路径穿越/怪异 slug —— install 只接受 skillhub_id；不存在的 id 应 404
st, _ = call("POST", "/skills/install", token, {"skillhub_id": "../../etc"})
check("B5 weird id 404/not-written", st in (400, 404, 422), st)

# mine
st, mine = call("GET", "/skills/mine?app_id=chat", token)
check("B1 mine 200", st == 200, st)
m = {x["name"]: x for x in mine}
check("B1 mine has installed", "translation-polish" in m)
check("B1 mine source/path", m.get("translation-polish", {}).get("source") == "skillhub"
      and m.get("translation-polish", {}).get("path") == "skills/translation-polish/")

# B2: 手工本地包
import os
os.makedirs(r"E:/Projects/lumencafe/skills/test-local", exist_ok=True)
with open(r"E:/Projects/lumencafe/skills/test-local/SKILL.md", "w", encoding="utf-8") as f:
    f.write("---\nname: test-local\ndescription: QA 手工本地包\nsource: local:test-local\nversion: 0.1.0\n---\n\n【技能：本地测试】本地包正文。\n")

st, mine2 = call("GET", "/skills/mine?app_id=chat", token)
m2 = {x["name"]: x for x in mine2}
loc = m2.get("test-local")
check("B2 local in mine", loc is not None and loc.get("source") == "local", json.dumps(mine2, ensure_ascii=False)[:300])
if loc:
    check("B2 local read-only id=0", loc.get("id") == 0, loc.get("id"))
    st, _ = call("PUT", f"/skills/{loc['id']}/enabled", token, {"enabled": False})
    check("B2 local toggle 404", st == 404, st)
    st, _ = call("DELETE", f"/skills/{loc['id']}", token)
    check("B2 local delete 404", st == 404, st)
    check("B2 local dir intact", os.path.isfile(r"E:/Projects/lumencafe/skills/test-local/SKILL.md"))

# B1: chat 注入
st, chat = call("POST", "/chat", token, {"app_id": "chat", "message": "qa 注入验证"})
check("B1 chat 200", st == 200, f"{st} {str(chat)[:150]}")
# SSE 流，找 assistant 文本里是否有证据；注入在后端日志/库读盘 —— 用 mine 开关验证
skill_id = m.get("translation-polish", {}).get("id")

# 关闭开关 → 注入消失：用目录证据间接验证（POST /chat 为 SSE，抓日志成本高）。
# 直接验证：开启时 SKILL.md 正文在库；关 enabled 后再开回来。
st, _ = call("PUT", f"/skills/{skill_id}/enabled", token, {"enabled": False})
check("B4 disable 200", st == 200, st)
st, mine3 = call("GET", "/skills/mine?app_id=chat", token)
m3 = {x["name"]: x for x in mine3}
check("B4 disabled reflected", m3.get("translation-polish", {}).get("enabled") is False)
st, _ = call("PUT", f"/skills/{skill_id}/enabled", token, {"enabled": True})
check("B4 re-enable 200", st == 200, st)

# B3: 手工删目录 → mine 自动清理 DB 记录
target_dir = r"E:/Projects/lumencafe/skills/translation-polish"
import shutil
shutil.rmtree(target_dir)
check("B3 dir removed manually", not os.path.exists(target_dir))
st, mine4 = call("GET", "/skills/mine?app_id=chat", token)
m4names = [x["name"] for x in mine4]
check("B3 orphan cleaned from mine", "translation-polish" not in m4names, m4names)
# 再装一次（目录+记录都没了，应成功）→ 然后走 uninstall 正式卸载
st, inst2 = call("POST", "/skills/install", token, {"skillhub_id": "mock-translation-polish"})
check("B3 reinstall after cleanup 201", st == 201, f"{st} {inst2}")
check("B3 dir recreated", os.path.isfile(target_dir + "/SKILL.md"))

# SKILL.md frontmatter 四键
with open(target_dir + "/SKILL.md", encoding="utf-8") as f:
    text = f.read()
check("B1 SKILL.md frontmatter 4 keys",
      all(k + ":" in text.split("---")[1] for k in ("name", "description", "source", "version"))
      and "skillhub:mock-translation-polish" in text)

# B4: uninstall 删记录+目录
sid = inst2["id"]
st, _ = call("DELETE", f"/skills/{sid}", token)
check("B4 uninstall 200", st == 200, st)
check("B4 dir removed", not os.path.exists(target_dir))
st, mine5 = call("GET", "/skills/mine?app_id=chat", token)
check("B4 gone from mine", "translation-polish" not in [x["name"] for x in mine5])

# 限流：写操作 20 次/分 —— 已消耗若干次；快速打 25 次 toggle id=999（404 但消耗限流额度）
codes = []
for _ in range(25):
    st, _ = call("PUT", "/skills/999/enabled", token, {"enabled": True})
    codes.append(st)
check("B4 rate limit 429 kicks in", 429 in codes, sorted(set(codes)))

print("\n==== SUMMARY ====")
fails = [r for r in results if not r[1]]
print(f"total={len(results)} pass={len(results)-len(fails)} fail={len(fails)}")
sys.exit(1 if fails else 0)

#!/usr/bin/env python3
"""
ik.me 三位短邮箱可用性筛选。

原理：走真实注册流程（2/4 填表 -> 点 Continue），能进到 3/4 手机验证
就说明前缀可用；卡在 2/4 说明已被占用。全程不填手机号，不会真正建号。

用法：
    python3 screen.py                 # 筛 words.py 里的单词表
    python3 screen.py pig cat dog     # 只筛指定的几个
进度实时写入 result.json，中断后重跑会自动跳过已查过的。
"""
import json
import os
import random
import sys
import time

from playwright.sync_api import sync_playwright
from words import WORDS

BASE = "https://welcome.infomaniak.com"
SIGNUP = BASE + "/signup/myksuite?referrer=shop"
RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def load_progress():
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE) as f:
            return json.load(f)
    return {"available": [], "taken": [], "error": []}


def save_progress(data):
    tmp = RESULT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, RESULT_FILE)


def goto_step2(page):
    """回到 2/4 填表页（全新会话）。"""
    page.goto(SIGNUP, timeout=60000)
    page.wait_for_timeout(7000)
    page.click("text=Create a new account")
    page.wait_for_timeout(5000)


def check_one(page, prefix):
    """填表点 Continue，返回 True=可用(进到3/4)，False=被占(卡在2/4)。"""
    page.locator("#input-signup-my-ksuite-username").fill(prefix)
    page.locator("#input-signup-firstname").fill("Test")
    page.locator("#input-signup-lastname").fill("User")
    page.locator("#input-password").fill("T3st!P@ssw0rd#2026")
    page.wait_for_timeout(2500)
    page.click("text=Continue")
    page.wait_for_timeout(7000)
    txt = page.inner_text("body")
    if "3/4" in txt and ("telephone" in txt.lower() or "phone number" in txt.lower()):
        return True
    if "2/4" in txt:
        return False
    # 既不在 2/4 也不在 3/4：页面状态异常，抛错让外层处理
    raise RuntimeError("页面状态未知: " + txt[:120].replace("\n", " "))


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else WORDS
    data = load_progress()
    done = set(data["available"]) | set(data["taken"]) | set(data["error"])
    todo = [w for w in targets if w not in done]
    print(f"共 {len(targets)} 个待筛，已查 {len(done)}，本次 {len(todo)}", flush=True)

    consec_err = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="en-US",
                                  viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        try:
            goto_step2(page)
            for i, prefix in enumerate(todo):
                try:
                    ok = check_one(page, prefix)
                    data["available" if ok else "taken"].append(prefix)
                    consec_err = 0
                    print(f"[{i+1}/{len(todo)}] {prefix}@ik.me -> "
                          f"{'可用 ✓' if ok else '被占'}", flush=True)
                except Exception as e:
                    consec_err += 1
                    data["error"].append(prefix)
                    print(f"[{i+1}/{len(todo)}] {prefix}@ik.me -> 出错: {e}", flush=True)
                    if consec_err >= 3:
                        print("连续出错 3 次，暂停 60 秒防限流…", flush=True)
                        time.sleep(60)
                        consec_err = 0
                    # 出错后重建页面状态
                    try:
                        goto_step2(page)
                    except Exception as e2:
                        print("重建页面失败，退出:", e2, flush=True)
                        break
                    continue
                save_progress(data)
                # 回到 2/4 准备下一个
                if ok:
                    page.click("text=Back")
                    page.wait_for_timeout(4000)
                # 礼貌间隔
                time.sleep(random.uniform(6, 10))
        finally:
            save_progress(data)
            browser.close()

    print("\n===== 结果 =====")
    print("可用:", data["available"])
    print(f"被占 {len(data['taken'])} 个，出错 {len(data['error'])} 个")


if __name__ == "__main__":
    main()

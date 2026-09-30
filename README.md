# ikme-check

筛选 `ik.me` 三位短邮箱前缀的可用性。

## 原理

走 Infomaniak 官方注册页的真实流程（`https://welcome.infomaniak.com/signup/myksuite`）：

1. 打开注册页，点 **Create a new account**，进入 2/4 填表页；
2. 填入待测前缀（如 `pig` → `pig@ik.me`），姓名密码随便填；
3. 点 **Continue**；
4. **能进到 3/4 手机验证页 → 该前缀可用**；卡在 2/4 不动 → 已被占用。

全程不填写手机号，账号不会真正创建。

> 技术细节：注册页的可用性接口是 `POST /api/web-components/1/register/my_ksuite/check_email`，
> 前面挡着 Altcha 验证码（SHA-256 PoW），且纯 HTTP 请求会被 WAF 掐连接，
> 因此改用 Playwright 驱动真实 Chromium 走页面流程，Altcha 在页面加载时自动解掉。

## 环境要求

- Python 3.10+
- Playwright + Chromium

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m playwright install-deps chromium   # 系统依赖（需 root）
```

## 用法

```bash
# 筛 words.py 里的全部单词（322 个，单进程约 1.5 小时）
python3 screen.py

# 只筛指定的几个
python3 screen.py pig cat dog

# 穷举全部 26^3=17576 种三位组合，8 并发（约 10 小时）
python3 screen.py --all --workers 8

# 穷举 + 跑完后把结果发到邮箱（经 Brevo，需 /root/wula/config/brevo.env）
python3 screen.py --all --workers 8 --email admin@hxsn.eu.cc

# 后台长期跑（推荐）
nohup python3 screen.py --all --workers 8 --email admin@hxsn.eu.cc > screen_full.log 2>&1 &
```

多进程时每个 worker 用独立浏览器、写 `result_w{i}.json`，全部结束后自动合并
进 `result.json` 并删除分片文件。中断重跑会自动跳过已查过的前缀（分块是确定性的）。

## 进度与断点续跑

- 单进程：每次检查完立即写入 `result.json`（`available` / `taken` / `error` 三组）；
- 多进程：每个 worker 写自己的 `result_w{i}.json`，结束后合并；
- 中断后重跑会自动跳过已查过的前缀；
- `result.json` 已加入 `.gitignore`，不会提交到仓库。

## 单词表

`words.py` 里是 322 个三位英文真实单词（`ace`、`fox`、`sky`……），想加自己的候选
直接往 `WORDS` 列表里追加，或用命令行参数指定。

## 注意事项

1. **不要高频跑**：每个 worker 每次检查间隔 6~10 秒随机等待，连续出错 3 次会自动暂停 60 秒。
   如果被限流，多等一会儿再重跑即可（进度都在）。
2. **并发别太大**：8 个并发的浏览器持续刷注册接口，在服务端眼里接近机器行为，
   有触发限流的可能。4C8G 的机器上 8 并发约占 4G 内存，是实用上限。
3. **注册新号需要手机号**：Infomaniak 注册要短信验证，一个手机号一般只能绑一个号，
   筛出可用的前缀后，准备好新手机号再去官网手动注册。
4. 填表用的姓名（Test User）和密码是占位的，不会产生任何真实账号。

/* 流光咖啡馆原型 v2 · 演示数据层
 * 数据结构对齐 docs/PRD-v1.md 契约：
 *  - 应用注册表：id/name/desc/color/icon/category/sort + 用户级覆盖（hidden/pinned）
 *  - 记账金额一律以「分」为单位（N7），展示层换算为元
 *  - 分类契约：{id, name, kind: expense|income|both, icon?, sort, built_in}
 */
window.LC_DATA = {
  user: { id: 1, username: "admin", nickname: "管理员", avatar: "A", roles: ["admin"], roleLabel: "管理员" },

  /* 应用分类（应用注册表 /apps/categories） */
  appCategories: [
    { id: "ai", name: "AI 应用" },
    { id: "life", name: "生活工具" },
    { id: "platform", name: "平台" }
  ],

  /* 应用注册表（GET /apps 返回的子集，含用户级覆盖） */
  apps: [
    {
      id: "chat", name: "AI 对话", icon: "chat", color: "#f0f6ff", ink: "#1664ff",
      desc: "通用 AI 助手：日常问答、写作辅助、学习解释，多轮会话自动保存",
      category: "ai", sort: 1, pinned: true, size: "big",
      tags: ["多轮对话", "DeepSeek-V3", "SSE 流式"]
    },
    {
      id: "money", name: "记账本", icon: "money", color: "#f0f6ff", ink: "#1664ff",
      desc: "一句话 AI 记一笔，按分类看清每月收支",
      category: "life", sort: 2, pinned: true, size: "big",
      tags: ["AI 记一笔", "本月 23 笔", "餐饮占比最高"]
    },
    {
      id: "papers", name: "文献", icon: "book", color: "#f2f3f5", ink: "#4e5969",
      desc: "PubMed 每日新文献跟踪（AD/PD/ALS），收藏、笔记与 AI 解读",
      category: "ai", sort: 3, pinned: true, size: "small", disabled: true, badge: "第二批"
    },
    {
      id: "admin", name: "平台管理", icon: "gear", color: "#f2f3f5", ink: "#4e5969",
      desc: "用户与角色、模型 Provider 管理",
      category: "platform", sort: 4, pinned: true, size: "small", adminOnly: true
    },
    {
      id: "apps", name: "应用中心", icon: "grid", color: "#f2f3f5", ink: "#4e5969",
      desc: "全部应用按分类浏览",
      category: "platform", sort: 5, pinned: true, size: "small", internal: true
    }
  ],

  /* 最近对话（GET /chat/conversations?app_id=chat） */
  conversations: [
    { id: 1, title: "润色一封措辞礼貌的邮件", updated: "今天 08:12" },
    { id: 2, title: "用大白话解释量子纠缠", updated: "昨天 22:40" },
    { id: 3, title: "帮我列一份周复盘提纲", updated: "昨天 09:05" },
    { id: 4, title: "出三道关于回调函数的练习题", updated: "10月12日" }
  ],

  /* 当前会话历史消息（GET /chat/history，升序，assistant 支持 markdown） */
  messages: [
    {
      role: "user",
      text: "帮我用 Python 写一个按月份归档账目的脚本，账目是 JSON 行格式，字段有 amount(分)、type、category、date。"
    },
    {
      role: "assistant",
      html:
        "<p>可以，按你的字段约定（金额以「分」存储）写一个最小可用的归档脚本：</p>" +
        '<div class="codeblock"><div class="codeblock-head"><span>archive.py</span>' +
        '<button type="button" data-copy><i class="ic" data-ic="copy"></i>复制</button></div>' +
        '<pre><code>import json, collections, pathlib\n' +
        "\n" +
        "def archive(src, out_dir):\n" +
        "    grouped = collections.defaultdict(list)\n" +
        "    for line in pathlib.Path(src).open(encoding='utf-8'):\n" +
        "        row = json.loads(line)\n" +
        "        grouped[row['date'][:7]].append(row)  # YYYY-MM\n" +
        "    for month, rows in grouped.items():\n" +
        "        path = pathlib.Path(out_dir) / f'{month}.jsonl'\n" +
        "        with path.open('a', encoding='utf-8') as f:\n" +
        "            for r in rows:\n" +
        "                f.write(json.dumps(r, ensure_ascii=False) + '\\n')\n" +
        "        print(f'{month}: {len(rows)} 笔')\n" +
        "\n" +
        "archive('transactions.jsonl', 'archive')</code></pre></div>" +
        "<p>两点说明：</p>" +
        "<p>1. 金额不做任何换算，原样保留「分」单位，避免浮点误差；</p>" +
        "<p>2. 追加模式（a）保证重复执行同一文件时 month 级幂等，不会丢账。需要我再加上按分类汇总导出 CSV 吗？</p>"
    }
  ],

  /* 流式演示文本：进入对话页时打字机播放 */
  streamDemo:
    "幂等性这点问得很好。这个脚本里我刻意没有做去重——归档只是搬运，重复 detection 应该放在入账那一层：写接口带 request_id，同一 request_id 重试时后端直接返回首次创建的记录。所以这里的追加模式是安全的：同一批账目最多被搬两次，不会被改写。",

  /* 记账分类（GET /money/categories，按 sort 升序） */
  moneyCategories: [
    { id: 1, name: "餐饮", kind: "expense", built_in: true, sort: 1 },
    { id: 2, name: "交通", kind: "expense", built_in: true, sort: 2 },
    { id: 3, name: "购物", kind: "expense", built_in: true, sort: 3 },
    { id: 4, name: "居住", kind: "expense", built_in: true, sort: 4 },
    { id: 5, name: "工资", kind: "income", built_in: true, sort: 5 },
    { id: 6, name: "咖啡", kind: "expense", built_in: false, sort: 6 }
  ],

  /* 最近账目（GET /money/transactions，倒序；金额单位：分） */
  transactions: [
    { id: 101, amount: 3200, type: "expense", category: "咖啡", note: "手冲耶加，两支豆子", date: "10-15" },
    { id: 102, amount: 18500, type: "expense", category: "购物", note: "秋季卫衣", date: "10-14" },
    { id: 103, amount: 2400, type: "expense", category: "交通", note: "地铁月卡充值", date: "10-13" },
    { id: 104, amount: 6800, type: "expense", category: "餐饮", note: "和朋友吃火锅 AA", date: "10-12" },
    { id: 105, amount: 800000, type: "income", category: "工资", note: "十月工资", date: "10-10" },
    { id: 106, amount: 15800, type: "expense", category: "居住", note: "电费 + 宽带", date: "10-09" }
  ],

  /* 月度统计（GET /money/stats/monthly?month=2026-10） */
  monthly: {
    month: "2026-10",
    expenseTotal: 234000,
    incomeTotal: 800000,
    balance: 566000,
    byCategory: [
      { name: "餐饮", total: 86000, count: 9 },
      { name: "购物", total: 62000, count: 3 },
      { name: "居住", total: 45000, count: 2 },
      { name: "交通", total: 28000, count: 4 },
      { name: "咖啡", total: 13000, count: 5 }
    ]
  },

  /* 近 6 个月趋势（GET /money/stats/trend?months=6），无数据月份补零 */
  trend: [
    { month: "2026-05", expense: 198000, income: 800000 },
    { month: "2026-06", expense: 246000, income: 800000 },
    { month: "2026-07", expense: 312000, income: 815000 },
    { month: "2026-08", expense: 221000, income: 800000 },
    { month: "2026-09", expense: 268000, income: 800000 },
    { month: "2026-10", expense: 234000, income: 800000 }
  ],

  /* 模型 Provider（GET /admin/models/providers，Key 已脱敏）
   * 一个条目 = 厂商 × 套餐（官方 API / Coding Plan 平级），各自独立 base_url + Key
   * 模型能力 meta：{context, vision, files} —— 驱动对话选择器与文件上传按钮显隐
   * remoteModels：调用官方 GET /models 的返回（平铺），原型用静态数据模拟 */
  providers: [
    {
      id: 1, name: "DeepSeek 官方 API", vendor: "deepseek",
      base_url: "https://api.deepseek.com/v1", enabled: true,
      has_key: true, key_mask: "••••f42a",
      models: [
        { name: "deepseek-chat", meta: "V3.2 · 128K 上下文", context: "128K", files: true, is_default: true },
        { name: "deepseek-reasoner", meta: "R1 · 64K 上下文", context: "64K" },
        { name: "deepseek-chat-250821", meta: "自定义 · 128K 上下文", context: "128K", files: true, custom: true }
      ],
      remoteModels: [
        { name: "deepseek-chat", meta: "V3.2 · 128K 上下文", context: "128K", files: true },
        { name: "deepseek-reasoner", meta: "R1 · 64K 上下文", context: "64K" }
      ]
    },
    {
      id: 2, name: "Moonshot Kimi 官方", vendor: "kimi",
      base_url: "https://api.moonshot.cn/v1", enabled: true,
      has_key: true, key_mask: "••••9c11",
      models: [
        { name: "moonshot-v1-8k", meta: "8K 上下文", context: "8K" },
        { name: "moonshot-v1-32k", meta: "32K 上下文", context: "32K" },
        { name: "moonshot-v1-128k", meta: "128K 上下文", context: "128K", vision: true }
      ],
      remoteModels: [
        { name: "moonshot-v1-8k", meta: "8K 上下文", context: "8K" },
        { name: "moonshot-v1-32k", meta: "32K 上下文", context: "32K" },
        { name: "moonshot-v1-128k", meta: "128K 上下文", context: "128K", vision: true }
      ]
    },
    {
      id: 3, name: "Kimi Coding Plan", vendor: "custom", custom: true,
      base_url: "https://coding-plan.moonshot.cn/v1", enabled: true,
      has_key: true, key_mask: "••••3d07",
      models: [
        { name: "kimi-k2-0905-preview", meta: "K2 · 256K 上下文", context: "256K", files: true, vision: true }
      ],
      remoteModels: []
    }
  ],

  /* 网关对外密钥（GET /admin/gateway-tokens；/gw/v1 鉴权，供 n8n 等外部工具接入） */
  gatewayTokens: [
    { id: 1, name: "n8n", mask: "sk-••••8f2a", scope: "全部模型", created: "2026-10-15", active: true }
  ],

  /* 角色与权限点（GET /admin/roles、/admin/permissions） */
  roles: [
    { id: 1, name: "admin", label: "管理员", permissions: ["app:chat", "app:money", "app:papers", "admin:users", "admin:models"], builtin: true },
    { id: 2, name: "member", label: "成员", permissions: ["app:chat", "app:money"], builtin: true }
  ],
  users: [
    { id: 1, username: "admin", nickname: "管理员", avatar: "A", roles: "admin", status: "启用",
      perms: { chat: true, money: true, users: true, models: true },
      lastActive: "今天 08:12", joined: "2026-10-01" },
    { id: 2, username: "user", nickname: "用户", avatar: "U", roles: "member", status: "启用",
      perms: { chat: true, money: true },
      lastActive: "3 天前", joined: "2026-10-12" }
  ]
};

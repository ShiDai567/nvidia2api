# 前端

Next.js 16 (App Router, Turbopack) + TypeScript + Tailwind CSS + lucide-react。

## 结构

```
frontend/
├── app/
│   ├── layout.tsx              # 根布局，挂载 <Toaster />
│   ├── page.tsx                # / → /dashboard
│   ├── login/page.tsx
│   ├── not-found.tsx
│   ├── globals.css             # 深色玻璃拟态底样式
│   └── (console)/
│       ├── layout.tsx          # 侧栏 + 鉴权守卫（未登录推回 /login）
│       ├── dashboard/          # 仪表盘 + Token 图表
│       ├── chat/               # 对话（流式 + 思考展示 + Token 统计）
│       ├── nvidia-keys/        # Key CRUD + 批量导入 + 测试 + 显隐
│       ├── proxies/            # 代理 CRUD/导入/一键检测/获取 IP + 启用上限
│       ├── proxy-groups/       # 分组 CRUD
│       ├── models/             # 列表/同步/启停
│       ├── api-keys/           # 用户 Key CRUD（rate_limit 0=不限）
│       ├── request-logs/       # 日志列表 + 展开竞速明细
│       └── settings/           # 运行时参数编辑器
├── components/
│   ├── ui.tsx                  # Card/Button/Badge/Modal/DataTable/Toggle/… + NvidiaLogo
│   └── toaster.tsx             # 全局 Toast；`toast.success/error/info(...)`
└── lib/api.ts                  # fetch 封装 + 类型 + token 管理
```

## 数据流

- `lib/api.ts` 的 `api.get/post/patch/del`：自动带 `Authorization: Token`，401/403 清空 token 并跳回登录
- 列表响应兼容 `{results: []}`、`{data: []}`、裸数组（`asList`）
- 错误归一到 `Error.message`（读 `error.message` 或 `detail`）

## 几个非显然的实现

**流式对话**（`chat/page.tsx`）：不用 fetch 的 SSE 库，直接 `reader.read()` + `\n\n` 分帧，自识别：

| 帧 | 动作 |
|---|---|
| `data: {"meta": …}` | 显示 Winner/线路/first_chunk |
| 普通 chunk | 累加 `delta.content` / `delta.reasoning_content`，原地重渲染 |
| `data: {"summary": …}` | 填入总耗时和 token 明细 |
| `data: {"error": …}` | 把错误写进气泡、toast 提示 |
| `data: [DONE]` | 结束 |

**思考内容**支持两种上游格式：`delta.reasoning_content` 字段、`<think>...</think>` 包裹在 content 里——两者都被剥成独立的可折叠区块。

**Token 图表**（仪表盘）：纯 SVG/CSS 柱状图，hover 查看明细，无第三方图表库。

**日志总行展开**：每行用 `Fragment key={request_id}` 包住两行 `<tr>`（数据 + 明细），不加 key 会触发 React 警告。

## 本地开发

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

后端默认 `http://127.0.0.1:8000`，跨端口走 `NEXT_PUBLIC_API_BASE_URL`。

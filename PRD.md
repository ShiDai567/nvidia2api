# nvidia2api 项目完整开发提示词

你现在是一名资深的全栈架构师、Python 后端工程师、Next.js 前端工程师以及高并发网络代理系统工程师。

请从零开始设计并实现一个名为 **nvidia2api** 的 AI API 聚合代理平台。

## 一、项目定位

项目名称：

**nvidia2api**

项目定位：

> 一个专门针对 NVIDIA AI API 的 API 聚合、代理加速、API Key 池管理、代理池管理以及 OpenAI API 兼容中转平台。

核心目标：

1. 管理多个 NVIDIA API Key。
2. 管理多个 SOCKS5 / HTTP / HTTPS 代理。
3. 自动获取 NVIDIA 可用模型。
4. 管理平台对外开放的模型。
5. 对外提供标准的 OpenAI Compatible API。
6. 用户可以通过平台生成的 API Key 调用模型。
7. 后端自动将请求分配到 NVIDIA API Key + 代理节点。
8. 多个线路并行发起请求。
9. 尽量避免同一个请求重复使用同一个 NVIDIA API Key。
10. 第一条线路获得正确响应后立即返回给用户，并取消其他仍在进行中的请求。
11. 提供完善的管理后台。
12. 使用 SQLite 作为数据库。
13. 项目必须具备真实可运行能力，而不是静态 Demo。

---

# 二、技术栈

请优先采用以下技术栈：

## 后端

* Python 3.12+
* Django
* Django REST Framework
* SQLite
* httpx
* asyncio
* Pydantic
* django-filter
* JWT / Token Authentication
* Python logging

如果 Django ASGI 环境适合，可以使用：

* Uvicorn
* ASGI
* asyncio

用于高并发 API 请求处理。

## 前端

* Next.js
* React
* TypeScript
* Tailwind CSS
* shadcn/ui
* Lucide Icons

前端要求：

* 深色科技感
* 简洁
* 专业
* 类似现代 AI SaaS 控制台
* 响应式布局
* 桌面端优先，同时兼容移动端

---

# 三、整体架构

项目采用前后端分离架构：

```text
nvidia2api
├── backend/
│   ├── Django
│   ├── API
│   ├── NVIDIA Key Manager
│   ├── Proxy Manager
│   ├── Model Manager
│   ├── Load Balancer
│   ├── Request Race Engine
│   ├── OpenAI Compatible API
│   └── SQLite
│
└── frontend/
    ├── Next.js
    ├── Dashboard
    ├── NVIDIA Keys
    ├── Proxies
    ├── Proxy Groups
    ├── Models
    ├── API Keys
    ├── Logs
    └── Settings
```

请保持模块化设计。

不要把所有逻辑写在 Django View 中。

核心业务逻辑应该拆分成 Service：

```text
services/
├── nvidia_service.py
├── nvidia_key_service.py
├── proxy_service.py
├── proxy_checker.py
├── proxy_pool.py
├── load_balancer.py
├── request_race.py
├── model_service.py
├── api_key_service.py
└── usage_service.py
```

---

# 四、NVIDIA API Key 管理

后台需要提供：

## NVIDIA API Key 列表

字段：

* ID
* 名称
* API Key
* 状态
* RPM 限制
* 当前分钟请求数
* 剩余可用次数
* 成功请求数
* 失败请求数
* 最后使用时间
* 创建时间
* 更新时间

默认：

```text
RPM = 40
```

前端明确显示：

```text
40 / 分钟
```

例如：

```text
Key名称：主账号-01
Key：nvapi-****************
限制：40/分钟
状态：正常
```

API Key 默认必须脱敏显示。

例如：

```text
nvapi-xxxxxxxxxxxxxxxxxxxx
```

管理员点击后可以显示完整 Key。

---

# 五、NVIDIA API Key 批量导入

提供：

**一键批量导入**

支持以下格式。

## 格式一

```text
name---key
```

例如：

```text
主账号01---nvapi-xxxxxxxx
主账号02---nvapi-yyyyyyyy
测试账号---nvapi-zzzzzzzz
```

## 格式二

```text
key
```

例如：

```text
nvapi-xxxxxxxx
nvapi-yyyyyyyy
nvapi-zzzzzzzz
```

如果只提供 Key：

自动生成名称：

```text
NVIDIA Key 001
NVIDIA Key 002
NVIDIA Key 003
```

要求：

* 一行一个 Key
* 自动去除空格
* 自动忽略空行
* 自动去重
* 检查格式
* 批量导入结果显示：

  * 成功数量
  * 重复数量
  * 无效数量
  * 失败数量

---

# 六、NVIDIA Key 限流

每一个 NVIDIA API Key 默认：

```text
40 requests / minute
```

系统必须实现服务端限流。

不能单纯依赖前端显示。

建议实现：

```text
Token Bucket / Sliding Window
```

每个 Key 独立统计。

状态：

```text
available
rate_limited
error
disabled
invalid
```

当某个 Key 达到限制时：

```text
暂时不要继续向该 Key 分配请求
```

并在下一分钟自动恢复。

如果 NVIDIA API 返回明显的限流状态，例如：

```text
429
```

应该：

1. 记录日志
2. 标记当前 Key 为 rate_limited
3. 计算合理的冷却时间
4. 暂时降低该 Key 的调度优先级
5. 不影响其他 Key 工作

---

# 七、模型管理

系统需要支持从 NVIDIA API 获取模型列表。

提供：

```text
同步模型
```

按钮。

同步后获取 NVIDIA 当前可用模型。

数据库保存：

```text
id
model_name
display_name
description
provider
status
enabled
created_at
updated_at
```

例如：

```text
模型名称：
meta/llama-3.3-70b-instruct
```

前端可以：

* 查看所有模型
* 搜索模型
* 添加模型
* 启用模型
* 禁用模型
* 删除模型
* 设置显示名称
* 设置描述

---

# 八、模型选择机制

不要默认把 NVIDIA 返回的所有模型都暴露给用户。

只有：

```text
enabled = true
```

的模型才可以通过 OpenAI API 调用。

例如：

```text
GET /v1/models
```

返回平台启用的模型。

返回结构必须尽量兼容 OpenAI：

```json
{
  "object": "list",
  "data": [
    {
      "id": "meta/llama-3.3-70b-instruct",
      "object": "model",
      "owned_by": "nvidia"
    }
  ]
}
```

---

# 九、代理管理

系统需要完整的代理池功能。

支持：

* SOCKS5
* HTTP
* HTTPS

代理格式：

```text
name---proxy
```

或者：

```text
proxy
```

例如：

```text
美国01---socks5://127.0.0.1:10001
日本01---socks5://127.0.0.1:10002
香港01---http://127.0.0.1:10003
```

也支持：

```text
socks5://127.0.0.1:10001
http://127.0.0.1:10002
https://127.0.0.1:10003
```

如果没有名称：

自动生成：

```text
代理 001
代理 002
代理 003
```

---

# 十、代理数据库结构

代理至少包含：

```text
id
name
protocol
host
port
username
password
group_id
country
region
city
enabled
status
latency
last_check_time
public_ip
success_count
failure_count
created_at
updated_at
```

密码等敏感字段必须安全存储。

前端显示时进行脱敏。

---

# 十一、代理分组

支持代理分组。

例如：

```text
美国
日本
香港
新加坡
欧洲
自定义代理组
```

一个代理只能属于一个主分组，也可以根据实际设计支持标签。

分组字段：

```text
id
name
description
country
enabled
created_at
updated_at
```

前端支持：

* 新建分组
* 编辑分组
* 删除分组
* 批量移动代理
* 按分组查看代理

---

# 十二、代理测速

后台提供：

**全部测速**

和：

**单条测速**

功能。

测试内容：

```text
连接是否成功
DNS 是否成功
TCP 延迟
HTTPS 延迟
总响应时间
```

结果：

```text
正常
超时
失败
```

例如：

```text
美国01
状态：正常
IP：1.2.3.4
延迟：182ms
```

测速应该采用异步并发方式。

不能因为测试一个代理导致整个后台阻塞。

需要：

```text
timeout
```

例如默认：

```text
10 秒
```

同时允许后台配置。

---

# 十三、获取代理公网 IP

支持：

**获取代理 IP**

通过代理访问可靠的 IP 查询服务。

获取：

```text
public_ip
country
region
city
isp
```

如果无法获取地理位置：

不要认为代理不可用。

只记录：

```text
public_ip
```

---

# 十四、代理启用 / 禁用

每个代理支持：

```text
启用
禁用
```

但是有一个非常重要的限制：

假设 NVIDIA API Key 数量：

```text
N
```

则：

```text
启用代理数量 <= N - 1
```

例如：

### 5 个 NVIDIA Key

最多：

```text
4 个代理
```

最终：

```text
4 个代理 + 1 个直连
= 5 条线路
```

### 10 个 NVIDIA Key

最多：

```text
9 个代理
```

最终：

```text
9 个代理 + 1 个直连
= 10 条线路
```

前端必须实时显示：

```text
NVIDIA Key：10
启用代理：7 / 9
直连线路：1
当前总线路：8
```

如果用户尝试启用超过限制的代理：

拒绝操作，并提示：

```text
当前 NVIDIA API Key 数量为 10，
最多允许启用 9 个代理。
```

注意：

**这个限制必须由后端强制执行，不能只依赖前端。**

---

# 十五、核心：请求调度系统

这是整个项目最核心的功能。

用户请求：

```http
POST /v1/chat/completions
```

例如：

```json
{
  "model": "meta/llama-3.3-70b-instruct",
  "messages": [
    {
      "role": "user",
      "content": "你好"
    }
  ]
}
```

平台接收到请求后：

```text
用户
 ↓
nvidia2api
 ↓
选择可用 NVIDIA API Key
 ↓
选择代理线路
 ↓
构造多个请求
 ↓
并行发送
 ↓
第一个获得正确响应
 ↓
立即返回用户
 ↓
取消其他请求
```

---

# 十六、线路概念

定义一个：

```text
Route
```

一条 Route =

```text
一个代理 + 一个 NVIDIA API Key
```

另外存在：

```text
Direct Route
```

即：

```text
直连 + 一个 NVIDIA API Key
```

例如：

```text
Route 1
Proxy: 美国01
Key: NVIDIA Key 01

Route 2
Proxy: 日本01
Key: NVIDIA Key 02

Route 3
Proxy: 香港01
Key: NVIDIA Key 03

Route 4
Proxy: None
Key: NVIDIA Key 04
```

---

# 十七、Key 与线路分配

一次请求开始时：

假设：

```text
NVIDIA Key = 5
启用代理 = 4
```

那么建立：

```text
5 条线路
```

每条线路使用不同的 NVIDIA API Key。

优先保证：

```text
一个请求内部：
一个 Key 最多被一个线路使用
```

也就是说：

```text
Route 1 -> Key 1
Route 2 -> Key 2
Route 3 -> Key 3
Route 4 -> Key 4
Route 5 -> Key 5
```

不要出现：

```text
Route 1 -> Key 1
Route 2 -> Key 1
Route 3 -> Key 1
```

---

# 十八、Key 轮换

不同用户请求之间，也要尽量避免总是使用同一个 Key。

实现：

```text
Round Robin
+
Least Recently Used
+
当前 RPM
+
失败率
+
冷却状态
```

综合调度。

优先选择：

```text
未达到 RPM
+
没有冷却
+
最近较少使用
+
成功率较高
```

的 Key。

---

# 十九、并行竞速请求

当用户发起一个请求时：

假设有：

```text
5 条线路
```

系统可以同时：

```text
Task 1 -> Proxy A + Key 1
Task 2 -> Proxy B + Key 2
Task 3 -> Proxy C + Key 3
Task 4 -> Proxy D + Key 4
Task 5 -> Direct + Key 5
```

并发执行。

不是：

```text
请求1失败
↓
请求2失败
↓
请求3
```

而是：

```text
请求1 ────────┐
请求2 ─────┐  │
请求3 ───┐ │  │
请求4 ─┐ │ │  │
请求5 ─┤ │ │  │
        ↓ ↓ ↓ ↓
      谁先成功谁返回
```

---

# 二十、成功判断

不能简单认为：

```text
HTTP 200 = 成功
```

需要定义：

```text
is_valid_response()
```

至少检查：

* HTTP 状态码
* 响应 JSON
* 是否存在有效 choices
* 是否存在有效 message / delta
* 是否存在 NVIDIA API 错误
* 是否为限流
* 是否为鉴权失败
* 是否为服务端异常

只有确认是：

```text
有效 AI 回复
```

才能作为 Winner。

---

# 二十一、Winner 机制

使用：

```text
asyncio.wait(
    tasks,
    return_when=asyncio.FIRST_COMPLETED
)
```

或者等价机制。

但是注意：

**第一完成的不一定是第一成功。**

因此逻辑必须是：

```text
Task 完成
 ↓
检查响应
 ↓
如果失败
   ↓
继续等待其他 Task

如果成功
   ↓
Winner
   ↓
立即返回
   ↓
取消其他 Task
```

---

# 二十二、取消其他请求

Winner 出现以后：

```text
cancel remaining tasks
```

并正确：

```text
关闭 HTTP 连接
释放连接池
释放 asyncio Task
释放代理连接
```

防止后台残留请求。

---

# 二十三、流式响应

必须支持：

```text
stream=true
```

例如：

```json
{
  "model": "xxx",
  "messages": [],
  "stream": true
}
```

需要兼容：

```text
text/event-stream
```

也就是 OpenAI 风格：

```text
data: {...}

data: {...}

data: [DONE]
```

流式模式下要特别处理：

### Winner 判定

不能等完整回答结束才判定。

应该：

```text
连接成功
 ↓
收到有效 SSE 数据
 ↓
确认是有效 AI 输出
 ↓
立即确定 Winner
 ↓
将后续 stream 转发给用户
```

其他线路立即取消。

---

# 二十四、非流式请求

对于：

```text
stream=false
```

逻辑：

```text
多个线路并发
 ↓
第一个获得完整且有效的 JSON 回复
 ↓
Winner
 ↓
返回用户
```

---

# 二十五、代理异常处理

代理可能出现：

```text
连接失败
DNS失败
CONNECT失败
TLS失败
超时
认证失败
代理不可用
```

这些错误：

**不能导致整个 API 请求失败。**

例如：

```text
Proxy A -> timeout
Proxy B -> success
Proxy C -> connection refused
Proxy D -> success
Direct -> success
```

只需要：

```text
A失败
C失败
B/D/Direct继续
```

最终：

```text
返回最快成功结果
```

---

# 二十六、NVIDIA Key 异常处理

如果某个 Key：

```text
401
403
429
5xx
timeout
```

分别记录。

例如：

```text
401
invalid_key

403
forbidden

429
rate_limited

5xx
server_error
```

不要因为一个 Key 失败而停止整个请求。

---

# 二十七、请求日志

后台必须提供：

**请求日志**

记录：

```text
request_id
用户 API Key
model
请求时间
请求耗时
使用线路
使用 NVIDIA Key
使用代理
代理 IP
HTTP 状态码
成功/失败
错误类型
是否 Winner
是否 Stream
输入 Token
输出 Token
总 Token
```

敏感数据不要完整记录。

尤其：

```text
用户 API Key
NVIDIA API Key
代理密码
Authorization
```

必须脱敏。

---

# 二十八、用户 API Key

平台需要支持：

**用户 API Key**

例如管理员创建：

```text
sk-nvidia2api-xxxxxxxx
```

用户通过：

```http
Authorization: Bearer sk-nvidia2api-xxxxxxxx
```

访问。

数据库：

```text
id
name
key_hash
key_prefix
enabled
rate_limit
total_requests
success_requests
failed_requests
last_used_at
created_at
updated_at
```

API Key 必须：

**只保存 Hash，不建议明文保存。**

创建时完整 Key 只显示一次。

---

# 二十九、OpenAI Compatible API

必须提供：

```text
GET /v1/models

POST /v1/chat/completions
```

并尽量兼容 OpenAI SDK。

例如 Python：

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-nvidia2api-xxxx",
    base_url="https://your-domain.com/v1"
)

response = client.chat.completions.create(
    model="meta/llama-3.3-70b-instruct",
    messages=[
        {
            "role": "user",
            "content": "你好"
        }
    ]
)

print(response.choices[0].message.content)
```

应该可以正常工作。

---

# 三十、API 错误格式

统一采用 OpenAI 风格：

```json
{
  "error": {
    "message": "No available NVIDIA API key",
    "type": "api_error",
    "param": null,
    "code": "no_available_key"
  }
}
```

HTTP 状态码正确。

例如：

```text
401 -> API Key 无效
403 -> API Key 被禁用
404 -> 模型不存在
429 -> 平台限流
500 -> 服务内部错误
502 -> 上游 API 错误
503 -> 当前没有可用线路
```

---

# 三十一、后台 Dashboard

首页显示：

```text
NVIDIA API Keys
12

Enabled Keys
10

Proxies
25

Enabled Proxies
9 / 11

Models
37

Enabled Models
18

Requests Today
12,381

Success Rate
98.7%

Average Latency
1.82s
```

再显示：

### 实时请求状态

```text
Active Requests
27
```

### Key 状态

```text
正常：9
限流：1
异常：1
禁用：1
```

### Proxy 状态

```text
正常：20
异常：3
禁用：2
```

---

# 三十二、前端页面

至少实现以下页面：

```text
/dashboard

/nvidia-keys

/proxies

/proxy-groups

/models

/api-keys

/request-logs

/settings
```

---

# 三十三、NVIDIA Key 页面

表格：

```text
名称
Key
状态
40/分钟
本分钟请求
成功率
最后使用
操作
```

操作：

```text
启用
禁用
编辑
删除
测试
```

顶部：

```text
+ 添加 Key
批量导入
刷新状态
```

---

# 三十四、代理页面

表格：

```text
名称
协议
地址
分组
公网 IP
国家
延迟
状态
启用
最后测速
操作
```

支持：

```text
批量导入
批量测速
批量启用
批量禁用
批量删除
移动分组
```

---

# 三十五、模型页面

显示：

```text
模型名称
显示名称
Provider
状态
启用状态
更新时间
```

按钮：

```text
同步 NVIDIA 模型
添加模型
启用
禁用
```

---

# 三十六、API Key 页面

支持：

```text
创建 API Key
删除 API Key
禁用 API Key
查看使用统计
```

创建：

```text
名称
备注
```

可以设置：

```text
请求频率限制
允许模型
```

---

# 三十七、请求日志页面

支持：

```text
时间筛选
模型筛选
状态筛选
API Key 筛选
线路筛选
代理分组筛选
```

显示：

```text
Request ID
时间
模型
耗时
Winner
代理
状态
Token
```

点击日志可以查看详细信息。

---

# 三十八、数据库设计

SQLite 数据库至少包含：

```text
AdminUser
NvidiaApiKey
ProxyGroup
Proxy
Model
UserApiKey
RequestLog
UsageRecord
SystemSetting
```

合理设计：

```text
ForeignKey
Index
UniqueConstraint
```

尤其对以下字段增加索引：

```text
NvidiaApiKey.status
NvidiaApiKey.last_used_at

Proxy.enabled
Proxy.status
Proxy.group_id

Model.enabled
Model.model_name

UserApiKey.key_hash

RequestLog.created_at
RequestLog.model
RequestLog.status
```

---

# 三十九、安全要求

这是 API 聚合平台，必须特别注意安全。

必须：

1. 所有 API Key 脱敏。
2. 用户 API Key 保存 Hash。
3. NVIDIA Key 不允许直接返回给普通用户。
4. 代理用户名密码加密保存。
5. 管理后台必须鉴权。
6. API 接口必须鉴权。
7. 防止 SQL 注入。
8. 防止 XSS。
9. 防止 CSRF。
10. 防止未授权访问后台。
11. 限制请求 Body 大小。
12. 限制并发数量。
13. 设置上游请求超时。
14. 防止无限重试。
15. 防止请求循环。
16. 日志不得记录完整 Authorization。
17. 日志不得记录完整 NVIDIA API Key。
18. 日志不得记录代理密码。

---

# 四十、并发与资源保护

必须防止：

```text
一个用户请求
→ N 条并发线路
```

造成资源耗尽。

需要配置：

```text
MAX_CONCURRENT_REQUESTS
MAX_CONCURRENT_UPSTREAM
UPSTREAM_TIMEOUT
CONNECT_TIMEOUT
READ_TIMEOUT
```

同时增加：

```text
Semaphore
```

保护系统。

例如：

```text
全局最大并发
单用户最大并发
单模型最大并发
```

都应该可以配置。

---

# 四十一、HTTP Client

建议使用：

```text
httpx.AsyncClient
```

并根据代理类型正确配置。

需要支持：

```text
http://
https://
socks5://
socks5h://
```

注意 SOCKS5 支持所需依赖。

连接池必须复用。

不要每一个请求都创建新的 HTTP Client。

---

# 四十二、代理健康状态

代理状态可以设计为：

```text
unknown
healthy
degraded
unhealthy
disabled
```

根据：

```text
成功率
延迟
最近错误
最后检测时间
```

动态判断。

连续失败可以：

```text
自动进入冷却
```

例如：

```text
连续失败 3 次
→ unhealthy
→ 60 秒冷却
```

冷却结束后重新检测。

这些参数放到系统配置里，不要写死。

---

# 四十三、智能线路调度

线路不是简单随机。

建议计算：

```text
score =
    latency_score
    + success_rate_score
    + key_availability_score
    + proxy_health_score
    + recent_usage_score
```

但是：

**竞速模式下仍然允许多个线路同时请求。**

调度算法主要用于：

```text
决定哪些 Key
+
哪些代理
进入本次竞速池
```

而不是限制最终并发。

---

# 四十四、请求 ID

每一个用户请求自动生成：

```text
request_id
```

例如：

```text
req_01JXXXXXX
```

整个生命周期都使用这个 ID：

```text
用户请求
↓
线路
↓
NVIDIA API
↓
日志
```

方便排查问题。

---

# 四十五、错误重试策略

不要无限重试。

针对不同错误采用不同策略：

```text
连接超时
→ 可以切换线路

代理失败
→ 换代理

429
→ 换 Key

401
→ 禁用/标记 Key

5xx
→ 可以尝试其他线路

模型不存在
→ 不应该重复竞速
```

---

# 四十六、核心请求流程

最终请求流程必须类似：

```text
POST /v1/chat/completions
        │
        ▼
验证用户 API Key
        │
        ▼
验证模型
        │
        ▼
检查用户限流
        │
        ▼
获取可用 NVIDIA Keys
        │
        ▼
获取可用代理
        │
        ▼
构建 Route
        │
        ▼
Key + Proxy 配对
        │
        ▼
启动并发任务
        │
        ├──── Proxy A + Key 1
        ├──── Proxy B + Key 2
        ├──── Proxy C + Key 3
        ├──── Proxy D + Key 4
        └──── Direct  + Key 5
                    │
                    ▼
              并行请求 NVIDIA
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
       失败                  成功
          │                   │
          │                   ▼
          │                Winner
          │                   │
          │                   ▼
          │             返回用户
          │                   │
          ▼                   ▼
      继续等待          取消其他 Task
```

---

# 四十七、重要：不要错误实现成串行重试

绝对不要实现：

```python
for route in routes:
    response = await request(route)
    if success:
        return response
```

这属于串行请求。

应该使用：

```text
asyncio
+
并发 Task
+
FIRST_COMPLETED
+
Winner
+
Cancel Remaining Tasks
```

实现真正的竞速请求。

---

# 四十八、流式请求特殊处理

对于：

```text
stream=true
```

必须使用：

```text
Async Streaming
```

不要把整个 NVIDIA 返回内容读取完以后才发送给用户。

正确：

```text
NVIDIA
 ↓
SSE Chunk
 ↓
nvidia2api
 ↓
用户
```

同时：

```text
第一条有效线路
→ Winner
→ 继续转发 Stream
→ 取消其他线路
```

---

# 四十九、OpenAI 兼容程度

尽可能兼容 OpenAI API。

至少支持：

```text
/v1/models

/v1/chat/completions
```

请求参数尽量透传：

```text
model
messages
temperature
top_p
max_tokens
stream
stop
frequency_penalty
presence_penalty
response_format
tools
tool_choice
```

对于 NVIDIA 不支持的参数：

不要无脑发送。

建立：

```text
Model Capability
```

机制。

---

# 五十、管理后台 API

后台 API 统一：

```text
/api/admin/
```

例如：

```text
GET    /api/admin/nvidia-keys
POST   /api/admin/nvidia-keys
POST   /api/admin/nvidia-keys/import
PATCH  /api/admin/nvidia-keys/{id}
DELETE /api/admin/nvidia-keys/{id}

GET    /api/admin/proxies
POST   /api/admin/proxies
POST   /api/admin/proxies/import
POST   /api/admin/proxies/test
PATCH  /api/admin/proxies/{id}
DELETE /api/admin/proxies/{id}

GET    /api/admin/models
POST   /api/admin/models/sync
PATCH  /api/admin/models/{id}

GET    /api/admin/api-keys
POST   /api/admin/api-keys
DELETE /api/admin/api-keys/{id}

GET    /api/admin/logs
GET    /api/admin/dashboard
```

---

# 五十一、配置管理

不要把重要参数写死。

使用：

```text
.env
```

例如：

```text
SECRET_KEY=
DEBUG=false

DATABASE_URL=sqlite:///db.sqlite3

NVIDIA_BASE_URL=

DEFAULT_NVIDIA_RPM=40

MAX_CONCURRENT_REQUESTS=100
MAX_CONCURRENT_UPSTREAM_REQUESTS=500

PROXY_TIMEOUT=10
UPSTREAM_CONNECT_TIMEOUT=10
UPSTREAM_READ_TIMEOUT=120

LOG_LEVEL=INFO
```

---

# 五十二、Docker

项目最终支持：

```text
docker compose up -d
```

运行。

提供：

```text
Dockerfile
docker-compose.yml
.env.example
```

SQLite 数据库需要挂载：

```text
./data:/app/data
```

防止容器删除以后数据丢失。

---

# 五十三、项目初始化

首次启动：

```text
python manage.py migrate
```

然后创建管理员。

可以提供：

```text
python manage.py createsuperuser
```

或者自行设计初始化命令：

```text
python manage.py init_admin
```

---

# 五十四、前端 UI 设计

整体风格：

**现代 AI Infrastructure / Developer Console**

不要做传统后台管理系统那种廉价感。

建议：

```text
深色背景
玻璃拟态
细边框
轻微渐变
卡片式布局
数据可视化
状态 Badge
Lucide Icons
```

但是不要过度使用动画。

重点是：

```text
专业
清晰
高性能感
科技感
```

---

# 五十五、Dashboard 视觉重点

顶部：

```text
nvidia2api
AI API Infrastructure
```

核心统计卡：

```text
NVIDIA Keys
Active Proxies
Available Models
Requests Today
```

中间：

```text
请求量趋势图
成功率
延迟
```

底部：

```text
实时线路状态
最近请求
Key 状态
Proxy 状态
```

---

# 五十六、代理池页面视觉

顶部显示：

```text
Proxy Pool

25 Total
18 Healthy
4 Degraded
3 Disabled

Enabled:
9 / 11
```

并提供：

```text
启用代理数量
最大允许数量
剩余可启用数量
```

例如：

```text
9 / 11

还可以启用 2 个代理
```

---

# 五十七、错误体验

所有操作都必须有：

```text
Loading
Success
Error
Empty
Confirm
```

状态。

例如批量导入完成：

```text
导入完成

成功：97
重复：2
无效：1
```

---

# 五十八、不要生成伪数据

开发过程中可以使用 Mock。

但是最终功能不能依赖：

```text
假数据
随机延迟
随机成功率
假 API
```

所有核心数据必须来自：

```text
SQLite
NVIDIA API
实际代理测试
真实请求日志
```

---

# 五十九、代码质量要求

代码必须：

* 模块化
* 类型明确
* 注释清晰
* 异常处理完善
* 日志完整
* 避免重复代码
* 不要把业务逻辑全部写在 View
* 不要把 SQL 到处散落
* 不要把配置写死
* 不要使用巨型函数
* 不要使用巨型 React Component

---

# 六十、测试

必须为核心逻辑编写测试。

至少测试：

### NVIDIA Key

```text
导入
去重
限流
禁用
冷却
```

### Proxy

```text
导入
格式解析
测速
启用限制
分组
```

### Load Balancer

测试：

```text
5 Keys + 4 Proxy
→ 5 Routes
```

以及：

```text
10 Keys + 20 Proxy
→ 最多 9 Proxy
→ 10 Routes
```

### Race Engine

测试：

```text
Route A 慢
Route B 快
Route C 失败
```

应该：

```text
B Winner
A/C Cancel
```

测试：

```text
Route A 失败
Route B 失败
Route C 成功
```

应该：

```text
C Winner
```

---

# 六十一、尤其测试并发安全

多个请求同时到达时：

```text
Request A
Request B
Request C
```

不能导致：

```text
同一个 Key
瞬间突破 40 RPM
```

需要确保限流计数具有并发安全性。

SQLite 环境下尤其注意：

```text
transaction
atomic update
database locking
```

如果 SQLite 在极高并发环境下存在天然瓶颈，应在代码和文档中明确说明，并为未来迁移 PostgreSQL 预留结构。

---

# 六十二、未来扩展

数据库和代码设计需要为未来支持：

```text
PostgreSQL
Redis
多个 NVIDIA Provider
多个上游 API
API Key 权重
代理权重
用户额度
计费系统
Token 统计
Webhook
Prometheus
Grafana
```

预留扩展能力。

但是当前版本：

**只使用 SQLite，不要为了未来需求引入不必要的复杂依赖。**

---

# 六十三、最终项目交付要求

最终必须生成完整项目：

```text
nvidia2api/
├── backend/
│   ├── manage.py
│   ├── config/
│   ├── apps/
│   ├── services/
│   ├── api/
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── hooks/
│   ├── types/
│   └── package.json
│
├── data/
│
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
└── LICENSE
```

---

# 六十四、README 必须包含

README 至少包含：

```text
项目介绍
功能介绍
技术栈
项目结构
环境要求
安装方法
数据库初始化
管理员创建
环境变量
启动后端
启动前端
Docker 部署
OpenAI API 使用方法
API Key 创建方法
NVIDIA Key 导入方法
代理导入方法
代理分组
模型同步
请求竞速机制
常见问题
```

---

# 六十五、开发方式

不要一次性生成大量互相不兼容的代码。

请按照以下顺序开发：

## Phase 1

项目基础架构：

```text
Django
Next.js
SQLite
Docker
```

## Phase 2

数据库：

```text
Models
Migrations
Admin
```

## Phase 3

NVIDIA Key：

```text
CRUD
批量导入
限流
状态
```

## Phase 4

Proxy：

```text
CRUD
批量导入
分组
测速
IP 获取
启用限制
```

## Phase 5

Models：

```text
NVIDIA Model Sync
模型管理
```

## Phase 6

User API Key：

```text
创建
鉴权
禁用
统计
```

## Phase 7

OpenAI Compatible API：

```text
/v1/models
/v1/chat/completions
```

## Phase 8

核心：

```text
Load Balancer
Route Manager
Race Engine
Winner
Cancellation
```

## Phase 9

Streaming：

```text
SSE
Stream Winner
Stream Cancellation
```

## Phase 10

Logs：

```text
Request Logs
Usage
Statistics
```

## Phase 11

Dashboard：

```text
实时状态
统计
图表
```

## Phase 12

测试：

```text
Unit Test
Integration Test
Concurrency Test
```

---

# 六十六、非常重要的实现原则

请严格遵守：

### 1.

不要把：

```text
代理数量
```

理解为：

```text
所有代理都参与一次请求。
```

只有：

```text
enabled proxy
```

才参与。

---

### 2.

不要让一个请求无限创建任务。

例如：

```text
1000 个代理
1000 个 Key
```

也不能一次请求启动 1000 个上游连接。

当前设计：

```text
启用代理数量 <= NVIDIA Key 数量 - 1
```

因此最多：

```text
N 条线路
```

---

### 3.

直连线路永远可以作为一条独立线路。

例如：

```text
10 Keys
9 Proxies
```

最终：

```text
9 Proxy Routes
+
1 Direct Route
=
10 Routes
```

---

### 4.

每一次请求尽量使用不同 Key。

例如第一次：

```text
Proxy A -> Key 1
Proxy B -> Key 2
Proxy C -> Key 3
Direct   -> Key 4
```

下一次可以：

```text
Proxy A -> Key 3
Proxy B -> Key 4
Proxy C -> Key 1
Direct   -> Key 2
```

避免固定：

```text
Proxy A 永远 Key 1
```

---

### 5.

不要因为某个线路失败而影响其他线路。

---

### 6.

不要把“最快连接建立”直接等同于 Winner。

必须获得：

```text
有效 AI 响应
```

才能成为 Winner。

---

### 7.

Winner 确定后必须及时取消其他任务。

---

### 8.

所有 Key / Proxy 的状态变化都必须记录日志。

---

### 9.

后端必须是最终规则执行者。

前端所有限制都不能替代后端校验。

---

### 10.

不要为了追求功能数量而牺牲核心请求链路的稳定性。

整个项目最重要的是：

```text
稳定
低延迟
正确的 Key 调度
正确的代理调度
正确的并发竞速
正确的流式响应
正确的错误处理
```

---

# 六十七、最终目标

完成之后，管理员可以：

```text
登录 nvidia2api
        ↓
导入 10 个 NVIDIA API Key
        ↓
导入 30 个代理
        ↓
设置代理分组
        ↓
测速
        ↓
选择 9 个代理启用
        ↓
同步 NVIDIA 模型
        ↓
启用需要的模型
        ↓
创建用户 API Key
```

最终用户只需要：

```text
Base URL:
https://your-domain.com/v1

API Key:
sk-nvidia2api-xxxx

Model:
NVIDIA 模型
```

即可通过标准 OpenAI SDK 使用。

每一次请求：

```text
用户
 ↓
nvidia2api
 ↓
选择多个不同 NVIDIA Key
 ↓
Proxy + Key 并行
+
Direct + Key
 ↓
竞速
 ↓
第一条有效响应
 ↓
Winner
 ↓
取消其他线路
 ↓
返回用户
```

请以这个目标作为整个系统的核心架构，不要偏离。

**现在开始从 Phase 1 开始实现，先完成项目目录、Django 后端、Next.js 前端、SQLite、Docker、基础配置以及数据库基础模型，然后逐阶段继续实现。每完成一个 Phase，都确保项目处于可运行状态，再进入下一阶段。**

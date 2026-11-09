# astrbot_plugin_rei_isittrue（绫波丽 · 是真的吗）

群聊事实核查插件，绫波丽主题版。引用一条消息，或 @机器人说出想核实的内容，AI 判断真假：

- 判定 `true` → 发送**绫波丽举绿勾**图片
- 判定 `false` → 发送**绫波丽举红叉**图片
- 无法核实 → 只回一句短文字

行为参考了 [konley/astrbot_plugin_isittrue](https://github.com/konley/astrbot_plugin_isittrue)（原版「是真的吗」），这一版重写为分层结构，并新增 DeepSeek 搜索 API、AnySearch API 等审查检索渠道。

## 触发方式

触发词由 `trigger_phrases` 配置，默认 `真的吗`。按优先级命中即停：

| # | 路径 | 条件 | 受开关控制 | 核查对象 |
|---|---|---|---|---|
| 1 | @机器人 + 触发词 | 消息 @ 了机器人且含触发词 | 否 | 引用消息（若有），否则本句去掉 @ 与触发词 |
| 2 | 引用 + 触发词 | 引用了一条消息且含触发词 | 否 | 被引用原消息；本句剩余文字作为「用户补充」 |
| 3 | 结尾监听 | 本句以触发词结尾（兼容 `？`/`?`） | `listen_suffix` | 本句去掉结尾触发词 |
| 4 | 开头监听 | 本句以触发词开头 | `listen_prefix` | 本句去掉开头触发词 |

- 只 @机器人、不带触发词**不会**触发。
- 支持文本、图片、合并转发；图片需要审查模型支持多模态，不支持会自动剥图重试。

## 回复示例

```text
……是假的。
……地球是球体，这是常识。
```

```text
……是真的。
……官方公告已发布该版本。
```

```text
……我不知道。
……资料不足，无法确认。
```

（第二条文字会附带对应图片；`……` 前缀是绫波丽模式的停顿，`persona=plain` 时会换成普通文案。）

## 配置项

### 基础

| 字段 | 默认 | 说明 |
|---|---|---|
| `cooldown` | 10 | 按用户 ID 的冷却秒数，0 不限制 |
| `trigger_phrases` | `["真的吗"]` | 触发词列表，可多个 |
| `listen_suffix` / `listen_prefix` | false | 无需 @ 的前后缀监听 |
| `group_blacklist` | `[]` | 不响应的群号 |
| `max_content_chars` | 2500 | 待核内容最大字符数 |
| `max_forward_depth` / `max_forward_nodes` / `max_forward_images` | 4 / 40 / 8 | 合并转发展开上限，防深层嵌套 |

### 审查模型

| 字段 | 默认 | 说明 |
|---|---|---|
| `review_backend` | `astrbot` | `astrbot` 用框架 Provider；`deepseek` 用下方 Key 直连 |
| `provider_id` | 空 | AstrBot Provider；留空用默认对话模型 |
| `provider_fallbacks` | `[]` | 模型回退链（Provider ID 列表） |
| `deepseek_api_key` | 空 | DeepSeek API Key（直连审查 + 默认搜索 Key） |
| `deepseek_base_url` | `https://api.deepseek.com` | OpenAI 兼容地址 |
| `deepseek_model` | `deepseek-flash` | 审查模型名 |
| `deepseek_timeout` | 60 | 直连超时秒数 |
| `enable_vision` | true | 是否把图片送模型 |

审查顺序：`deepseek` 直连（失败）→ 主 Provider → 回退链 → 默认 Provider。每个模型先带图，失败后剥图重试。

### 联网搜索

| 字段 | 默认 | 说明 |
|---|---|---|
| `enable_web_search` | true | 核查前是否检索资料 |
| `search_provider` | `auto` | 见下方渠道表 |
| `deepseek_search_key` | 空 | 留空复用 `deepseek_api_key` |
| `deepseek_search_count` | 5 | 返回条数 1–50 |
| `deepseek_search_content` | true | 是否抓取网页正文（`need_content`） |
| `anysearch_api_key` | 空 | AnySearch Key；匿名也可调用但有每日免费额度 |
| `anysearch_endpoint` | `https://api.anysearch.com/v1/search` | 接口地址 |
| `anysearch_zone` | 空 | `cn` / `intl` |
| `anysearch_language` | 空 | 例如 `zh-CN`、`en` |
| `max_search_results` | 5 | 每个查询展示条数 |
| `max_search_queries` | 2 | 最多搜索词数（1–3） |
| `search_timeout` | 30 | 单次搜索超时秒数 |
| `max_search_chars` | 2000 | 写进 prompt 的资料上限 |

#### 搜索渠道

| 渠道 | 实现 | Key |
|---|---|---|
| `deepseek` | `POST https://api.deepseek.com/v1/tools/search` | `deepseek_search_key` 或 `deepseek_api_key` |
| `anysearch` | `POST https://api.anysearch.com/v1/search` | `anysearch_api_key`（可匿名，有限额） |
| `tavily` | 读取框架 `provider_settings.websearch_tavily_key` | 框架配置 |
| `bocha` / `baidu_ai_search` / `brave` / `firecrawl` | 调用框架内置 `web_search_*` 工具 | 框架配置 |
| `none` | 关闭 | - |

`auto` 的降级顺序：框架配置的搜索渠道 → DeepSeek → Tavily → AnySearch → 其余内置工具。渠道失败、无 Key、空结果都会自动换下一个，最后回退为「仅凭模型知识判断」。

### 回复样式

| 字段 | 默认 | 说明 |
|---|---|---|
| `persona` | `rei` | `rei` 绫波丽口吻 / `plain` 普通口吻 |
| `true_label` | `……是真的。` | 判定为真文案 |
| `false_label` | `……是假的。` | 判定为假文案 |
| `unknown_label` | `……我不知道。` | 无法核实文案 |
| `send_verdict_image` | true | 真/假时附带举牌图片 |
| `true_image_path` / `false_image_path` | 空 | 自定义图片路径，留空用内置 `assets/` |
| `system_prompt` / `plan_prompt` | 空 | 留空用内置提示词 |

## 错误提示

| 情况 | 提示 |
|---|---|
| 图片被安全审核拦截 | ……图片被安全策略拦住了。换一张试试。 |
| 限流 / 429 / 额度 | ……太吵了，被限流了。等一会儿再问。 |
| 超时 | ……没有回应。稍后再试。 |
| 上下文过长 | ……内容太长了，做不到。精简一下。 |
| Key 无效 / 401 | ……钥匙不对。检查一下 API Key。 |
| 余额不足 / 402 | ……额度不够了。 |
| 其它 | ……判断失败。稍后再试。 |

## 安装

1. 把 `astrbot_plugin_rei_isittrue` 整个目录放到 `AstrBot/data/plugins/`。
2. 在 WebUI 插件页重载插件。
3. 按需填写 `deepseek_api_key` / `anysearch_api_key`，或保留 `astrbot` 用框架自带模型。

要求 AstrBot >= 4.10.4。无额外第三方依赖，HTTP 使用 AstrBot 自带的 `aiohttp`。

## 文件结构

```
astrbot_plugin_rei_isittrue/
├── main.py                 # 事件入口、冷却、消息发送
├── metadata.yaml
├── _conf_schema.json
├── logo.png                # 绫波丽绿勾图
├── assets/
│   ├── verdict_true.png    # 判定为真
│   └── verdict_false.png   # 判定为假
├── core/
│   ├── config.py           # 配置解析
│   ├── chain.py            # 消息组件识别
│   ├── triggers.py         # 触发词匹配
│   ├── content.py          # 引用 / 图文 / 合并转发提取
│   ├── prompts.py          # 系统与规划提示词
│   ├── planner.py          # 检索规划
│   ├── search.py           # DeepSeek / AnySearch / Tavily / 内置工具
│   ├── llm.py              # 审查模型与回退链
│   ├── verdict.py          # 三态解析与文案
│   ├── render.py           # 图片 + 文字消息链
│   ├── errors.py           # 友好错误
│   └── pipeline.py         # 流程编排
└── tests/
    ├── test_core.py
    └── test_services.py
```

## 自测

```bash
python tests/test_core.py
python tests/test_services.py
```

覆盖：配置默认值与非法值、四条触发路径、英文词边界、三态解析（含中文/包裹格式/重复判定词）、绫波丽与普通文案、判定图片选择与开关、引用/当前消息/合并转发提取与截断、规划解析与兜底救援、DeepSeek 搜索请求与解析、AnySearch 请求与业务错误、自动降级、Tavily 无 Key、审查模型直连/回退链/剥图降级、无模型报错、整体流程与错误提示、空内容静默。

## 说明与限制

- 判定为真/假的图片来自用户提供的绫波丽同人图；如需更换直接替换 `assets/` 下文件或填自定义路径。
- DeepSeek 搜索按请求次数计费（官方文档：每 1000 次成功请求 5 元），只有成功返回结果才计费。
- AnySearch 支持匿名调用，但会按 IP 限流并消耗每日免费额度；长期使用建议填 Key。
- 合并转发的远程展开依赖协议端 `get_forward_msg`，失败时只使用本地可见内容。
- 事实核查依赖模型与检索质量，结论仅供参考。

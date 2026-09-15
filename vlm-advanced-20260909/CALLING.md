# 图片理解 API 调用方法

适用于本次实际测试的 **Galbot 网关**，不是各模型厂商原生 API。请使用现有 `api_key.json`；不要把网关密钥发到 Google、阿里云、火山引擎或 OpenAI 官方 API 地址。

## 1. 无额外依赖的调用（推荐）

交付包中的 `tools/vlm_client.py` 只依赖 Python 3 标准库，Windows 和 Linux 均可用。默认读取脚本上级目录的 `api_key.json`，也可显式指定 `--config`。密钥不包含在交付包中。

在项目/解压目录执行（Windows 可将 `python3` 换成 `python`）：

```bash
python3 tools/vlm_client.py --config api_key.json --model gemini-3.5-flash --image vlm-advanced-20260909/assets/photo.png --prompt "请描述图片中的物体、数量、位置和相互关系；不要推测拍摄时间等不可见信息。"
python3 tools/vlm_client.py --config api_key.json --model qwen3.7-plus --image vlm-advanced-20260909/assets/ui.png --prompt "哪个实例被选中？满足至少24GB显存且可用的最便宜实例是哪个？为什么启动按钮不可用？"
python3 tools/vlm_client.py --config api_key.json --model doubao-seed-2-1-pro --image vlm-advanced-20260909/assets/chart.png --prompt "读取图例和各季度销量，计算两组全年总销量，说明趋势。"
python3 tools/vlm_client.py --config api_key.json --model doubao-seed-2-1-turbo --image vlm-advanced-20260909/assets/before.png --image vlm-advanced-20260909/assets/after.png --prompt "第一张是变化前，第二张是变化后。哪些物体移动、消失？给出变化前后格子坐标。"
```

输出包含 `response`（模型答案）、`seconds`（完整请求耗时）、`http_status`、`finish_reason` 和 `usage`。HTTP 失败、空答案或 `finish_reason=length` 时命令以非零状态退出；不要把截断结果当成完整答案。默认 2048 输出预算，可用 `--max-output-tokens 4096` 调整。默认 socket 超时 55 秒，不自动重试；这不是严格的整个请求总时限。

## 2. 在 Python 项目里调用

从项目目录运行，或把 `vlm_client.py` 放到应用可导入的位置：

```python
from tools.vlm_client import VLMClient

client = VLMClient("api_key.json", timeout=55)
result = client.understand(
    model="gemini-3.5-flash",  # 可换成通过测试的 Qwen / Doubao 等网关别名
    images=["vlm-advanced-20260909/assets/photo.png"],
    prompt="请详细描述图片内容。把可见事实与不确定推测分开。",
    max_tokens=2048,
)
if not result["api_response_ok"] or result.get("finish_reason") == "length":
    raise RuntimeError(result.get("error", "模型输出为空或已截断"))
print(result["response"])
```

## 3. HTTP 请求结构

请求到配置中的 `BASE_URL` 加 `/v1/chat/completions`（若已含 `/v1` 则不重复追加），认证头为 `Authorization: Bearer <API_KEY>`。

```json
{
  "model": "gemini-3.5-flash",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "请理解图片并回答问题。"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,<图片Base64>"}}
    ]
  }],
  "max_tokens": 2048,
  "stream": false
}
```

多图：在同一 `content` 数组中追加多个 `image_url`。本地文件路径不能直接作为网关可访问 URL；脚本会读取本地 PNG/JPEG/WebP 并编码成 Data URI。无需将用户图片上传到公开图床。本客户端为控制请求体，对单图设置 10 MB 本地上限；这不是对所有上游厂商最大限制的声明。

GPT 路由使用 `max_completion_tokens` 替代 `max_tokens`，并设置 `reasoning_effort="low"`；这是已核对的 Chat Completions 参数差异。该预算包含可见输出与推理 token，不能理解为必然产生同样多的答案文字。[OpenAI 官方参数文档](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create)

主测试其他路由保留网关默认思考设置。只有豆包 Pro 的补测实际验证了下面的 `thinking` 参数；不要假定 `enable_thinking`、`thinking_budget`、`media_resolution` 在此网关均被支持。

### 豆包 Pro 快速模式（实测有效，但不是无损加速）

```bash
python3 tools/vlm_client.py --config api_key.json --model doubao-seed-2-1-pro --disable-thinking --image vlm-advanced-20260909/assets/photo.png --prompt "请描述可见物体及数量，不能确定的信息返回未知。"
```

等价的额外 HTTP 字段：

```json
"thinking": {"type": "disabled"}
```

这是添加到原有请求对象的字段片段，不是单独完整的请求体。Python 调用时传 `client.understand(..., disable_thinking=True)`。此开关只允许用于 Doubao 路由，不会静默套用到 GPT/Gemini/Qwen。

本轮 Pro 快速模式四题中位数 2.837 秒、27/28 个字段正确；默认模式两项超时，双图延长超时后 83.528 秒答对。快速模式界面题把 Busy 的 A17 错当成满足 Ready 条件，因此对复杂条件判断应保留复核。若需要默认思考，可不加开关并设置 `--timeout 120`；这只延长等待，不会提升推理速度。计划执行超过一分钟的 Linux 任务请使用 tmux。

## 4. 使用边界

- Google 官方列明 Gemini 3.5 Flash 支持图片输入、文本输出；本测试调用的是网关同名路由。[Google 模型说明](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)
- Qwen 官方视觉文档给出了 `image_url`、Base64 和多图调用方法；网关模型名以本次 `/v1/models` 和实测结果为准。[Qwen 视觉理解文档](https://help.aliyun.com/zh/model-studio/vision)
- 网关可跨模型乃至跨厂商自动回退。请求名、返回 `model` 字段都不能独立证明实际后端身份；不要据此声称测到了原厂独占性能。
- 未验证官方直连密钥、计费单价、SLA、所有上下文长度、视频或实时流式能力；本轮聚焦图片理解。
- 自动化使用时校验 JSON 字段和数值，不要只看 HTTP 200；对关键判断保留人工复核。
- 对结构化提取允许字段为 null，并明确“图片缺失、模糊或内容不可见时禁止猜测”。本轮无图对照发现部分路由会编造读数，完整 JSON 不是存在视觉证据的保证。

## 5. 复现实验

已附全部图片、题目、标准答案和逐请求结果。只有重建合成图片需要 Pillow；实际调用及重新评分无第三方依赖。

```bash
python3 tools/test_vlm_client.py
python3 tools/benchmark_vlm_advanced.py --config api_key.json --output-dir vlm-advanced-20260909 --run-name repeat-01
```

第二条会产生新的计费 API 请求，不能与已有 run-name 重名。Linux 上预计超过一分钟，遵循项目要求放在 tmux 中：

```bash
tmux new-session -d -s vlm-repeat-0909 'cd /home/lidanshi/lizekai/AgentM && set -o pipefail && python3 -u tools/benchmark_vlm_advanced.py --output-dir vlm-advanced-20260909 --run-name repeat-01 2>&1 | tee -a vlm-repeat-20260909.log'
```

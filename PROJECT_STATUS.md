# SnapFlow 当前进度

更新：2026-09-16。

## 当前版本

- Windows 安装目录版本：`SnapFlow-Windows-ConfigFix-20260914-165159`。
- 最新代码内部版本：`windows-networkfix-20260916`。
- 最新安装包及摘要位于 `deliverables/snapflow/`，指针为 `LATEST.json`。
- 当前代码支持 Gemini 网关路由 `gemini-3.8-flash`；实际密钥仅保存在用户机器，仓库和安装包不携带。

## 已实现

- 页面内浏览磁盘和文件夹，明确授权后读取该目录中的截图。
- 后台每 3 秒检查新增和修改的 PNG/JPG/WebP 文件，等待写入稳定、按内容去重，支持暂停、继续和撤销。
- 任务、待办、作业、日程、灵感、资料分类；自动保存可靠结果，缺信息的事项留待核对。
- 批量上传、结果编辑、飞书任务和日历连接入口、日历文件导出。
- 旧版本模型配置继承、独立配置保存、启动诊断及可用端口选择。
- 移除用户指定的三句首页提示。

## 最新用户反馈与验收顺序

用户在收到一键修复后反馈“终于可以了”。这是用户侧恢复可用的反馈；尚未提供具体识别结果或返回诊断，因此不据此声称所有截图、实际连接路径或飞书同步均已验收。下一步不要求重复安装或重复配置。

1. 先在已授权文件夹的最外层放入一张从未处理过的新截图，确认不点击上传也会产生记录或待核对事项。
2. 自动新增通过后，再检查不同类型截图、重复内容与重启后授权保留。
3. 接通真实飞书账号，分别验收一条任务和一个日程；核对时间、目标和重复创建。
4. 最后收敛启动/更新入口与错误提示，完成 Windows 可持续使用的交付验收。

## 本次修复交付

- 用户明确要求减少操作，已实现单文件 `SnapFlow-Repair.cmd`：检测已知安装、备份并校验旧代码、更新 20 个运行文件、保留私有配置和用户数据、打开应用、自动检测连接，并至多重试一张此前失败的截图。
- Windows 在线检查成功，但 SSH 与 WinRM 入口拒绝连接，无法从开发机直接执行修复。`SnapFlow-Repair.cmd` 已于 2026-09-16 09:31:10（开发机日志时间）通过 Tailscale 发送成功；随后用户反馈“终于可以了”；具体执行诊断与持续处理结果尚未收集。
- 已实现默认网络/直连预检，可选复用既有 `ds4090-ts` SSH 转接。只转接已指定网关，严格主机信任和网关 TLS 校验，无新环境安装或系统代理修改；后台退出时关闭自己启动的 SSH 进程，强制终止进程仍需留意残留子进程。
- 页面不再把配置存在显示为“已连接”；提供检测入口，区分配置、检测和识别状态。
- 116 项离线检查、12 组 Chrome 交互通过；完整更新器再次通过 3 项备份/回滚检查。见 `snapflow/verification/network-repair-20260916/REPORT.md`。
- 开发机模型列表 HTTP 200 且包含 `gemini-3.8-flash`；网关解析为内网地址。转接 TLS 冒烟 HTTP 401，保留证书验证；没有新增模型调用。目标 Windows 的 SSH 自动登录、截图识别和持续监测仍未验证。

## 已有验证

2026-09-14 的最新功能回归：102 项后端/HTTP/启动检查、12 组 Chrome 离线交互通过。持续监测线程已在离线测试中覆盖新增、修改、写入稳定、暂停和撤销。具体结果见 `snapflow/verification/album-agent-20260914/REPORT.md`。

Windows 更新入口已通过 Tailscale 发送；传输成功不代表用户已运行更新，也不代表目标 Windows 的完整流程已验收。

## 当前阻塞与下一步

1. 用户的 `测试1.jpg`、`测试2.jpg`、`测试3.jpg` 很快出现“外部服务暂时无法连接或响应无效”。2026-09-16 用户提供 Windows Python 3.12 独立无凭据连接检查的完整异常：`urllib.error.URLError` 包装 `ssl.SSLEOFError: UNEXPECTED_EOF_WHILE_READING`，发生在 `do_handshake()`。这次检查在 TLS 握手完成前被断开，尚未收到 HTTP 响应；它不是证书校验失败的证据，也不能判断密钥是否有效。应用请求是否同因仍需修复后的实际识别验证。
2. 开发机对网关 `/v1/models` 的无凭据连接检查返回 HTTP 401，证明开发机能完成 HTTPS 连接；不能据此推断 Windows 网络或密钥正常。
3. 2026-09-16 请求级直连对比已有结果：用户使用 `ProxyHandler({})` 后，`socket.create_connection()` 中的 `sock.connect(sa)` 抛出 `TimeoutError: timed out`，最终包装为 `URLError`。这次连接在 TCP 阶段超时，尚未进入 TLS。此前默认路径在 TLS 阶段断开，两种模式都没有取得 HTTP 响应；不能把“关闭代理”直接当作修复，也不能仅凭此断定必须使用 VPN、网关宕机或密钥错误。请求级禁用自动代理不保证绕过系统 VPN、透明代理或网络过滤。
   - 先前人工诊断方案（现已由双击修复取代）：Windows 执行 `Resolve-DnsName llm-gateway.galbot.com -Type A` 检查解析结果；用 `curl.exe -q -I --connect-timeout 10 --max-time 15 https://llm-gateway.galbot.com/v1/models` 对比另一客户端。`-q` 必须作为首个选项，避免读取 curl 默认配置；不传密钥、不关证书校验、不改系统设置。
   - curl 与 Python 默认代理发现机制并不相同，结果差异仅用于缩小范围，不单独证明 Python 或代理是根因。HEAD 的 HTTP 状态也不等同于模型调用是否成功。根据结果再核对实际代理/VPN及网关的访问条件，不反复调用模型或声称已修复。
4. 真实飞书账号的任务创建、日程创建、时间及幂等性仍待用户授权后的端到端验收。

异常语义和请求级代理设置依据：[Python 3.12 SSL 文档](https://docs.python.org/3.12/library/ssl.html#ssl.SSLEOFError)、[ProxyHandler 文档](https://docs.python.org/3.12/library/urllib.request.html#urllib.request.ProxyHandler)。后续已新增上述运行时修复与一键交付；真实成功须以 Windows 返回结果为准。

## 当前需要用户的一步

保持应用后台和 Tailscale 运行，将一张新的聊天通知截图放进已授权文件夹的最外层，不使用页面上传。确认页面是否自动生成记录或待核对事项；有问题只需描述现象，不要求继续手写诊断命令。

## 开发验证

在项目根目录运行离线测试，不需要真实 API 密钥：

```bash
SNAPFLOW_TEST_OUTPUT="$PWD/tmp/local-tests" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s snapflow/tests -p 'test_*.py'
```

测试和浏览器产物留在 `tmp/`；涉及本机 HTTP 服务的检查需要环境允许监听回环地址。旧模型报告是历史证据，不代表每次代码修改都重新进行了真实模型检验。

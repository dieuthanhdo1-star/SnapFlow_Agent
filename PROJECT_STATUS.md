# SnapFlow 当前进度

更新：2026-09-16。

## 当前版本

- Windows 安装目录版本：`SnapFlow-Windows-ConfigFix-20260914-165159`。
- 最新代码内部版本：`windows-folderwatch-20260914`。
- 最新安装包及摘要位于 `deliverables/snapflow/`，指针为 `LATEST.json`。
- 当前代码支持 Gemini 网关路由 `gemini-3.8-flash`；实际密钥仅保存在用户机器，仓库和安装包不携带。

## 已实现

- 页面内浏览磁盘和文件夹，明确授权后读取该目录中的截图。
- 后台每 3 秒检查新增和修改的 PNG/JPG/WebP 文件，等待写入稳定、按内容去重，支持暂停、继续和撤销。
- 任务、待办、作业、日程、灵感、资料分类；自动保存可靠结果，缺信息的事项留待核对。
- 批量上传、结果编辑、飞书任务和日历连接入口、日历文件导出。
- 旧版本模型配置继承、独立配置保存、启动诊断及可用端口选择。
- 移除用户指定的三句首页提示。

## 已有验证

2026-09-14 的最新功能回归：102 项后端/HTTP/启动检查、12 组 Chrome 离线交互通过。持续监测线程已在离线测试中覆盖新增、修改、写入稳定、暂停和撤销。具体结果见 `snapflow/verification/album-agent-20260914/REPORT.md`。

Windows 更新入口已通过 Tailscale 发送；传输成功不代表用户已运行更新，也不代表目标 Windows 的完整流程已验收。

## 当前阻塞与下一步

1. 用户的 `测试1.jpg`、`测试2.jpg`、`测试3.jpg` 很快出现“外部服务暂时无法连接或响应无效”。说明任务进入处理流程，但 Windows 端请求失败的具体原因未确定。
2. 开发机对网关 `/v1/models` 的无凭据连接检查返回 HTTP 401，证明开发机能完成 HTTPS 连接；不能据此推断 Windows 网络或密钥正常。
3. 已提供 Windows Python 单行连通性检查，等待具体输出。下一步根据 DNS、代理、TLS 或 HTTP 结果定位；不要未经诊断反复调用模型、自动重试或声称已修复。
4. 真实飞书账号的任务创建、日程创建、时间及幂等性仍待用户授权后的端到端验收。

## 开发验证

在项目根目录运行离线测试，不需要真实 API 密钥：

```bash
SNAPFLOW_TEST_OUTPUT="$PWD/tmp/local-tests" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s snapflow/tests -p 'test_*.py'
```

测试和浏览器产物留在 `tmp/`；涉及本机 HTTP 服务的检查需要环境允许监听回环地址。旧模型报告是历史证据，不代表每次代码修改都重新进行了真实模型检验。

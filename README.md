# ds-web plugin for Claude Code

把本机 ds-web（DeepSeek）模型接进 Claude Code。

## 两层

1. **修复代理**（`~/.claude/ds-web-proxy.py`，端口 15722）—— Claude Code 的 `ANTHROPIC_BASE_URL` 指向它。上游 15721 会丢弃客户端的 `tools`、只注入自己的 memory 工具，并让模型把工具调用吐成 DSML 文本。代理做两件事：
   - 把客户端的工具 schema 写进 system prompt（上游不转发 `tools`）
   - 把模型输出的 DSML 文本转回原生 `tool_use` block，流式响应也合成好再发

   没有它，主模型（ds-web）无法调用 Bash/Read/Edit 等任何工具，只能吐裸 DSML 文本。
2. **插件**（本目录）—— `/ds-web` slash command + `ds_web` MCP 工具，把 prompt 直接转给 ds-web 模型做一次性问答。

## 结构

```
.claude-plugin/plugin.json       插件清单
.claude-plugin/marketplace.json  本地 marketplace（ds-web-local）
.mcp.json                        MCP server 声明
commands/ds-web.md               /ds-web slash command
server/dsweb-ask.js              CLI：一次 prompt → 文本（command 用）
server/dsweb-mcp.js              stdio MCP server（MCP 工具用）
proxy/ds-web-proxy.py            修复代理（install.ps1 装到 ~/.claude/）
install.ps1                      本机安装器（代理 + settings + 自启 + 插件）
bootstrap.ps1                    远端一键安装（下载本仓库 zip 后跑 install.ps1）
```

代理与启动器在 `~/.claude/`：

```
ds-web-proxy.py                  修复代理
start-ds-web-proxy.cmd           手动启动器（保留窗口）
%APPDATA%\...\Startup\ds-web-proxy.cmd   登录自启（pythonw，无窗口）
```

## 安装（新电脑一条命令）

仓库：https://github.com/wangliang01/ds-web-claude

前提：Windows + **Python 3.11+** + **Claude Code CLI**，且 15721 的 cc-switch 网关在本机跑着。

```powershell
irm https://raw.githubusercontent.com/wangliang01/ds-web-claude/main/bootstrap.ps1 | iex
```

脚本会下载仓库 zip、跑 `install.ps1`（装代理、改 `settings.json`、写登录自启、注册插件），然后删临时目录。幂等，重复跑安全。

完事后**重启 Claude Code**。

### 手动 / 开发方式

```powershell
git clone https://github.com/wangliang01/ds-web-claude
powershell -ExecutionPolicy Bypass -File .\ds-web-claude\install.ps1
```

或者只装插件（不含代理）：

```bash
claude plugin marketplace add wangliang01/ds-web-claude
claude plugin install ds-web@ds-web-local
```

`~/.claude/settings.json` 必须指向代理：

```json
"ANTHROPIC_BASE_URL": "http://127.0.0.1:15722"
```

## 用法

```
/ds-web 把这段日志归类成 JSON：...
```

MCP 工具：`ds_web(prompt, system?, model?, max_tokens?)`。

普通对话（Bash/Read/Edit 等工具）走代理，模型能正常调用 —— 已验证 `claude -p "用 Bash 工具跑 echo ..."` 端到端返回命令输出。

## 环境变量

代理：`DSWEB_UPSTREAM`（默认 `http://127.0.0.1:15721`）、`DSWEB_PORT`（默认 15722）、`DSWEB_KEY`（默认 `PROXY_MANAGED`）。

插件：`DSWEB_BASE_URL`、`DSWEB_KEY`、`DSWEB_MODEL`、`DSWEB_MAX_TOKENS`。

## 已知限制

1. 上游只支持 `/v1/messages`；`/v1/chat/completions` 当前 502（9Router 转发失败）。代理和插件都不走 chat 端点，不受影响。
2. 代理是 stdlib 单文件，流式响应靠缓冲上游后合成 —— 首字节延迟等于上游完整响应时间，不是逐 token 流式。
3. 登录自启依赖 Startup 目录，未装成 Windows 服务。

## 换电脑

见上面「安装」—— `bootstrap.ps1` 就是为换机器准备的，一条命令拉取并安装，无需 git。

`install.ps1` 幂等，做五件事：

1. 定位 Python（`C:\Program Files\Python311\python.exe`，否则 PATH 上的 `python`）
2. 把 `proxy/ds-web-proxy.py` 复制到 `~\.claude\ds-web-proxy.py`
3. 改 `~\.claude\settings.json`：`ANTHROPIC_BASE_URL=http://127.0.0.1:15722`、`ANTHROPIC_AUTH_TOKEN=PROXY_MANAGED`（其它键原样保留）
4. 写登录自启 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ds-web-proxy.cmd`
5. 若 15722 未监听则启动代理，并注册插件 `ds-web@ds-web-local`

完事后**重启 Claude Code**。验证：

```bash
claude -p "用 Bash 工具跑 echo OK 并原样报告"
```

返回值含 `OK` 即通。

模型名相关 env（`ANTHROPIC_DEFAULT_*_MODEL`）是每台机器自己的，脚本不动；新机器按自己的网关配置填。
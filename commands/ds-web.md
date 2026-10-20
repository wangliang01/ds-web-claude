---
description: 把问题委派给本机 ds-web (DeepSeek) 模型，返回它的原话
argument-hint: <问题或任务>
allowed-tools: Bash
---

下面是本机 ds-web 模型的回答（由 bash 预先取回，无需调用任何工具）：

!`node "${CLAUDE_PLUGIN_ROOT}/server/dsweb-ask.js" "$ARGUMENTS"`

请原样转述上面的回答，不要改写、不要补充。
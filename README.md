# lightpanda-cdp-noop-guard

**Playwright 脚本在 Lightpanda 上"跑通了"，但有些动作根本没发生。** 这个工具读一份 CDP 会话轨迹，把"上游接受、返回成功、其实什么都没做"的方法逐条揪出来 —— 在 CI 里，而不是在线上截图里。

Upstream: https://github.com/lightpanda-io/browser

为什么现在需要它：Lightpanda 以"Playwright/Puppeteer 直接换引擎"为卖点（38k stars，今天仍在日榜），换引擎的成本被描述成改一个 `ws://` 地址。但换引擎之后，脚本不会报错 —— 它会**静默降级**。深色模式截图变成浅色、触摸模拟没生效、窗口尺寸没改，全都没有异常，只有结果不对。

## 上游是什么，它缺什么

Lightpanda 是从零写的无头浏览器（Zig），对外提供 Chrome DevTools Protocol。它的 CDP 层由 `src/server/cdp/domains/*.zig` 逐个域实现。

问题不在"没实现的方法会报错"——那些反而好办。问题在**实现了入口、吞掉了参数、返回成功**的方法。上游源码里就写着：

- `src/server/cdp/domains/emulation.zig#L62` — `Emulation.setEmulatedMedia` 上方是 `// TODO: noop method`，整个函数体被注释掉，直接返回成功
  <https://github.com/lightpanda-io/browser/blob/315df53123a3bf02d5f17b24386bbb73b59945c4/src/server/cdp/domains/emulation.zig#L62>
- `emulation.zig#L75` — `Emulation.setFocusEmulationEnabled`，同样 `// TODO: noop method`
- `emulation.zig#L136` — `Emulation.setTouchEmulationEnabled`，同样 `// TODO: noop method`
- `browser.zig#L190` — `Browser.setWindowBounds`，同样 `// TODO: noop method`
- `emulation.zig#L57` — `Emulation.setDefaultBackgroundColorOverride`，注释 `// Nothing is painted with a background.`，直接 `sendResult(null)`
- `browser.zig#L120` — `Browser.setDownloadBehavior` 在没有 browser context 时"treat it as a success no-op rather than erroring"
- `storage.zig#L118` — cookie 的 `priority` / `sourceScheme` / `sourcePort` / `partitionKey` "Accepted and ignored"

这七条不是猜的，是 `gh api` 取源码逐行读出来的，行号对得上。缺口是：**没有任何工具能在运行前告诉你，你的 CDP 轨迹里有多少调用会落进这些静默分支。** 上游 issue 里关于 Playwright 兼容性的抱怨（如 #3076、#4186）讨论的是"报错/挂起"，静默成功这一类别没有对应的检测手段。

## 这个工具做什么，不做什么

做：

- 读一份 CDP 轨迹（JSONL 或 JSON 数组，支持裸 `{"method":...}` 和 `{"message":{"method":...}}` 两种封装）
- 按内置清单（pin 在上游 commit `315df53`）把调用分成 `noop` / `conditional_noop` / `partial` 三档
- 输出人类可读报告或 `--json`，每条命中都带**上游源码永久链接 + 行号 + 原文证据**
- 退出码可用于 CI 卡口

不做：

- 不连网、不启动浏览器、不驱动 CDP —— 纯离线静态判定
- 不判断"这个方法在 Lightpanda 里实现得好不好"，只判断清单里记录的"接受但忽略"
- 不覆盖清单外的语义差异（渲染、布局、JS 引擎差异），那些需要真实运行

## 安装 / 用法

零依赖，只要 Python 3.8+：

```bash
git clone git@github-linmoxi33:linmoxi33/lightpanda-cdp-noop-guard.git
cd lightpanda-cdp-noop-guard
./bin/lightpanda-cdp-noop-guard examples/in/playwright-darkmode.jsonl
```

输出（退出码 1）：

```text
lightpanda-cdp-noop-guard v1.0.0
trace: examples/in/playwright-darkmode.jsonl
upstream: lightpanda-io/browser @ 315df53123a3
calls: 6 (6 distinct)

HITS: 2 ignored method(s)
  ERROR Emulation.setEmulatedMedia                    x1   line 3    noop
        media/features are never parsed; prefers-color-scheme and print emulation do nothing.
        evidence: // TODO: noop method
        source:   https://github.com/lightpanda-io/browser/blob/315df53.../emulation.zig#L62
```

`--json`（可被 `python3 -c "import json,sys;json.load(sys.stdin)"` 解析）：

```json
{
  "tool": "lightpanda-cdp-noop-guard",
  "verdict": "fail",
  "total_calls": 6,
  "error_hits": 2,
  "warning_hits": 0,
  "hits": [
    {"method": "Emulation.setEmulatedMedia", "status": "noop", "count": 1,
     "first_line": 3, "evidence": "// TODO: noop method",
     "source_url": "https://github.com/lightpanda-io/browser/blob/315df53.../emulation.zig#L62"}
  ],
  "unclassified_methods": ["Browser.getVersion", "Page.navigate"]
}
```

选项：`--json`、`--strict`（把 `partial` / `conditional_noop` 也判为失败）、`--manifest PATH`、`--quiet`。

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 通过：没有 `noop` 命中（`--strict` 下也没有警告级命中） |
| 1 | 检出问题：轨迹里存在被静默忽略的调用 |
| 2 | 用法或输入错误：缺参数、文件读不到、JSON 解析失败、记录没有 `method` |

## 局限

- 清单是**快照**，pin 在 commit `315df53`（2026-10-31）。上游改掉某个 `TODO: noop` 之后，清单会过时；`--manifest` 允许你换成自己维护的版本。
- 只覆盖 `src/server/cdp/domains/` 里能直接读出来的静默分支。参数级的部分忽略（例如 `Input.dispatchKeyEvent` 注释里的 "Many optional parameters are not implemented yet"）没有逐参数建模。
- 清单外的 `unclassified_methods` 只列出、不判定 —— 未知不等于安全。
- 没有对真实 Lightpanda 二进制做端到端验证（本环境无法构建 Zig）；证据全部来自上游源码文本。

## 本轮创新

**第一次把"CDP 静默成功"当成一类独立缺陷来检测。** 现有的 Lightpanda/Playwright 兼容性讨论（issue #3076、#4186 以及同类项目）都在处理"调用报错/挂起"，而本工具针对的是相反的方向：调用返回 200、参数被丢弃、结果错但无异常。判定依据不是跑一遍浏览器，而是把上游源码里的 `// TODO: noop method` 变成可执行的清单，并 pin 到 commit + 行号，所以每一条命中都能点开原文核对。这个视角换到别的项目不成立 —— 清单是逐行读 Lightpanda 的 CDP 域实现得来的。

## 与同类项目的差异

`gh search repos "lightpanda cdp"` / `"playwright lightpanda"` 命中最高 5 stars（`irookanji/playwright-lightpanda-tests`），都是"怎么跑起来"的示例或 MCP 桥；`gh search code "setEmulatedMedia lightpanda"` 无命中。没有同类做静默忽略检测，也没有同类把上游源码行号作为证据链输出。

## 许可

MIT，见 `LICENSE`。

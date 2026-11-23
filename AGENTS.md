# AGENTS — AI 代理入口（自动加载）

> 本文件遵循 AGENTS.md 约定，可被支持该标准的 AI 编码工具自动注入上下文。
> 适配器：Claude Code 用 `ln -s AGENTS.md CLAUDE.md`；Cursor 旧版复制到 `.cursor/rules/project.mdc`；TRAE 复制到 `.trae/rules/project.md`。

## 会话第一件事：读状态，别读全部

```bash
bash tools/ai.sh brief      # → doc/brief.md（≤4KB：现在 / 必须知道 / 约束速查 / 验证命令）
```

它由 `STATE.md + 闸门结果 + git + CONSTRAINTS` 现算，**替代「通读全部入口文件」**。
下面清单改为**按需回查**（brief 里指到哪条就看哪条），不再要求每会话整篇读：

1. `AI_INSTRUCTIONS.md` — 协作协议 + 完成定义（DOD）
2. `CONSTRAINTS.md` — 硬约束注册表（违反 = 返工）
3. `BLOCKS.md` — 积木注册表（改动先报积木编号）
4. `STATE.md` — 当前状态与已知问题（brief 已摘要）
5. `GLOSSARY.md` — 术语表（名词有歧义先查这里）

> `doc/000-…手册.md` 是方法论参考，卡顿时直接看第 6 章失效信号诊断表；`doc/003` 是 v3 闭环的设计依据。

## 改动完成后，一条命令全绿才提交

```bash
bash tools/run.sh --out out/ --json
```

它依次跑：输入校验 → 业务勾稽 → 双跑对比 → 索引一致性 → 占位符残留 → 密钥扫描 → 上下文预算，
并把结果写成机器可读的 `doc/health/last_gates.json`。缺前置条件的门会 SKIP，不假装通过；
同一门连续 3 次 SKIP 会提示启用。

## 交付前 / 排障时

- `bash tools/ai.sh explain` — 改动评审单 `doc/review.md`：风险等级、命中约束、必跑验证、待拍板问题
- `bash tools/ai.sh triage` — 把最近一次 FAIL 变成 `doc/health/TRIAGE.md`（事实 + 候选原因，不含结论）
- `bash tools/ai.sh watch` — 无人值守巡检（`--once` 可进 cron/CI）；失败自动分诊
- `bash tools/align.sh --open` — 人机对齐看板 `doc/align.html`
- `bash tools/doctor.sh` — 环境自检（新项目第一天 / 换机器先跑）
- `bash tools/selftest.sh` — 改了 `tools/` 必跑（模板本体）

单独跑某一门：`python tools/checks/<门>.py …`，用法见各文件头。

写 `doc/NNN-版本_主题.md`（模板见 doc/001），同步更新 `STATE.md` 与 `CONSTRAINTS.md`，
提交信息带 `Refs: doc/NNN`（commit-msg 钩子会检查）。

# 提交规范（中文范围式）

## 格式

```
<范围>: <摘要>

<正文，可选>
```

- **首行**：`范围: 摘要`，≤50 字，讲清"做了什么"，结尾不加句号。
- **范围词**：`地基` / `数据层` / `检测层` / `fusion` / `plan` / `风控` / `输出` / `hermes` / `测试` / `文档`（可按需新增，保持一致）。
- **正文**（可选，空一行后写）：用 `-` 列要点，重点说**为什么**，可标注关联决策 `(D3)` `(P0-2)` `(缺口9)`。

## 示例

```
fusion: 修复评分越界

- abs(net)/max_possible 双重夹取 0-100
- 加多周期封顶回归测试 (缺口9)
```

## 自动校验

- 模板：`git config commit.template .gitmessage`（`git commit` 不带 -m 时自动带出提示）。
- 钩子：`commit-msg` 校验首行结构（`core.hooksPath=.githooks`，随仓库走）。
  缺少 `范围: 摘要` 结构会被拒绝；标题过长仅提醒。
- 放行：`Merge`/`Revert` 开头的提交不校验。

## 新克隆仓库后启用

```
git config commit.template .gitmessage
git config core.hooksPath .githooks
```
（首次 `setup` 后已写入本地 `.git/config`，仅换机/重克隆需重设。）

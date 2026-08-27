---
name: git-pull-resolve
description: 安全执行 Git 拉取与分支集成，优先通过 rebase 保持线性历史，定位并解释合并或变基冲突，逐项完成语义化解决和验证，并提供 commit message 建议但不创建新提交。当用户要求 git pull、拉取代码、同步分支、rebase、线性合并、合并分支、解决 Git 冲突、指出冲突位置与解决办法，或完成“拉取—冲突处理—验证”流程时使用。
---

# Git Pull、线性集成与冲突处理

完整执行代码同步和冲突验证流程，同时保护无关改动并避免不必要的分叉。把“冲突在哪里”“为什么这样解决”和“建议使用什么 commit message”作为强制交付内容；是否创建新提交由用户决定。

## 安全规则

- 操作前读取仓库指令。仓库根目录存在 `.codegraph/` 时，理解冲突代码前先使用 CodeGraph，再考虑文本搜索或逐文件阅读。
- 绝不丢弃用户改动。禁止使用 `git reset --hard`、对全部文件执行 `checkout --ours/--theirs`，或进行破坏性清理。
- 不暂存任务开始前已有的无关改动。必要时单独保存，并在不会混入待提交结果时安全恢复。
- 不执行 `git commit`、`git commit --amend` 或创建新的 merge commit。允许使用 `git rebase --continue` 重放任务开始前已经存在的本地提交；这不代表获得创建或修改其他提交的授权。
- 未经用户明确要求，不执行 `git push`。
- 不得不加分析地选择 ours 或 theirs。先理解双方意图，再保留兼容行为。
- 仍存在未合并索引项、冲突标记、失败检查或未完成的 merge/rebase 时，不得宣称任务全部完成。
- 未经用户明确授权，不改写已经 push 或多人共享的提交。仅对尚未发布的本地提交默认采用 rebase。
- 重写本地历史前记录旧分支 tip；重写后验证代码 tree 未意外变化，并保留 reflog 恢复路径。
- 不得只因 `.git/REBASE_HEAD` 存在就判断 rebase 未完成。以 `git status` 以及 `.git/rebase-merge`、`.git/rebase-apply` 状态目录为准。

## 1. 确认拉取目标与仓库状态

1. 确认仓库、分支、上游和工作区状态：

   ```bash
   git rev-parse --show-toplevel
   git status --short --branch
   git remote -v
   git branch -vv
   git log --oneline --decorate --graph -12
   git diff --check
   ```

2. 检查是否已有 merge、rebase、cherry-pick 或 revert 正在进行。若该操作早于本次任务，仅在符合用户目标时继续；不得自动中止他人发起的操作。
3. 确定当前目标分支和待拉取来源。优先使用用户明确指定的远端与分支；否则使用当前分支配置的 upstream，并向用户说明这一假设。
4. 若处于 detached HEAD 且包含需要集成的改动，先确认这些改动的基线和目标分支。若继续操作必须先创建新提交，停止并让用户决定提交方式；不要代替用户制造提交后再清理历史。
5. 若存在无关的已跟踪或未跟踪改动，先记录并隔离。确有需要时使用名称清晰的 stash；按需包含未跟踪文件，但不得把被忽略的密钥或敏感文件加入 stash。记录 stash 引用，避免混入本次待提交结果。
6. 为便于观察和诊断，把 pull 拆成 fetch 与集成步骤：

   ```bash
   git fetch --prune <remote>
   ```

7. 按以下顺序选择集成方式：
   - 用户要求或仓库规范优先。
   - 本地提交尚未 push，且目标是保持单线历史时，默认把功能提交 rebase 到最新 upstream。
   - 已 push、多人共享或必须保留分支汇合信息时，使用 merge；除非用户明确授权历史重写。
   - 只有工作树改动、尚无提交时，先用安全的 stash 隔离，再同步当前分支并恢复；若这些改动必须先形成提交才能 rebase，停止并让用户决定如何提交。

   线性集成优先使用：

   ```bash
   git switch <feature-branch>
   git rebase <remote>/<target-branch>
   git switch <target-branch>
   git merge --ff-only <feature-branch>
   ```

   确认目标分支已经包含 rebased commit 后，按需删除临时功能分支。正常流程应提前选择 rebase，避免事后删除 merge commit。

8. 仅在应该保留分叉结构时使用 merge：

   ```bash
   git merge --no-commit <remote>/<branch>
   ```

   除非用户要求或仓库规定，否则不要通过 `--no-ff` 强制创建合并提交。若结果为 fast-forward，明确说明无需创建 merge commit；若产生待提交的 merge 结果，完成冲突处理和验证后停在 `MERGE_HEAD` 状态，由用户决定是否提交或中止。

9. 若用户明确要求把尚未 push 的现有 merge 历史改为单线：
   - 记录旧 merge tip 和 tree hash；
   - 在功能分支上 rebase 到 upstream；
   - 验证 rebased tip 与旧 merge tip 的最终 tree 一致；
   - 离开目标分支后再移动本地目标分支指针，避免使用 `git reset --hard`；
   - 切回目标分支并删除已经完全包含的临时分支；
   - 确认目标分支仅领先 upstream 预期数量，且普通 push 即可完成发布。

## 2. 列出全部冲突

在仓库根目录运行技能自带的只读报告脚本：

```bash
python3 <技能目录>/scripts/conflict_report.py
```

退出码 `0` 表示没有未解决索引项；退出码 `1` 表示发现冲突，这是报告结果而非脚本故障。

同时检查：

```bash
git status --short
git diff --name-only --diff-filter=U
git ls-files -u
git diff --cc
```

编辑前建立“冲突清单”。每个冲突文件必须说明：

- **位置：** 仓库相对路径，加冲突标记行号范围、符号/配置区段，或无冲突标记时的索引阶段说明。
- **类型：** 内容冲突、双方新增、修改/删除、重命名、文件/目录、二进制、子模块，或 Git 报告的其他类型。
- **ours：** merge 时表示当前分支；rebase 时表示新的基线/upstream。
- **theirs：** merge 时表示传入分支；rebase 时表示正在重放的本地提交。
- **解决方案：** 准备保留、删除或组合的具体行为/内容，以及采用该方案的原因。

在解决冲突之前或解决过程中，以简洁进度更新展示该清单。对于没有 `<<<<<<<` 标记的冲突，使用索引阶段和文件状态定位；不得因文件中没有标记就报告“无冲突”。

特别提醒：rebase 中 ours/theirs 的直觉与“保留我的本地修改”相反。报告和解决方案必须使用“upstream/正在重放的提交”再次说明，避免选错一侧。

## 3. 理解并解决冲突

依次处理每个冲突文件：

1. 不修改索引，读取三方版本：

   ```bash
   git show :1:path/to/file  # 共同基线 base
   git show :2:path/to/file  # ours：merge 当前分支 / rebase 目标基线
   git show :3:path/to/file  # theirs：merge 传入内容 / rebase 重放提交
   git diff --ours -- path/to/file
   git diff --theirs -- path/to/file
   ```

2. 追踪受影响的符号、调用方、测试、数据结构、配置和外部行为。仓库已建立 CodeGraph 索引时，先查询冲突文件或符号，再使用 `rg`。
3. 优先解决真实来源文件：
   - 先合并依赖清单，再使用仓库工具重新生成 lockfile 或生成文件。
   - 对可重新生成的派生文件，优先通过项目工具链生成。
   - 双方独立新增且仍有效的声明、注册、路由或工程引用，应同时保留。
   - 遇到修改/删除冲突，先确认删除是否为有意行为，再决定恢复还是删除。
   - 遇到二进制或子模块冲突，比较元数据和历史，明确选择或重新生成目标，并记录选中的对象或子模块提交。
   - 遇到 `.pbxproj` 冲突，不要只清除冲突标记。Git 可能自动合并出重复的 24 位对象 ID；扫描整个文件的定义，并确保 `PBXBuildFile`、Build Phase、Package Reference 和 Product Dependency 形成一致引用链。
   - 两个 Xcode 依赖复用同一对象 ID 时，保留目标分支已有 ID，将传入依赖整体重映射到未占用 ID；不得只修改定义而遗漏所有引用。
4. 进行最小范围编辑，移除全部冲突标记，只暂存已经解决的路径：

   ```bash
   git add -- path/to/file
   # 若确认删除：
   git rm -- path/to/file
   ```

   在 merge/rebase 冲突中暂存路径只表示“该冲突已解决”，不是替用户决定最终提交。rebase 可通过 `git rebase --continue` 完成既有提交的重放；普通 merge 不执行 `git commit`。

5. 每解决一组文件后重新运行冲突报告。若调查结果改变了解决方案，同步更新冲突清单。

## 4. 验证合并结果

确保以下结构性检查全部通过：

```bash
test -z "$(git diff --name-only --diff-filter=U)"
git ls-files -u
git diff --check
git diff --cached --check
git status --short
git diff --cached --stat
git diff --cached
```

搜索已跟踪文件中残留的冲突标记；若测试夹具或文档示例故意包含标记，需要单独说明：

```bash
git grep -n -E '^(<<<<<<<|=======|>>>>>>>)( |$)'
```

对于 Xcode 工程，额外验证 plist 语法和对象定义唯一性：

```bash
plutil -lint path/to/project.pbxproj
rg -o --pcre2 '^\s*\K[A-Z0-9]{24}(?= /\*.*\*/ =)' path/to/project.pbxproj | sort | uniq -d
```

第二条命令必须无输出。若有重复 ID，继续修复，不能暂存或提交。

运行仓库相关的格式化、构建、静态检查、单元测试和冲突行为专项测试。对于 iOS 工程：

- 存在 CocoaPods `.xcworkspace` 时，构建 workspace，不要直接构建 `.xcodeproj`；后者不会构建 Pods targets，容易误报模块缺失。
- 首次解析或 workspace 没有自己的 `Package.resolved` 时，不要使用 `-disableAutomaticPackageResolution`。先运行 `xcodebuild -resolvePackageDependencies -workspace ... -scheme ...`。
- SwiftPM 解析失败后出现大量 `Missing package product` 时，先找到最早的远端访问、认证或版本解析错误；后续产品缺失通常是级联结果。
- 区分 warning 与 error。第三方 SDK 的弃用警告不能冒充构建失败；以 `xcodebuild` 退出码和 `BUILD FAILED/SUCCEEDED` 为准。
- 环境允许时执行 workspace 的 `xcodebuild build` 或 `xcodebuild test`。不得隐瞒失败；使用证据区分本次集成导致的失败与原有失败。

## 5. 整理待提交结果并恢复原有改动

1. 审查暂存和未暂存差异，确认只包含本次集成内容及其冲突解决；不得把任务开始前的无关改动混入待提交结果。
2. 不执行 `git commit`。根据仓库近期提交风格和实际差异提供一段可复制的 commit message 建议：

   ```text
   <type>(<scope>): <简洁主题>

   - <主要变更或冲突解决点>
   - <验证或兼容性说明，可选>
   ```

   无明确 scope 时省略括号；仓库不使用 Conventional Commits 时遵循现有格式。不要编造未发生的修改。若 rebase 仅重放已有提交且没有新的待提交差异，明确说明无需新 commit message，沿用已有提交信息。
3. rebase 或其他历史整理完成后，对比旧 tip 与新 tip：

   ```bash
   git diff --exit-code <old-tip> <new-tip>
   git show -s --format='%H %T %P %s' <old-tip> <new-tip>
   ```

   当任务只改变历史形状时，最终 tree 应一致。若不一致，先解释差异，不得继续移动目标分支。
4. 记录当前索引、工作树和历史证据：

   ```bash
   git status --short --branch
   git diff --cached --stat
   git diff --cached
   git rev-parse HEAD
   git rev-list --left-right --count HEAD...@{upstream}
   git log --oneline --decorate --graph -8
   ```

5. 若此前保存了无关改动，仅在 rebase/fast-forward 已完成且工作树允许隔离恢复时恢复。若 merge 仍等待用户提交，保留 stash，不要把原有改动恢复到待提交索引中。恢复 stash 时若再次发生冲突，单独报告“恢复原有改动时的冲突”，并保留 stash，直到确认可以安全清理。
6. 删除临时分支前确认目标分支包含 rebased commit，且分支没有独有工作。不要为了视觉整洁删除尚未集成的提交。

## 最终报告要求

最终必须说明：

- 拉取来源、目标分支/提交，以及结果属于 merge、rebase 还是 fast-forward；
- 当前是否存在待提交差异或待完成 merge；默认明确写“未执行 git commit，由用户决定如何提交”；
- 每个冲突的位置、类型和实际采用的解决方案；没有冲突时明确写“无冲突”；
- 执行过的验证命令及结果；
- 一段基于实际差异、符合仓库风格的 commit message 建议；仅重放已有提交且无新差异时说明无需新提交信息；
- 任务开始前已有改动或 stash 的最终状态；
- 最终历史是否线性、目标分支相对 upstream 的领先/落后数量，以及临时分支是否已删除；
- 是否仍有未解决事项；除非用户明确要求，否则说明未执行 push。

若 rebase 后提交直接位于最新 upstream 之上且从未 push，说明后续使用普通 push，不要误导用户使用 force push。只有确实改写了已发布远端历史并获得授权时才考虑 `--force-with-lease`，禁止使用裸 `--force`。

若无法完成，保持仓库处于最安全、可恢复的状态，指出准确阻塞原因，并给出下一条非破坏性命令或需要用户决定的事项。

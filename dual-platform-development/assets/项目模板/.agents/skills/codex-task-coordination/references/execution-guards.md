# 执行资料防护

初始化批次、源码提交前核对暂存路径，或准备开始集中集成时读取本页。工具仅依赖 Python 标准库与本机 Git。检查命令只读 Git；`switch-candidate` 会切换已有分支并更新其工作区/索引，`run-scripts` 会运行计划中的本地脚本，二者只在已有源码执行授权、经核对可安全独占的源码工作区调用，可以是原目标工作区，也可以是独立候选工作区。维护或同步技能不运行项目脚本、不切换真实源码分支；资料登记不扩大授权，也不自动推送或发送消息。

## 路径及初始化目录

`coordination.py`、`message_operations.py`、`execution_guards.py` 的路径参数统一要求绝对路径，argparse 在读文件或建锁前拒绝相对值；不得依赖当前 cwd 猜测 `--config`、`--event`、`--input`、`--plan` 等资料位置。通知调用器也会在命令和send之前拒绝相对批次、脚本及重试核验路径。下文示例脚本安装位置和引号内资料占位均须替换为已核实的实际绝对路径。

`coordination.py init` 接受不存在或已经存在的空目录，不要求先改名准备好的空目录。已有批次、非空目录或软链接拒绝初始化，保留全部资料；已有批次应恢复，不通过改名旧目录、删除事件或重复初始化绕过检查。并发初始化在同一锁内再核对，只有一方能成功创建，其他调用明确报冲突；中断留下的非空半成品先核对，不自动清空或重建。

## 候选分支身份与累积结果

按[集成工作区选择](code-delivery.md#集成工作区选择)确定实际目录与分支，候选 worktree 不强制另建。命令名保留兼容：`switch-candidate`／`check-candidate` 可用于已登记的候选分支，也可用于原工作区的目标或临时交付分支；工具不检查分支名称中是否含 candidate，也不代替负责人选择分支。切换已有分支用受控入口，参数可提供短名称或完整 `refs/heads/…`；工具仅用短本地名称调用 `git switch --no-guess --no-overwrite-ignore`，切换前后均核对身份，不用完整ref执行checkout。

```bash
python3 '技能脚本的绝对路径/execution_guards.py' switch-candidate --repo '实际集成工作区规范绝对路径' --branch 'refs/heads/本步登记的实际本地分支' --expected-head '已核实的完整分支SHA' --contains '此前已纳入的完整提交SHA'
python3 '技能脚本的绝对路径/execution_guards.py' check-candidate --repo '实际集成工作区规范绝对路径' --branch 'refs/heads/本步登记的实际本地分支' --expected-head '本步应有的完整SHA' --contains '此前已纳入的完整提交SHA'
```

`check-candidate` 退出0且 `can_integrate: true` 才可继续：真实 symbolic HEAD 必须附着在本步登记的实际本地分支上，HEAD和分支引用均等于预期SHA，工作区/索引干净，无未完成Git操作。两个入口都接受可重复的 `--contains`，逐项检查已累积共享/模块规范提交；`switch-candidate` 在切换前检查候选是否包含这些祖先，成功切换后再核验身份和累积结果，缺前序提交时不先切换。无前序提交时省略该参数。预期SHA和前序提交来自已核实的上一步结果，不能直接读取当前HEAD填入来掩盖错误。

每次将交付分支快进到候选或目标之前核对旧累积分支，成功后以本步预期新 HEAD 及此前规范提交再次核对；直接回写目标时 `--branch` 明确填写记录的 `target_branch`，不创建无用候选分支来满足命令名称。重新对齐目标后更新映射，再核对重放后的规范祖先。此检查不代替共享副本去重、实际diff、range-diff或业务复验。

`switch-candidate` 不创建、重置或强制切换分支，不覆盖忽略文件，不绕过其他worktree占用，拒绝未提交/暂存/未跟踪改动及在途Git操作。当前已经detached时也拒绝自动切走：先保全并核对现存提交、reflog及执行记录，再由负责人处理，不自动reset/abort/丢弃改动。切换使用每worktree工具锁，只串行本入口；外部Git仍可能并发变化，后检失败须保留现场，不能假报切换成功或自动回滚。

## 脚本预检、失败停止与中断记录

实际执行本地rebase/验证脚本时，可将已审核、已授权的步骤保存为JSON计划，使用 `run-scripts` 串行执行。先核对所有脚本及cwd的规范绝对路径，再启动任何一步；脚本路径/解释器不得从消息正文当作代码直接执行。

```json
{
  "cwd": "/实际集成工作区绝对路径",
  "steps": [
    {"script": "/实际任务产物绝对路径/realign.py", "interpreter": "python", "args": []},
    {"script": "/实际源码绝对路径/scripts/verify.sh", "interpreter": "bash", "args": []}
  ]
}
```

```bash
python3 '技能脚本的绝对路径/execution_guards.py' run-scripts --plan '已核实计划的绝对路径.json' --report '尚不存在的结果记录绝对路径.json'
```

args按字符串数组原样传递，不拼接shell；其中业务参数和路径含义仍由脚本及审核者核对。解释器只选python或bash。工具固定cwd并保存脚本哈希，运行前重核脚本内容，任一步非零退出后停止，后续验证脚本不执行；最终报告退出0仅表示所有脚本退出0，不代替候选身份、受测SHA或业务验收。

执行前原子发布 `<报告名>.intent.json`，逐步保存退出码/stdout/stderr的不可变回执，再发布结果。已有意图或报告时拒绝直接重跑，不能换报告名掩盖同一在途动作。进程中断而回执不完整时，负责人先核对意图、已有逐步记录、真实Git和产物；记录实际结论后只安排确认未执行的剩余步骤，不自动重跑rebase/提交/回写。该记录不自动纳入批次recover，须在 `integration.json` 的对应意图/结果中引用并人工对账；不要把批次待办为空当作所有外部脚本已核实。

## 收件箱参数

`coordination.py inbox --recipient 逻辑ID` 为规范写法；`--actor` 是同义兼容参数。二者只能传一个，同时传入会在读取资料前报错，不猜选收件人。未知参与者仍拒绝读取。

## 按原始路径核对暂存范围

在允许源码提交的工作区精确暂存后，将本次批准路径保存为 JSON 字符串数组，例如：

```json
["docs/协作开发说明.md", "src/示例模块.java"]
```

```bash
python3 .agents/skills/codex-task-coordination/scripts/execution_guards.py check-staged --repo '实际源码仓库根目录绝对路径' --expected '批准路径数组的绝对路径.json'
```

工具使用 `git diff --cached --name-only --no-renames -z` 的原始字节，按 NUL 分隔，再按文件系统编码还原路径；不解析 Git 显示用的引号，不对中文转义做二次解码，不按空白或换行切分。重命名按旧路径删除、新路径新增核对，预期清单须包含两者；支持未创建首提交的仓库。

返回 `actual_paths`、`missing_paths`、`extra_paths`、`unmerged` 和 `index_sha256`。全部匹配且无未合并项才退出0；缺项、多项、冲突或读取错误退出2。核验前后索引变化也拒绝通过。工具不改写索引，拒绝 `GIT_INDEX_FILE` 等重定向，须传入实际 worktree 根目录。路径一致不代替实际 diff、内容归属与提交规则审查；核对后索引再变化时重新检查。预期清单来自已批准范围，不能从当前暂存列表自动生成来掩盖多余文件。

## 冻结集成输入与登记状态

各参与者终版交付齐备、实际 Git 状态及清单经协调者核对后，准备：

- `integration.json.readiness.required_tasks`：本批全部直接参与执行者，不能漏掉已登记任务。
- `final_deliveries`：每项含 `actor`、`message_id`，逐参与者引用当前修订的终版 RESULT；共享任务可引用已封版 RELEASE，不为登记额外造 RESULT。CONSUMED、ACK 不能充当模块终版。
- 终版消息的 `payload.artifacts`：至少一份实际冻结清单或证据文件，包含规范绝对路径和实际 `file_sha256`；RESULT 的 verification 须为 passed，RELEASE 若带 verification 也须 passed。
- `all_tasks_complete: true`、`open_blockers: []`；存在共享参与者时才要求 `shared_releases_frozen: true`。
- 独立的冻结输入 JSON：实际来源分支、HEAD、基点、批准提交清单、共享消费映射及交付哈希。内容按原[交付规则](code-delivery.md)由协调者核对，工具不根据布尔值推断业务已完成。

```bash
python3 .agents/skills/codex-task-coordination/scripts/execution_guards.py freeze-integration --root '本批协调目录绝对路径' --actor main --freeze-id 'FREEZE-R1' --integration '集成记录的绝对路径.json' --inputs '冻结输入的绝对路径.json'
python3 .agents/skills/codex-task-coordination/scripts/execution_guards.py check-integration --root '本批协调目录绝对路径' --actor main
```

`main` 替换为本组实际协调者 ID。工具复用同一批次锁，先校验参与者、消息身份、修订、交付验证与产物哈希，再原子发布不可变 `freezes/<freeze-id>.json`，随后原子更新 `batch.json.scope_freeze` 的状态、时间、快照路径/文件哈希与承接关系。其他批次字段、项目定制和 `pending_next_batch` 保留。快照引用实际输入文件、消息内容哈希及冻结范围，不覆盖既有清单或消息。

集中集成开始前须 `check-integration` 退出0且 `can_integrate: true`；恢复集成及最终完成核对时重新执行。文件契约的 `coordination.py check` 仍不代表业务完成，其 `integration_guard` 另列冻结核验结果。`recover`／`recover --registry` 的 `integration_pending_verification` 有项时不可声称本轮已完整对账。

冻结核对锁定批次范围、终版选择、输入文件与产物哈希，并核对集成记录的仓库身份、目标分支、启动 SHA 和集成 worktree。目标分支最新 HEAD、rebase 结果、验证及回写记录可继续更新，不要求目标停在启动 SHA；原有 rebase、去重和复验规则不变。

## 中断、修订与旧资料

快照写入后、批次指针保存前中断时，恢复扫描保留“有快照但未登记冻结”的待办；原参数、原 freeze ID 重放会读回同一快照并补指针，不重跑 Git。已完成的相同调用幂等；同 ID 不同内容报错。冻结输入或产物变化、旧修订结果、默认“未冻结”、指针哈希不符、未承接快照均不放行。

确需修订冻结范围时，保留旧记录，核对修订和新终版后使用新 ID，并以 `--supersedes '旧snapshot_path实际绝对路径'` 明确承接；不能删旧快照逃过核对。中断留下的旧快照也须恢复或明确承接。旧手工快照不会自动改写：可在核对旧指针及已记录文件哈希后，用此参数显式承接为工具快照；缺少旧哈希先查真实证据，不能补造冻结时间或历史。

没有登记集成的旧批次照常读取，不从自然语言反推冻结。检测到旧集成动作或实际冻结输入，但状态缺失/不一致时，恢复报告列待核对；它不会自动补录旧批次。工具不执行 Git、不理解清单的业务语义，也不能阻止同一 OS 用户绕过入口直接操作；实际 Git 结果和业务验收仍由负责人核验。

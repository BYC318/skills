#!/usr/bin/env python3
"""管理逐状态截图证据并生成离线验收册；只校验记录，不替代实际 UI 审查。"""

import argparse
import copy
import hashlib
import json
import re
import struct
import sys
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

# 按脚本实际位置定位本项目的 resources 目录，避免执行目录不同导致记录写入其他项目。
RESOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT = RESOURCE_ROOT.parent
CHECKS = ("layout", "images", "fonts", "interaction", "toast", "resource_cleanup", "identity")
LABELS = dict(zip(CHECKS, ("布局", "图片", "字体", "交互", "缺失功能 Toast", "旧资源清理", "证据身份")))
IDENTITY_KEYS = ("id", "state_id", "variants")
VARIANTS = ("light-ltr", "light-rtl", "dark-ltr", "dark-rtl")


def now():
    """使用带时区的时间保留跨机器可解释的记录。"""
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    """主 Agent 单写台账，原子替换避免中断留下半份 JSON。"""
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value), "证据 ID 仅可使用字母、数字、下划线和连字符，最长 80 字符")
    return value


def timestamp(value):
    require(text(value), "采集或审查时间缺失")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "时间必须包含时区")


def png_info(data):
    """检查实际 PNG 字节，避免把空文件或接口错误页当成截图。"""
    require(data[:8] == b"\x89PNG\r\n\x1a\n", "截图必须是 PNG 原图")
    offset, width, height, pixels, ended = 8, 0, 0, [], False
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        require(offset + size + 12 <= len(data), "PNG 数据不完整")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        checksum = struct.unpack(">I", data[offset + 8 + size:offset + 12 + size])[0]
        require(zlib.crc32(kind + payload) & 0xFFFFFFFF == checksum, "PNG 块校验失败")
        if kind == b"IHDR":
            require(size == 13, "PNG 图像头无效")
            width, height = struct.unpack(">II", payload[:8])
        if kind == b"IDAT":
            pixels.append(payload)
        if kind == b"IEND":
            ended = True
            break
        offset += size + 12
    require(width > 0 and height > 0 and ended and pixels, "PNG 缺少必要图像数据")
    require(bool(zlib.decompress(b"".join(pixels))), "PNG 像素数据为空")
    return width, height


def inside(root, relative):
    require(text(relative) and not Path(relative).is_absolute(), "证据文件必须使用相对证据根目录的路径")
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path != root, "证据路径越出任务目录")
    return path


def load(path):
    ledger = read_json(path)
    require(isinstance(ledger, dict) and ledger.get("schema_version") == 1, "不支持的页面台账格式")
    require(isinstance(ledger.get("task"), dict) and isinstance(ledger.get("pages"), list), "台账缺少 task/pages")
    task = ledger["task"]
    require(task.get("platforms") and set(task["platforms"]).issubset({"ios", "android"}), "参与平台无效")
    require(len(task["platforms"]) == len(set(task["platforms"])), "参与平台不可重复")
    require(task.get("variants") == list(VARIANTS), "任务取证矩阵必须包含日夜间与 LTR/RTL 四种组合")
    root = Path(task["evidence_root"])
    require(root.is_absolute() and root.is_dir(), "外部证据目录不存在；请先核对磁盘挂载，不得回退目录")
    root = root.resolve()
    require(not root.is_relative_to(PROJECT), "截图与报告目录不能位于协作或源码仓库中")
    ids = [p["id"] for p in ledger["pages"]]
    require(len(ids) == len(set(ids)), "页面证据 ID 重复")
    for page in ledger["pages"]:
        safe_id(page["id"])
        require(set(page["variants"]) == set(VARIANTS), "页面须覆盖日夜间和 LTR/RTL 四种组合")
        for key, variant in page["variants"].items():
            theme, direction = key.split("-")
            require(variant.get("theme") == theme and variant.get("direction") == direction and text(variant.get("locale")), "组合标签、主题、方向或语言不一致")
            safe_id(variant["baseline_id"])
        require(isinstance(page.get("rounds"), list), "页面缺少轮次列表")
        rounds = [r["id"] for r in page["rounds"]]
        require(len(rounds) == len(set(rounds)), "同页轮次 ID 重复")
        for run in page["rounds"]:
            safe_id(run["id"])
    return ledger, root


def find_page(ledger, page_id):
    result = next((p for p in ledger["pages"] if p["id"] == page_id), None)
    require(result is not None, "没有找到页面证据 ID")
    return result


def find_round(page, round_id=None):
    round_id = round_id or page.get("current_round")
    result = next((r for r in page["rounds"] if r["id"] == round_id), None)
    require(result is not None, "没有找到取证轮次；请先创建轮次")
    return result


def identity(page):
    return {k: copy.deepcopy(page[k]) for k in IDENTITY_KEYS}


def build_valid(build):
    require(isinstance(build, dict), "缺少构建记录")
    for key in ("commit", "worktree_digest", "artifact_sha256"):
        require(text(build.get(key)), "构建记录缺少 " + key)
    require(re.fullmatch(r"[0-9a-fA-F]{40,64}", build["commit"]), "commit 必须是完整 Git 提交 ID")
    for key in ("worktree_digest", "artifact_sha256"):
        require(re.fullmatch(r"[0-9a-fA-F]{64}", build[key]), key + " 必须是 SHA256")


def metadata_errors(meta, platform, snapshot, builds, variant):
    """校验明确身份绑定；锚点和稳定性仍须采集者从实际运行中核实。"""
    errors = []
    try:
        require(isinstance(meta, dict), "采集信息必须是 JSON 对象")
        case = snapshot["variants"][variant]
        for key, expected in (("page_id", snapshot["id"]), ("state_id", snapshot["state_id"]), ("baseline_id", case["baseline_id"]), ("locale", case["locale"]), ("theme", case["theme"]), ("direction", case["direction"])):
            require(meta.get(key) == expected, "采集身份不匹配：" + key)
        timestamp(meta.get("captured_at"))
        if platform == "figma":
            require(case.get("figma"), "该主题与方向尚未绑定设计依据")
            for key in ("file_key", "node_id"):
                require(meta.get(key) == case["figma"][key], "原稿节点不匹配：" + key)
            version = case["figma"].get("version_id", "")
            require(not version or meta.get("version_id") == version, "原稿版本不匹配")
        else:
            require(meta.get("effective_theme") == case["theme"] and meta.get("effective_direction") == case["direction"], "实际主题或布局方向未核验或不匹配")
            require(meta.get("raw_screenshot") is True, "须确认来自实际 App 的原始截图")
            require(meta.get("identity_verified") is True and meta.get("stability_verified") is True, "页面身份或布局稳定性未核验")
            require(text(meta.get("route")), "运行入口缺失")
            require(text(meta.get("application_id")) and meta["application_id"] == meta.get("foreground_application_id"), "前台应用与目标应用不一致")
            require(meta.get("data_source") in ("fixture", "service"), "须标明固定测试数据或真实服务")
            require(meta.get("normal_entry_verified") is True, "真实产品入口未验证")
            require(meta.get("data_source") != "fixture" or meta.get("debug_only") is True, "固定状态入口必须仅 Debug 生效")
            anchors = meta.get("anchors", [])
            require(isinstance(anchors, list) and len(anchors) >= 2 and all(text(a) for a in anchors) and len(set(anchors)) >= 2, "至少记录两个实际核验的页面特有锚点")
            device = meta.get("device", {})
            require(isinstance(device, dict), "设备记录必须为对象")
            require(all(text(device.get(k)) for k in ("alias", "os", "orientation")), "设备或方向信息缺失")
            require(all(isinstance(device.get(k), (int, float)) and device[k] > 0 for k in ("width", "height", "scale")), "设备尺寸和缩放缺失")
            build_valid(meta.get("build"))
            require(meta["build"] == builds.get(platform), "截图构建与本轮预期构建不一致")
    except (ValueError, KeyError, TypeError) as error:
        errors.append(str(error))
    return errors


def check_file(record, root, image=False):
    require(isinstance(record, dict), "文件记录缺失")
    path = inside(root, record.get("path"))
    data = path.read_bytes()
    require(bool(data) and sha(data) == record.get("sha256"), "文件缺失、为空或 SHA256 不匹配：" + str(path.name))
    if image:
        width, height = png_info(data)
        require((width, height) == (record.get("width"), record.get("height")), "记录的图像尺寸与实际不符")
    return path


def evaluate_variant(page, run, task, root, variant):
    """只由证据推导状态，手写一个“通过”字段不能绕过缺图与复验要求。"""
    result = {"status": "待对齐", "problems": [], "captures": 0}
    if run is None:
        result["problems"] = ["尚未创建取证轮次"]
        return result
    problems, missing = [], []
    snapshot = run["identity"]
    case = snapshot["variants"][variant]
    for platform in ["figma"] + task["platforms"]:
        capture = run.get("captures", {}).get(variant, {}).get(platform)
        if not capture:
            missing.append(platform + " 缺少截图")
            continue
        issues = metadata_errors(capture.get("metadata"), platform, snapshot, run.get("builds", {}), variant)
        try:
            check_file(capture.get("image"), root, image=True)
            check_file(capture.get("support"), root)
            if capture.get("comparison"):
                check_file(capture["comparison"], root, image=True)
            if platform != "figma":
                image = capture["image"]
                device = capture["metadata"]["device"]
                require((device["width"], device["height"]) == (image["width"], image["height"]), "原始截图像素与设备记录不一致")
        except (ValueError, OSError, KeyError, TypeError, zlib.error, struct.error) as error:
            issues.append(str(error))
        if not issues and platform != "figma":
            result["captures"] += 1
        problems.extend(platform + "：" + issue for issue in issues)
    identity_changed = snapshot["id"] != page["id"] or snapshot["state_id"] != page["state_id"] or case != page["variants"][variant]
    stale = run.get("invalidated_reason") or ("设计身份或基准已变化" if identity_changed else "")
    if run.get("builds") != page.get("expected_builds"):
        stale = stale or "预期构建已变化"
    if stale:
        result.update(status="需复验", problems=[stale] + problems + missing)
        return result
    if problems:
        result.update(status="证据无效", problems=problems + missing)
        return result
    if not case.get("figma"):
        result.update(status="待设计依据", problems=["此主题与方向未绑定对应原稿或经确认的适配依据"] + missing)
        return result
    if missing:
        result.update(status="待截图", problems=missing)
        return result
    review = run.get("review", {}).get(variant, {})
    failures, pending = [], []
    for check in CHECKS:
        item = review.get("checks", {}).get(check, {})
        status = item.get("status")
        allowed_na = check in ("toast", "resource_cleanup") and text(item.get("note"))
        if status == "fail":
            failures.append(LABELS[check] + "未通过")
        elif status != "pass" and not (status == "not_applicable" and allowed_na):
            pending.append(LABELS[check] + "待检查")
        elif not text(item.get("note")):
            pending.append(LABELS[check] + "缺少审查依据")
    failures.extend(issue for issue in review.get("open_issues", []) if text(issue))
    try:
        require(text(review.get("reviewer")), "审查者未记录")
        timestamp(review.get("reviewed_at"))
    except (ValueError, TypeError) as error:
        pending.append(str(error))
    # 没有 Figma 版本号时，用本次原稿和资源清单的不可变快照追溯；不强迫用户管理版本号。
    if not case["figma"].get("version_id"):
        pending += [] if run["captures"][variant]["figma"].get("support") else ["资源基准快照缺失"]
    result.update(status="有差异" if failures else "待验收" if pending else "已通过", problems=failures + pending)
    return result


def evaluate(page, run, task, root):
    """四个组合全部通过才算页面完成，单个主题或方向不能代表整页。"""
    variants = {key: evaluate_variant(page, run, task, root, key) for key in VARIANTS}
    statuses = {item["status"] for item in variants.values()}
    priority = ("证据无效", "需复验", "有差异", "待设计依据", "待截图", "待验收", "待对齐", "已通过")
    status = next(value for value in priority if value in statuses)
    problems = [key + "：" + issue for key, value in variants.items() for issue in value["problems"]]
    return {"status": status, "problems": problems, "captures": sum(v["captures"] for v in variants.values()), "variants": variants}


def summary(ledger, root):
    rows = []
    for page in ledger["pages"]:
        run = find_round(page) if page.get("current_round") else None
        rows.append({"id": page["id"], **evaluate(page, run, ledger["task"], root)})
    passed = sum(r["status"] == "已通过" for r in rows)
    inventory = ledger["task"].get("inventory_complete") is True and text(ledger["task"].get("inventory_basis"))
    return {"pages": rows, "registered": len(rows), "passed": passed, "captures": sum(r["captures"] for r in rows), "inventory_complete": bool(inventory), "complete": bool(rows) and bool(inventory) and passed == len(rows)}


def init_task(args):
    require(text(args.name) and len(args.name) <= 80 and not re.search(r"[/\\\x00-\x1f]", args.name) and args.name not in (".", ".."), "任务名称不可包含路径或控制字符")
    root = Path(args.evidence_root).resolve()
    require(Path(args.evidence_root).is_absolute() and root.is_dir(), "请先核对挂载并创建专属外部证据目录")
    require(not root.is_relative_to(PROJECT), "证据目录必须在仓库外")
    platforms = args.platforms.split(",")
    require(platforms and len(platforms) == len(set(platforms)) and set(platforms).issubset({"ios", "android"}), "平台须为 ios、android 或 ios,android，不可重复")
    directory = PROJECT / "任务记录" / args.name
    note = directory.parent / (directory.name + ".md")
    require(not directory.exists() and not note.exists(), "任务已存在，恢复原台账即可；初始化不会覆盖记录")
    directory.mkdir(parents=True)
    ledger = {"schema_version": 1, "task": {"name": args.name, "scope": args.scope, "evidence_root": str(root), "platforms": platforms, "variants": list(VARIANTS), "inventory_complete": False, "inventory_basis": "", "created_at": now()}, "pages": []}
    write_json(directory / "ui-evidence.json", ledger)
    template = (RESOURCE_ROOT / "assets" / "双端任务记录模板.md").read_text(encoding="utf-8")
    template = template.replace("# 双端任务记录", "# " + args.name, 1)
    template = template.replace("../references/ui-alignment/ui-evidence.md", "../resources/references/ui-alignment/ui-evidence.md")
    note.write_text(template + f"\n## 已创建的证据入口\n\n- [页面台账]({args.name}/ui-evidence.json)\n- 外部证据目录：`{root}`\n- 当前状态：台账已创建，设计页面尚未盘点，尚无 App 截图。\n", encoding="utf-8")
    render_report(ledger, root)
    print(directory / "ui-evidence.json")


def add_page(args, ledger):
    require(not any(p["id"] == args.page for p in ledger["pages"]), "页面 ID 已登记")
    safe_id(args.page)
    safe_id(args.baseline)
    variants = {key: {"theme": key.split("-")[0], "direction": key.split("-")[1], "locale": "en" if key.endswith("ltr") else "ar", "baseline_id": args.baseline, "figma": None, "basis_note": ""} for key in VARIANTS}
    variant = args.theme + "-" + args.direction
    variants[variant].update(locale=args.locale, figma=figma_reference(args), basis_note=args.basis_note)
    require(not any(p["state_id"] == args.state_id and any(v.get("figma") == variants[variant]["figma"] for v in p["variants"].values()) for p in ledger["pages"]), "同一设计状态重复登记")
    ledger["pages"].append({"id": args.page, "module": args.module, "name": args.title, "state_id": args.state_id, "state": args.state, "variants": variants, "expected_builds": {}, "current_round": None, "rounds": []})
    # 增加范围后必须重新确认盘点，不能沿用之前的全量完成声明。
    ledger["task"]["inventory_complete"] = False


def figma_reference(args):
    node = args.node_id.replace("-", ":")
    require(re.fullmatch(r"\d+:\d+", node), "必须提供实际 Figma 节点 ID")
    require(re.fullmatch(r"[A-Za-z0-9]+", args.file_key), "Figma 文件 key 无效")
    return {"file_key": args.file_key, "node_id": node, "version_id": args.version_id}


def new_round(args, ledger):
    page = find_page(ledger, args.page)
    builds = read_json(args.builds)
    require(set(builds) == set(ledger["task"]["platforms"]), "构建清单必须恰好覆盖参与平台")
    for value in builds.values():
        build_valid(value)
    round_id = "R" + str(len(page["rounds"]) + 1).zfill(4)
    page["expected_builds"] = builds
    page["rounds"].append({"id": round_id, "identity": identity(page), "builds": copy.deepcopy(builds), "created_at": now(), "captures": {}, "review": {}, "invalidated_reason": ""})
    page["current_round"] = round_id
    print(round_id)


def attach(args, ledger, root):
    page = find_page(ledger, args.page)
    run = find_round(page, args.round)
    require(args.variant not in run.get("review", {}), "已审查组合不再追加截图，请创建新轮次")
    require(args.platform == "figma" or args.platform in ledger["task"]["platforms"], "该平台不参与本任务")
    captures = run["captures"].setdefault(args.variant, {})
    require(args.platform not in captures, "该平台本轮此主题和方向已有原图，重拍请新建轮次")
    meta = read_json(args.metadata)
    issues = metadata_errors(meta, args.platform, run["identity"], run["builds"], args.variant)
    require(not issues, "；".join(issues))
    image_data = Path(args.image).read_bytes()
    width, height = png_info(image_data)
    support_key = "resources_manifest_path" if args.platform == "figma" else "layout_path"
    require(text(meta.get(support_key)), "采集信息缺少 " + support_key)
    support_data = Path(meta[support_key]).read_bytes()
    require(bool(support_data), "资源清单或布局记录为空")
    comparison_data = None
    if meta.get("comparison_image_path"):
        require(text(meta.get("comparison_transform")), "比较图须记录裁切、缩放及排除区域规则")
        comparison_data = Path(meta["comparison_image_path"]).read_bytes()
        png_info(comparison_data)
    if args.platform != "figma":
        require((meta["device"]["width"], meta["device"]["height"]) == (width, height), "设备像素与截图不一致")
    baseline = run["identity"]["variants"][args.variant]["baseline_id"]
    destination = inside(root, f"pages/{page['id']}/{baseline}/{run['id']}/{args.variant}/{args.platform}")
    destination.mkdir(parents=True, exist_ok=False)

    def save_file(name, content, image=False):
        path = destination / name
        with path.open("xb") as stream:
            stream.write(content)
        record = {"path": str(path.relative_to(root)), "sha256": sha(content)}
        if image:
            record["width"], record["height"] = png_info(content)
        return record

    meta = copy.deepcopy(meta)
    meta.pop(support_key)
    meta.pop("comparison_image_path", None)
    capture = {"metadata": meta, "image": save_file("raw.png", image_data, True), "support": save_file("resources.json" if args.platform == "figma" else "layout.txt", support_data)}
    if comparison_data:
        capture["comparison"] = save_file("comparison.png", comparison_data, True)
    captures[args.platform] = capture


def review_round(args, ledger, root):
    page = find_page(ledger, args.page)
    run = find_round(page, args.round)
    require(args.variant not in run.get("review", {}), "此组合审查已留存；修改或重拍请新建轮次")
    result = evaluate_variant(page, run, ledger["task"], root, args.variant)
    require(result["status"] == "待验收", "只有身份完整、文件有效的轮次可以审查：" + result["status"])
    review = read_json(args.review)
    require(isinstance(review, dict), "审查记录必须是对象")
    require(text(review.get("reviewer")), "审查者未记录")
    timestamp(review.get("reviewed_at"))
    require(isinstance(review.get("open_issues"), list) and all(text(x) for x in review["open_issues"]), "open_issues 必须是问题文本数组，可为空")
    require(isinstance(review.get("checks"), dict) and set(review["checks"]) == set(CHECKS), "检查项须完整覆盖规定清单")
    for key, item in review["checks"].items():
        require(isinstance(item, dict), "检查项必须为对象")
        require(item.get("status") in ("pass", "fail", "not_applicable") and text(item.get("note")), "每项须记录明确结果和实际依据")
        require(item["status"] != "not_applicable" or key in ("toast", "resource_cleanup"), "仅 Toast 和旧资源清理允许有依据地不适用")
    run.setdefault("review", {})[args.variant] = review


def render_report(ledger, root, announce=True):
    """报告为台账派生物，包含失败和历史轮次，不反写证据状态。"""
    report = copy.deepcopy(ledger)
    report["summary"] = summary(ledger, root)
    for page in report["pages"]:
        for run in page["rounds"]:
            run["evaluation"] = evaluate(page, run, ledger["task"], root)
    payload = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (RESOURCE_ROOT / "assets" / "ui-alignment" / "ui-evidence-report.html").read_text(encoding="utf-8")
    output = root / "验收册.html"
    output.write_text(template.replace("__EVIDENCE_DATA__", payload), encoding="utf-8")
    write_json(root / "校验结果.json", report["summary"])
    if announce:
        print(output)


def review_references(ledger):
    """把完成结论绑定到当前轮次的逐组合审查，避免只有一句完成声明。"""
    return [
        {"page_id": page["id"], "round_id": run["id"], "variant": variant,
         "reviewer": review["reviewer"], "reviewed_at": review["reviewed_at"],
         "review_sha256": sha(json.dumps(review, ensure_ascii=False, sort_keys=True).encode("utf-8"))}
        for page in ledger["pages"]
        for run in [find_round(page)]
        for variant in VARIANTS
        for review in [run["review"][variant]]
    ]


def deliver(ledger_path, ledger, root):
    """完整验收后留存不可覆盖的回执；失败只展示缺口，不产生通过回执。"""
    ledger_bytes = ledger_path.read_bytes()
    require(json.loads(ledger_bytes) == ledger, "台账在加载后已变化，请重新执行交付检查")
    render_report(ledger, root, announce=False)
    result = summary(ledger, root)
    if not result["complete"]:
        print(json.dumps({"completion_allowed": False, "summary": result}, ensure_ascii=False, indent=2))
        return 1
    directory = inside(root, "deliveries/" + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    # 验收册仍引用任务根目录的原图；移动到两层归档目录后须保持相对链接有效。
    html = (root / "验收册.html").read_text(encoding="utf-8")
    archived = {
        "台账快照.json": ledger_bytes,
        "校验结果.json": (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "验收册.html": html.replace("<head>", '<head>\n<base href="../../">', 1).encode("utf-8"),
    }
    artifacts = {}
    for name, data in archived.items():
        path = directory / name
        with path.open("xb") as stream:
            stream.write(data)
        artifacts[name] = {"path": str(path.relative_to(root)), "sha256": sha(data)}
    receipt = {"schema_version": 1, "kind": "ui-delivery", "created_at": now(),
               "ledger": {"path": str(ledger_path.resolve()), "sha256": sha(ledger_bytes)},
               "summary": result, "reviews": review_references(ledger), "artifacts": artifacts}
    # 台账只有协调者单写；发布前再核对一次，避免收尾期间的更新沿用旧完成结论。
    require(ledger_path.read_bytes() == ledger_bytes and summary(ledger, root) == result,
            "交付期间台账或证据已变化，请重新核对；本次没有发布通过回执")
    receipt_path = directory / "交付回执.json"
    write_json(receipt_path, receipt)
    print(json.dumps({"completion_allowed": True, "receipt": str(receipt_path),
                      "ledger_sha256": receipt["ledger"]["sha256"], "summary": result}, ensure_ascii=False, indent=2))
    return 0


def verify_delivery(ledger_path, ledger, root, receipt_path):
    """每次使用旧回执都重新检查原始证据，历史通过不能掩盖缺失、篡改或新轮次。"""
    receipt_path = receipt_path.resolve()
    require(receipt_path.is_relative_to(root / "deliveries"), "回执必须位于本任务证据目录的 deliveries 中")
    receipt = read_json(receipt_path)
    require(isinstance(receipt, dict), "交付回执必须是 JSON 对象")
    require(receipt.get("schema_version") == 1 and receipt.get("kind") == "ui-delivery", "不是有效的 UI 交付回执")
    timestamp(receipt.get("created_at"))
    data = ledger_path.read_bytes()
    require(json.loads(data) == ledger, "台账在加载后已变化，请重新核对")
    require(receipt.get("ledger") == {"path": str(ledger_path.resolve()), "sha256": sha(data)},
            "回执对应的台账已变化或属于其他任务，须重新交付检查")
    artifacts = receipt.get("artifacts", {})
    require(isinstance(artifacts, dict) and set(artifacts) == {"台账快照.json", "校验结果.json", "验收册.html"}, "回执缺少台账、检查结果或验收册快照")
    for record in artifacts.values():
        require(check_file(record, root).parent == receipt_path.parent, "交付快照必须与回执位于同一目录")
    require(check_file(artifacts["台账快照.json"], root).read_bytes() == data, "回执的台账快照与当前台账不一致")
    result = summary(ledger, root)
    require(result["complete"] and result == receipt.get("summary"), "当前证据不再满足完整验收，请重新取证或审查")
    require(read_json(check_file(artifacts["校验结果.json"], root)) == result, "归档检查结果与当前证据不一致")
    require(receipt.get("reviews") == review_references(ledger), "回执未绑定当前轮次的完整审查记录")
    require(ledger_path.read_bytes() == data, "核验期间台账已变化，请重新核对")
    print(json.dumps({"completion_allowed": True, "receipt": str(receipt_path),
                      "ledger_sha256": sha(data), "summary": result}, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="逐页截图证据登记、校验与离线验收册生成")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="创建任务记录与空页面台账，不覆盖已有任务")
    init.add_argument("--name", required=True)
    init.add_argument("--scope", required=True)
    init.add_argument("--evidence-root", required=True)
    init.add_argument("--platforms", default="ios,android")
    for command in ("add-page", "bind-reference", "round", "attach", "review", "invalidate", "inventory", "check", "render", "deliver", "verify-delivery"):
        p = sub.add_parser(command)
        p.add_argument("ledger", type=Path)
        if command in ("add-page", "bind-reference", "round", "attach", "review", "invalidate"):
            p.add_argument("--page", required=True)
        if command == "add-page":
            for name in ("module", "title", "state-id", "state", "locale", "baseline", "file-key", "node-id"):
                p.add_argument("--" + name, required=True)
            p.add_argument("--version-id", default="")
            p.add_argument("--theme", choices=("light", "dark"), default="light")
            p.add_argument("--direction", choices=("ltr", "rtl"), default="ltr")
            p.add_argument("--basis-note", default="Figma 对应主题与方向的设计节点")
        elif command == "bind-reference":
            p.add_argument("--variant", required=True, choices=VARIANTS)
            for name in ("baseline", "file-key", "node-id", "locale", "basis-note"):
                p.add_argument("--" + name, required=True)
            p.add_argument("--version-id", default="")
        elif command == "round":
            p.add_argument("--builds", required=True, type=Path)
        elif command in ("attach", "review"):
            p.add_argument("--round")
            p.add_argument("--variant", required=True, choices=VARIANTS)
            if command == "attach":
                p.add_argument("--platform", required=True, choices=("figma", "ios", "android"))
                p.add_argument("--image", required=True, type=Path)
                p.add_argument("--metadata", required=True, type=Path)
            else:
                p.add_argument("--review", required=True, type=Path)
        elif command == "invalidate":
            p.add_argument("--reason", required=True)
        elif command == "inventory":
            p.add_argument("--basis", required=True)
        elif command == "check":
            p.add_argument("--require-complete", action="store_true")
        elif command == "verify-delivery":
            p.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            init_task(args)
            return 0
        ledger, root = load(args.ledger)
        if args.command == "add-page":
            add_page(args, ledger)
        elif args.command == "bind-reference":
            safe_id(args.baseline)
            find_page(ledger, args.page)["variants"][args.variant].update(baseline_id=args.baseline, figma=figma_reference(args), locale=args.locale, basis_note=args.basis_note)
        elif args.command == "round":
            new_round(args, ledger)
        elif args.command == "attach":
            attach(args, ledger, root)
        elif args.command == "review":
            review_round(args, ledger, root)
        elif args.command == "invalidate":
            require(text(args.reason), "失效原因不可为空")
            find_round(find_page(ledger, args.page))["invalidated_reason"] = args.reason
        elif args.command == "inventory":
            require(ledger["pages"] and text(args.basis), "只有完成真实盘点并记录依据后才能确认范围")
            ledger["task"].update(inventory_complete=True, inventory_basis=args.basis)
        elif args.command == "check":
            result = summary(ledger, root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            invalid = any(row["status"] == "证据无效" for row in result["pages"])
            return int(invalid or (args.require_complete and not result["complete"]))
        elif args.command == "render":
            render_report(ledger, root)
            return 0
        elif args.command == "deliver":
            return deliver(args.ledger, ledger, root)
        elif args.command == "verify-delivery":
            return verify_delivery(args.ledger, ledger, root, args.receipt)
        write_json(args.ledger, ledger)
        render_report(ledger, root)
        return 0
    except (ValueError, OSError, KeyError, TypeError, zlib.error, struct.error) as error:
        print("证据流程失败：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

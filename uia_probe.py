# -*- coding: utf-8 -*-
"""
微信 UIA 探针 — 探测微信 4.x 的 UI Automation 元素树
找出消息列表的控件结构，为实时监听做铺垫
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import uiautomation as uia
from uiautomation import Control

uia.SetGlobalSearchTimeout(3)  # 快速超时

WECHAT_CLASSES = ["Qt51514QWindowIcon", "WeChatMainWndForPC", "mm-app", "MainWindow"]


def find_wechat_window() -> Control | None:
    """查找微信主窗口"""
    # 方法1: 通过窗口类名查找
    for cls in WECHAT_CLASSES:
        try:
            win = uia.WindowControl(ClassName=cls)
            if win.Exists(1):
                return win
        except Exception:
            pass

    # 方法2: 通过部分名称匹配（中英文）
    for keyword in ["微信", "WeChat", "Weixin"]:
        try:
            win = uia.WindowControl(Name=keyword)
            if win.Exists(1):
                return win
        except Exception:
            pass
        try:
            win = uia.WindowControl(searchDepth=1, Name=keyword)
            if win.Exists(1):
                return win
        except Exception:
            pass

    return None


def safe_get_props(ctrl: Control) -> dict:
    """安全获取控件属性"""
    props = {}
    for attr in ['Name', 'ClassName', 'ControlType', 'AutomationId', 'BoundingRectangle']:
        try:
            val = getattr(ctrl, attr)
            if val:
                props[attr] = str(val)
        except Exception:
            pass
    return props


def dump_tree(ctrl: Control, depth: int = 0, max_depth: int = 5, file=None):
    """递归打印 UI 树"""
    if depth > max_depth:
        return

    try:
        props = safe_get_props(ctrl)
    except Exception:
        return

    indent = "  " * depth
    name = props.get("Name", "")[:60]
    cls = props.get("ClassName", "")
    ctype = props.get("ControlType", "")
    aid = props.get("AutomationId", "")

    line = f"{indent}[{ctype}] cls={cls} name='{name}' id={aid}"
    print(line)
    if file:
        file.write(line + "\n")

    # 如果包含消息内容的关键词，高亮标记
    try:
        children = ctrl.GetChildren()
    except Exception:
        return

    for child in children:
        dump_tree(child, depth + 1, max_depth, file)


def search_list_controls(ctrl: Control, results: list = None, depth: int = 0) -> list:
    """专门搜索列表类控件（最可能包含消息）"""
    if results is None:
        results = []

    if depth > 8:
        return results

    try:
        ctype = str(ctrl.ControlType)
        if "List" in ctype or "DataGrid" in ctype or "Table" in ctype:
            props = safe_get_props(ctrl)
            children_count = len(ctrl.GetChildren()) if ctrl.GetChildren() else 0
            results.append({
                **props,
                "depth": depth,
                "children_count": children_count,
            })
    except Exception:
        pass

    try:
        for child in ctrl.GetChildren():
            search_list_controls(child, results, depth + 1)
    except Exception:
        pass

    return results


def search_text_rich(ctrl: Control, pattern: str = "", depth: int = 0, max_depth: int = 6):
    """搜索包含特定文本的控件（用于定位消息区域）"""
    try:
        name = str(ctrl.Name) if ctrl.Name else ""
        if pattern and pattern in name:
            props = safe_get_props(ctrl)
            print(f"  [命中] depth={depth} {props}")
    except Exception:
        pass

    if depth >= max_depth:
        return

    try:
        for child in ctrl.GetChildren():
            search_text_rich(child, pattern, depth + 1, max_depth)
    except Exception:
        pass


def monitor_chat_list(ctrl: Control, duration: int = 30):
    """
    实时监听聊天列表变化 — 验证方案可行性
    使用 UIA 的 AddAutomationEventHandler 监听元素添加事件
    """
    import time

    print(f"\n{'='*60}")
    print("  🔍 实时监听模式（{0}秒内检测列表变化）".format(duration))
    print("  请在微信中打开一个聊天窗口，让人给你发几条消息...")
    print("="*60)

    # 先找列表控件
    lists = search_list_controls(ctrl)
    if not lists:
        print("❌ 未找到列表控件，放弃实时监听")
        return

    print(f"\n找到 {len(lists)} 个列表类控件：")
    for i, lst in enumerate(lists):
        print(f"  [{i}] {lst.get('ControlType')} cls={lst.get('ClassName')} "
              f"name='{lst.get('Name','')[:40]}' children={lst.get('children_count')}")

    # 尝试对最可能的列表做轮询快照
    target = lists[0]  # 默认第一个
    # 优先选 children_count 最大的
    best = max(lists, key=lambda x: x.get('children_count', 0))
    if best.get('children_count', 0) > 0:
        target = best

    print(f"\n📌 监听目标: {target.get('ControlType')} name='{target.get('Name','')[:40]}'")

    # 轮询快照对比
    prev_count = target.get('children_count', 0)
    start = time.time()
    checks = 0

    while time.time() - start < duration:
        time.sleep(0.5)
        checks += 1

        # 重新获取
        fresh_lists = search_list_controls(ctrl)
        if not fresh_lists:
            continue

        # 找同名列表
        current = None
        for lst in fresh_lists:
            if lst.get('ClassName') == target.get('ClassName'):
                current = lst
                break
        if not current:
            current = max(fresh_lists, key=lambda x: x.get('children_count', 0))

        cur_count = current.get('children_count', 0)
        if cur_count != prev_count:
            print(f"  📩 检测到变化！子元素: {prev_count} → {cur_count} (第{checks}次，{time.time()-start:.1f}s)")
            prev_count = cur_count

            # 尝试读取最新子元素的内容
            try:
                ctrl_obj = uia.ControlFromPoint(0, 0)  # 占位，需要用正确的方式找到列表
                # 方法：从主窗口重新定位到列表
                print("    尝试读取最新消息内容...")

                # Walk to the list element
                walk_to_list_and_read(ctrl, target)
            except Exception as e:
                print(f"    读取失败: {e}")

    print(f"\n监听结束，共检查 {checks} 次")


def walk_to_list_and_read(main_win: Control, list_info: dict):
    """尝试走到列表控件并读取最后几个子元素"""
    # 重新搜索并读取
    lists = search_list_controls(main_win)
    if not lists:
        return

    best = max(lists, key=lambda x: x.get('children_count', 0))
    if best.get('children_count', 0) == 0:
        return

    # 尝试用 searchDepth 定位
    try:
        list_ctrl = uia.ListControl(
            searchDepth=10,
            ClassName=best.get('ClassName', '')
        )
        if list_ctrl.Exists(0.5):
            items = list_ctrl.GetChildren()
            print(f"    列表共有 {len(items)} 项")
            # 打印最后 3 项
            for item in items[-3:]:
                props = safe_get_props(item)
                print(f"      -> {props}")
    except Exception as e:
        print(f"    定位列表失败: {e}")


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 60)
    print("  🔎 微信 UIA 探针 — UI Automation 树结构分析")
    print("=" * 60)

    print("\n[1] 查找微信窗口...")
    win = find_wechat_window()

    if not win:
        print("❌ 未找到微信窗口！")
        print("请确认：")
        print("  1. 微信已启动并登录")
        print("  2. 微信窗口可见（不要最小化到托盘）")
        sys.exit(1)

    props = safe_get_props(win)
    print(f"✅ 找到微信窗口: {props}")
    print(f"   矩形: {win.BoundingRectangle}")

    # ----- 阶段 1: 树结构快照 -----
    print(f"\n[2] 导出 UI 树结构（最大深度 5）...")
    tree_file = "uia_tree_dump.txt"
    with open(tree_file, "w", encoding="utf-8") as f:
        dump_tree(win, max_depth=5, file=f)
    print(f"✅ 树结构已保存到 {tree_file}")

    # 同时打印到屏幕（截断版，只显示有名字/类型的节点）
    print("\n--- UI 树结构（精简版）---")
    with open(tree_file, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            # 过滤纯空行但保留结构
            if stripped:
                print(stripped)
    print("--- 树结构结束 ---")

    # ----- 阶段 2: 搜索列表控件 -----
    print(f"\n[3] 搜索列表/表格控件（可能承载消息）...")
    lists = search_list_controls(win)
    if lists:
        print(f"✅ 找到 {len(lists)} 个列表控件：")
        for lst in lists:
            print(f"    [{lst.get('ControlType')}] cls={lst.get('ClassName')} "
                  f"name='{lst.get('Name','')[:50]}' "
                  f"depth={lst.get('depth')} children={lst.get('children_count')}")
    else:
        print("❌ 未找到列表控件")

    # ----- 阶段 3: 搜索消息文本 -----
    print(f"\n[4] 搜索控件中可读文本（前 100 字）...")
    try:
        # 获取所有带 Name 的控件
        text_ctrls = []
        def collect_text(ctrl, depth=0, max_d=6):
            if depth > max_d:
                return
            try:
                name = str(ctrl.Name).strip() if ctrl.Name else ""
                if name and len(name) > 2:
                    text_ctrls.append((name[:80], str(ctrl.ControlType), depth))
            except Exception:
                pass
            try:
                for child in ctrl.GetChildren():
                    collect_text(child, depth+1, max_d)
            except Exception:
                pass

        collect_text(win)
        if text_ctrls:
            print(f"  共 {len(text_ctrls)} 个有文本的控件，显示前 15 个：")
            for name, ctype, depth in text_ctrls[:15]:
                print(f"    [{ctype}] depth={depth} text='{name}'")
        else:
            print("  未找到带文本的控件（微信可能用自定义渲染）")
    except Exception as e:
        print(f"  搜索异常: {e}")

    # ----- 阶段 4: 实时监听测试 -----
    print(f"\n[5] 实时监听测试...")
    monitor_chat_list(win, duration=20)

    # ----- 结论 -----
    print(f"\n{'='*60}")
    print("  📊 探测结论")
    print("="*60)
    if lists and any(l.get('children_count', 0) > 0 for l in lists):
        print("✅ 发现有内容的列表控件，UIA 方案可行！")
        print("   下一步：编写 UIA 消息监听器")
    elif lists:
        print("⚠️  找到列表控件但内容为空（可能需要打开聊天窗口）")
        print("   请打开一个聊天窗口后重新运行此脚本")
    else:
        print("❌ 未找到列表控件。微信 4.x 可能：")
        print("   1. 使用 DirectUI/自绘控件（不暴露 UI 元素树）")
        print("   2. 消息区域用 WebView 渲染（Electron/CEF）")
        print("   如果这样，就需要回退到 OCR 方案")


if __name__ == "__main__":
    main()

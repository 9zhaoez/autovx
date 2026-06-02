# -*- coding: utf-8 -*-
"""
实时监听诊断脚本 — 逐步测试每一步是否正常
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time

print("=" * 60)
print("  实时监听诊断")
print("=" * 60)

# 1. 检查导入
print("\n[1] 检查导入...")
try:
    from realtime_monitor import RealtimeChatMonitor, ScreenWatcher
    print("  ✅ realtime_monitor 导入成功")
except Exception as e:
    print(f"  ❌ 导入失败: {e}")
    sys.exit(1)

# 2. 找微信窗口
print("\n[2] 查找微信窗口...")
import win32gui, win32process, psutil

WECHAT_PROCESS_NAMES = ["Weixin.exe", "WeChat.exe", "WeChatAppEx.exe"]
WECHAT_WINDOW_CLASSES = ["Qt51514QWindowIcon", "WeChatMainWndForPC"]

# 先按进程名确认在运行
for proc in psutil.process_iter(["pid", "name"]):
    try:
        name = str(proc.info.get("name", ""))
        if any(n.lower() == name.lower() for n in WECHAT_PROCESS_NAMES):
            print(f"  ✅ 找到微信进程: {name} (PID: {proc.info['pid']})")
            break
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue

# 再按类名直接搜窗口（微信UI窗口可能在不同子进程）
main_hwnd = None

def enum_cb(hwnd, _):
    if not win32gui.IsWindowVisible(hwnd):
        return
    cls = win32gui.GetClassName(hwnd)
    title = win32gui.GetWindowText(hwnd)
    for wc in WECHAT_WINDOW_CLASSES:
        if wc in cls:
            global main_hwnd
            main_hwnd = hwnd
            print(f"  ✅ 找到窗口: class={cls} title={title[:30]}")
            rect = win32gui.GetWindowRect(hwnd)
            print(f"     矩形: ({rect[0]},{rect[1]})-({rect[2]},{rect[3]}) {rect[2]-rect[0]}x{rect[3]-rect[1]}")
            return

win32gui.EnumWindows(enum_cb, None)

if not main_hwnd:
    print("  ❌ 未找到微信窗口！")
    sys.exit(1)

def get_rect():
    if main_hwnd:
        rect = win32gui.GetWindowRect(main_hwnd)
        return (rect[0], rect[1], rect[2], rect[3])
    return None

# 3. 测试截图区域
print("\n[3] 测试截图区域...")
rect = get_rect()
if rect:
    left, top, right, bottom = rect
    w = right - left
    h = bottom - top
    chat_top = top + int(h * 0.12)
    chat_bottom = top + int(h * 0.85)
    chat_height = chat_bottom - chat_top
    capture_top = chat_bottom - int(chat_height * 0.35)
    capture_height = chat_bottom - capture_top
    print(f"  窗口: {w}x{h}")
    print(f"  聊天区: top={chat_top}, bottom={chat_bottom}")
    print(f"  截取区: top={capture_top}, height={capture_height}, width={w}")

    if capture_height < 50:
        print(f"  ❌ 截取高度太小 ({capture_height}px)")
    else:
        print(f"  ✅ 截取区域合理")
else:
    print("  ❌ 无法获取窗口矩形")
    sys.exit(1)

# 4. 测试截图
print("\n[4] 测试截图（mss）...")
try:
    import mss
    import numpy as np
    with mss.mss() as sct:
        monitor = {"left": left, "top": capture_top, "width": w, "height": capture_height}
        img = sct.grab(monitor)
        arr = np.array(img)[:, :, :3]
        print(f"  ✅ 截图成功: {arr.shape}")
        # 保存截图供检查
        import cv2, os
        os.makedirs("photo", exist_ok=True)
        cv2.imwrite("photo/debug_capture.png", arr)
        print(f"  已保存到 photo/debug_capture.png，请检查是否截到了消息区域")

        # 哈希测试
        import hashlib
        h1 = hashlib.md5(arr.tobytes()).hexdigest()
        print(f"  当前哈希: {h1[:16]}...")
except Exception as e:
    print(f"  ❌ 截图失败: {e}")

# 5. 测试 OCR
print("\n[5] 测试 OCR...")
try:
    from ocr_reader import OCRReader
    ocr = OCRReader(engine='easyocr', bottom_ratio=0.35, debug=True)
    if ocr.available:
        print("  ✅ OCR 引擎可用")
        # 直接读一次
        result = ocr.read_latest_message(rect)
        if result:
            print(f"  ✅ OCR 识别结果: {result[:80]}")
        else:
            print("  ⚠️  OCR 未识别到文字（窗口聊天区可能没有新消息或者截图区域不对）")
    else:
        print("  ❌ OCR 引擎不可用")
except Exception as e:
    import traceback
    print(f"  ❌ OCR 测试失败: {e}")
    traceback.print_exc()

# 6. 测试屏幕差分
print("\n[6] 测试屏幕差分（5 秒内检测变化）...")
print("  请在这 5 秒内在微信聊天窗口发一条消息...")

detections = []
def on_detect(text):
    detections.append(text)
    print(f"  📩 检测到: {text[:60]}...")

monitor = RealtimeChatMonitor(
    get_window_rect=get_rect,
    on_new_message=on_detect,
    ocr_engine='easyocr',
    bottom_ratio=0.35,
    debug=True,
)
monitor.start()

# 等待 8 秒看有没有检测到
try:
    time.sleep(8)
except KeyboardInterrupt:
    pass

monitor.stop()

if detections:
    print(f"\n  ✅ 检测到 {len(detections)} 条消息:")
    for d in detections:
        print(f"     -> {d[:60]}")
else:
    print("\n  ❌ 8 秒内未检测到任何消息")
    print("  可能原因：")
    print("    1. 没有人给你发新消息")
    print("    2. 截图区域没覆盖到消息区（检查 debug_capture.png）")
    print("    3. OCR 识别失败")
    print("    4. 画面确实没变化（窗口被遮挡或聊天区没更新）")

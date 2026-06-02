# -*- coding: utf-8 -*-
"""
实时屏幕差分监听模块 — 事件驱动式消息检测
持续监控微信聊天区底部像素变化，变化时触发 OCR，空闲时几乎零开销

原理：
  - 每 80ms 截一次聊天区底部（仅 ~200×300px，极快）
  - 对像素数据取哈希，与上一帧对比
  - 哈希变化 → 新消息正在渲染 → 等待稳定后 OCR
  - 无变化时不做 OCR，CPU 占用接近 0

对比旧的轮询方式：
  旧：sleep(3s) → OCR → sleep(3s) → OCR  （不管有没有新消息都 OCR）
  新：watch → 变化! → 等 300ms 稳定 → OCR → 继续 watch（只有变化才 OCR）
"""

import time
import hashlib
import threading
from typing import Optional, Callable, Tuple

import numpy as np


class ScreenWatcher:
    """屏幕差分监听器 — 发现画面变化时回调"""

    def __init__(
        self,
        on_change: Callable[[], Optional[str]],
        capture_interval: float = 0.08,   # 截图间隔（秒），80ms 足够灵敏
        settle_time: float = 0.35,         # 变化后的稳定等待时间
        min_change_ratio: float = 0.001,   # 触发变化的最小像素比例（避免噪声）
    ):
        self.on_change = on_change
        self.capture_interval = capture_interval
        self.settle_time = settle_time
        self.min_change_ratio = min_change_ratio

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_frame_hash: Optional[str] = None
        self._last_frame_data: Optional[bytes] = None
        self._change_count = 0
        self._stable_count = 0
        self._last_ocr_time = 0.0    # 上次 OCR 时间戳
        self._ocr_cooldown = 1.5     # OCR 最小间隔（秒）
        self._sct = None  # 持久化 mss 实例

    def _grab_region(self, left: int, top: int, width: int, height: int) -> Optional[np.ndarray]:
        """极速截取屏幕区域 → numpy 数组"""
        try:
            if self._sct is None:
                import mss
                # mss v10+: use MSS() (class), not mss() (deprecated function)
                try:
                    self._sct = mss.MSS()
                except AttributeError:
                    self._sct = mss.mss()
            monitor = {"left": left, "top": top, "width": width, "height": height}
            img = self._sct.grab(monitor)
            return np.array(img)[:, :, :3]  # BGRA → BGR
        except ImportError:
            try:
                import pyautogui
                img = pyautogui.screenshot(region=(left, top, width, height))
                return np.array(img)[:, :, ::-1]
            except Exception:
                return None
        except Exception:
            return None

    def _hash_frame(self, frame: np.ndarray) -> str:
        """快速像素哈希 — 自适应降采样，确保小图也能检测到变化"""
        h, w = frame.shape[:2]
        # 目标：至少保留 40 行有效采样（不再低于这个）
        # 对 130px 高的截图，scale 最大为 3，保留 43 行 → 足够看到新文字
        scale = max(1, h // 40)
        if scale > 1:
            # 2D 降采样：取每块的平均值而不是跳行，避免完全漏掉细线
            new_h, new_w = h // scale, w // scale
            # 裁剪到 scale 的整数倍
            h_crop = new_h * scale
            w_crop = new_w * scale
            cropped = frame[:h_crop, :w_crop]
            # reshape + mean 做块平均
            small = cropped.reshape(new_h, scale, new_w, scale, -1).mean(axis=(1, 3)).astype(frame.dtype)
        else:
            small = frame.copy()
        data = small.tobytes()
        return hashlib.md5(data).hexdigest()

    def _frame_changed(self, frame: np.ndarray) -> bool:
        """判断画面是否发生变化"""
        new_hash = self._hash_frame(frame)

        if self._last_frame_hash is None:
            self._last_frame_hash = new_hash
            return False

        changed = new_hash != self._last_frame_hash
        self._last_frame_hash = new_hash
        return changed

    def _watch_loop(self, get_region: Callable[[], Optional[Tuple[int, int, int, int]]]):
        """主监听循环（防崩溃）"""
        settle_deadline = 0.0
        last_ocr_result: Optional[str] = None
        loop_count = 0

        while self._running:
            try:
                loop_count += 1
                region = get_region()

                # 首次/定期打印状态
                if loop_count == 1:
                    print(f"[Watcher] 启动，区域={region}")

                if region is None:
                    if loop_count <= 1:
                        print("[Watcher] get_region 返回 None（窗口不可用？）")
                    time.sleep(0.5)
                    continue

                left, top, width, height = region
                if width <= 0 or height <= 0:
                    time.sleep(0.5)
                    continue

                frame = self._grab_region(left, top, width, height)
                if frame is None:
                    if loop_count <= 1:
                        print("[Watcher] 截图返回 None")
                    time.sleep(0.2)
                    continue

                if loop_count == 1:
                    print(f"[Watcher] 首帧尺寸: {frame.shape}")

                changed = self._frame_changed(frame)

                if changed:
                    self._change_count += 1
                    if self._change_count <= 3:
                        print(f"[Watcher] 🔔 检测到画面变化 (第{self._change_count}次)")
                    settle_deadline = time.time() + self.settle_time
                elif settle_deadline > 0 and time.time() >= settle_deadline:
                    # 画面已稳定 → 检查冷却 → 触发 OCR
                    settle_deadline = 0.0
                    if time.time() - self._last_ocr_time < self._ocr_cooldown:
                        continue  # 冷却中，跳过
                    self._last_ocr_time = time.time()
                    self._stable_count += 1
                    print(f"[Watcher] 📷 画面稳定，触发 OCR (第{self._stable_count}次)")
                    try:
                        result = self.on_change()
                        if result:
                            print(f"[Watcher] ✅ OCR 结果: {result[:50]}...")
                            last_ocr_result = result
                        else:
                            print(f"[Watcher] ⏭ OCR 返回 None（未识别/去重命中）")
                    except Exception as e:
                        import traceback
                        print(f"[Watcher] ❌ OCR 异常: {e}")
                        traceback.print_exc()

                time.sleep(self.capture_interval)
            except Exception as e:
                import traceback
                print(f"[Watcher] 💥 主循环异常: {e}")
                traceback.print_exc()
                print("[Watcher] 继续运行...")
                time.sleep(0.5)

    def start(self, get_region: Callable[[], Optional[Tuple[int, int, int, int]]]):
        """
        启动监听
        get_region: 返回 (left, top, width, height) 的函数，返回 None 表示当前不可用
        """
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            args=(get_region,),
            daemon=True,
        )
        self._thread.start()

    def reset_baseline(self):
        """重置画面基准：下次只有画面再次变化才触发 OCR"""
        self._last_frame_hash = None

    def stop(self):
        """停止监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def stats(self) -> dict:
        return {
            "changes_detected": self._change_count,
            "ocr_triggered": self._stable_count,
        }


class RealtimeChatMonitor:
    """
    实时聊天监视器 — 封装 ScreenWatcher + OCRReader
    替代原来的定时轮询，实现事件驱动的消息检测
    """

    def __init__(
        self,
        get_window_rect: Callable[[], Optional[Tuple[int, int, int, int]]],
        on_new_message: Callable[[str], None],
        ocr_engine: str = "easyocr",
        bottom_ratio: float = 0.35,
        left_ratio: float = 0.0,
        right_ratio: float = 0.0,
        top_ratio: float = 0.12,
        bottom_offset_ratio: float = 0.85,
        debug: bool = False,
    ):
        self.get_window_rect = get_window_rect
        self.on_new_message = on_new_message
        self.ocr_engine = ocr_engine
        self.bottom_ratio = bottom_ratio
        self.left_ratio = left_ratio
        self.right_ratio = right_ratio
        self.top_ratio = top_ratio
        self.bottom_offset_ratio = bottom_offset_ratio
        self.debug = debug
        self.ocr = None
        self.last_text_hash: Optional[str] = None
        self._reply_cooldown_until = 0.0  # 回复后的冷却时间戳
        self._last_reply_prefix = ""      # 上次回复的前8个字，用于过滤自己的消息
        self._init_ocr()

    def _init_ocr(self):
        """延迟初始化 OCR（首次使用时加载模型）"""
        from ocr_reader import OCRReader
        self.ocr = OCRReader(
            engine=self.ocr_engine,
            bottom_ratio=self.bottom_ratio,
            left_ratio=self.left_ratio,
            right_ratio=self.right_ratio,
            top_ratio=self.top_ratio,
            bottom_offset_ratio=self.bottom_offset_ratio,
            debug=self.debug,
        )

    def _get_chat_bottom_region(self) -> Optional[Tuple[int, int, int, int]]:
        """获取聊天区底部区域坐标（用于像素差分）"""
        rect = self.get_window_rect()
        if rect is None:
            return None
        left, top, right, bottom = rect
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            return None

        # 排除左侧联系人栏
        cap_left = left + int(w * self.left_ratio)
        cap_right = right - int(w * self.right_ratio)
        cap_w = cap_right - cap_left

        # 聊天区（使用可配置比例）
        chat_top = top + int(h * self.top_ratio)
        chat_bottom = top + int(h * self.bottom_offset_ratio)
        chat_height = chat_bottom - chat_top

        # 截取底部
        capture_top = chat_bottom - int(chat_height * self.bottom_ratio)
        capture_height = chat_bottom - capture_top

        if capture_height < 50 or cap_w < 100:
            return None

        return (cap_left, capture_top, cap_w, capture_height)

    def _ocr_and_detect(self) -> Optional[str]:
        """OCR 识别最新消息并去重"""
        # 回复后冷却期：等待屏幕稳定，防止读到自己刚发的消息
        if time.time() < self._reply_cooldown_until:
            return None
        if self.ocr is None:
            print("[OCR-Detect] OCR 引擎为 None")
            return None
        if not self.ocr.available:
            print("[OCR-Detect] OCR 引擎不可用")
            return None

        rect = self.get_window_rect()
        if rect is None:
            print("[OCR-Detect] 窗口矩形为 None")
            return None

        img = self.ocr.capture_bottom(rect)
        if img is None:
            print("[OCR-Detect] capture_bottom 返回 None")
            return None

        texts = self.ocr.recognize(img)
        if not texts:
            return None

        groups = self.ocr._cluster_texts(texts, img_height=img.shape[0])
        if not groups:
            return None

        # 只取最后一条消息
        latest = ' '.join(t[0] for t in groups[-1]).strip()
        if not latest:
            return None
        full_text = latest

        # 过滤自己刚发的回复：如果最新一条就是自己发的，跳过
        if hasattr(self, '_last_reply_prefix') and self._last_reply_prefix and len(self._last_reply_prefix) >= 2:
            clean = latest.strip().replace(' ', '')
            prefix = self._last_reply_prefix.replace(' ', '')
            if clean.startswith(prefix) or (len(prefix) >= 4 and prefix in clean):
                print(f"[OCR-Detect] ⏭ 自己的回复: {latest[:40]}...")
                return None

        # MD5 去重（只对最后一条做去重，因为那是新消息的触发点）
        text_hash = hashlib.md5(latest.encode('utf-8')).hexdigest()
        if text_hash == self.last_text_hash:
            print(f"[OCR-Detect] ⏭ 去重: {latest[:40]}...")
            return None
        self.last_text_hash = text_hash

        print(f"[OCR-Detect] ✅ 新消息: {latest[:40]}...")
        return full_text

    def set_replied(self, text: str, reply_text: str = ""):
        """回复后：长冷却 + 重置基准 + 去重"""
        self._reply_cooldown_until = time.time() + 5.0  # 5秒冷却，覆盖动画
        if hasattr(self, 'watcher') and self.watcher:
            self.watcher.reset_baseline()
        # 存回复文本用于后续过滤
        if reply_text:
            self._last_reply_prefix = reply_text.strip()[:10]
        else:
            self._last_reply_prefix = ""
        # 存最新消息的去重哈希
        if text:
            self.last_text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()

    def start(self):
        """启动实时监听"""

        # 包装回调：OCR 识别到新文本时通知上层
        def on_screen_change() -> Optional[str]:
            result = self._ocr_and_detect()
            if result:
                self.on_new_message(result)
            return result

        self.watcher = ScreenWatcher(
            on_change=on_screen_change,
            capture_interval=0.08,
            settle_time=0.35,
        )
        self.watcher.start(self._get_chat_bottom_region)

    def reset_dedup(self):
        """（保留接口，已弃用）"""
        pass

    def set_replied(self, text: str, reply_text: str = ""):
        """回复后：长冷却 + 重置基准 + 去重"""
        self._reply_cooldown_until = time.time() + 5.0  # 5秒冷却，覆盖动画
        if hasattr(self, 'watcher') and self.watcher:
            self.watcher.reset_baseline()
        # 存回复文本用于后续过滤
        if reply_text:
            self._last_reply_prefix = reply_text.strip()[:10]
        else:
            self._last_reply_prefix = ""
        # 存最新消息的去重哈希
        if text:
            self.last_text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()

    def stop(self):
        """停止监听"""
        if hasattr(self, 'watcher'):
            self.watcher.stop()

    @property
    def stats(self) -> dict:
        if hasattr(self, 'watcher'):
            return self.watcher.stats
        return {}

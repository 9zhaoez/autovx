# -*- coding: utf-8 -*-
"""
OCR 消息读取模块 — 方案 B：截取聊天区底部 1/3
通过截图 + OCR 识别微信聊天区最新消息，替代剪贴板方案
"""

import ctypes
import time
import hashlib
from typing import Optional, List, Tuple

import numpy as np

# ── DPI 适配：让进程获取真实物理像素坐标 ────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class OCRReader:
    """OCR 消息读取器 — 纯截图识别，不碰剪贴板"""

    def __init__(self, engine: str = 'easyocr', bottom_ratio: float = 0.35,
                 left_ratio: float = 0.0, right_ratio: float = 0.0,
                 top_ratio: float = 0.12, bottom_offset_ratio: float = 0.85,
                 debug: bool = False):
        self.engine_name = engine
        self.bottom_ratio = bottom_ratio
        self.left_ratio = left_ratio
        self.right_ratio = right_ratio
        self.top_ratio = top_ratio
        self.bottom_offset_ratio = bottom_offset_ratio
        self.debug = debug
        self.engine = None
        self.last_text_hash: Optional[str] = None
        self._capture_count = 0  # 截图计数，前几次自动存 debug
        self._init_engine()

    # ── 引擎初始化 ────────────────────────────────────────

    def _init_engine(self):
        if self.engine_name == 'easyocr':
            try:
                import easyocr
                self.engine = easyocr.Reader(
                    ['ch_sim', 'en'], gpu=False, verbose=False
                )
                print("✅ EasyOCR 初始化完成")
            except ImportError:
                print("⚠️  未安装 easyocr，运行: pip install easyocr")
            except Exception as e:
                print(f"⚠️  EasyOCR 初始化失败: {e}")

        elif self.engine_name == 'paddleocr':
            try:
                from paddleocr import PaddleOCR
                self.engine = PaddleOCR(lang='ch', show_log=False)
                print("✅ PaddleOCR 初始化完成")
            except ImportError:
                print("⚠️  未安装 paddleocr，运行: pip install paddleocr")
            except Exception as e:
                print(f"⚠️  PaddleOCR 初始化失败: {e}")

        elif self.engine_name == 'rapidocr':
            try:
                from rapidocr_onnxruntime import RapidOCR
                self.engine = RapidOCR()
                print("✅ RapidOCR 初始化完成")
            except ImportError:
                print("⚠️  未安装 rapidocr，运行: pip install rapidocr-onnxruntime")
            except Exception as e:
                print(f"⚠️  RapidOCR 初始化失败: {e}")

    @property
    def available(self) -> bool:
        return self.engine is not None

    # ── 图像预处理 ────────────────────────────────────────

    def _preprocess(self, img: np.ndarray) -> np.ndarray:
        """灰度化 → CLAHE 增强对比度 → 2x 放大"""
        import cv2

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        h, w = enhanced.shape
        upscaled = cv2.resize(enhanced, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        return upscaled

    # ── 截图 ──────────────────────────────────────────────

    def capture_bottom(self, window_rect: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        """
        截取微信聊天区底部区域
        window_rect: (left, top, right, bottom) — 已经是物理像素（DPI 适配后）
        """
        left, top, right, bottom = window_rect
        w = right - left
        h = bottom - top

        if w <= 0 or h <= 0:
            print(f"[OCR] 窗口尺寸异常: w={w}, h={h}")
            return None

        # 排除左侧联系人栏和右侧空白
        capture_left = left + int(w * self.left_ratio)
        capture_right = right - int(w * self.right_ratio)
        capture_w = capture_right - capture_left

        # 聊天区范围（使用可配置的比例）
        chat_top = top + int(h * self.top_ratio)
        chat_bottom = top + int(h * self.bottom_offset_ratio)
        chat_height = chat_bottom - chat_top

        # 截取聊天区底部
        capture_top = chat_bottom - int(chat_height * self.bottom_ratio)
        capture_height = chat_bottom - capture_top

        if capture_height < 50:
            print(f"[OCR] 截图高度太小: {capture_height}px，窗口可能太小")
            return None

        if capture_w < 100:
            print(f"[OCR] 截图宽度太小: {capture_w}px（left_ratio={self.left_ratio}可能太大）")
            return None

        self._capture_count += 1

        try:
            import mss
        except ImportError:
            return self._capture_fallback(capture_left, capture_top, capture_w, capture_height)

        with mss.mss() as sct:
            monitor = {
                "left": capture_left,
                "top": capture_top,
                "width": capture_w,
                "height": capture_height,
            }
            screenshot = sct.grab(monitor)
            img = np.array(screenshot)[:, :, :3].copy()  # BGRA → BGR

        # 前 5 次自动保存 debug 截图，方便排查
        if self.debug or self._capture_count <= 5:
            self._save_debug(img, capture_top, capture_height, capture_w)

        return self._preprocess(img)

    def _capture_fallback(self, left, top, w, height) -> Optional[np.ndarray]:
        """pyautogui 截图兜底"""
        try:
            import pyautogui
            screenshot = pyautogui.screenshot(region=(left, top, w, height))
            img = np.array(screenshot)[:, :, ::-1].copy()
            return self._preprocess(img)
        except Exception as e:
            print(f"[OCR] 截图失败: {e}")
            return None

    @staticmethod
    def _cleanup_photos():
        """photo 文件夹图片超过 10 张时，删除最旧的前 9 张"""
        import os, glob
        files = sorted(glob.glob("photo/*.png"), key=os.path.getmtime)
        if len(files) > 10:
            for f in files[:9]:
                try:
                    os.remove(f)
                except OSError:
                    pass

    def _save_debug(self, img: np.ndarray, capture_top: int, capture_height: int, capture_width: int):
        """保存调试截图到 photo 文件夹"""
        import os, cv2
        os.makedirs("photo", exist_ok=True)
        ts = time.strftime('%H%M%S')
        raw_path = f"photo/debug_ocr_raw_{ts}.png"
        cv2.imwrite(raw_path, img)
        self._cleanup_photos()
        if self._capture_count <= 5:
            print(f"[OCR] 🔍 调试截图已保存: {raw_path} "
                  f"(区域: top={capture_top}, h={capture_height}, w={capture_width})")

    # ── OCR 识别 ──────────────────────────────────────────

    def recognize(self, img: np.ndarray) -> List[Tuple[str, float, Tuple[float, float]]]:
        """OCR 识别，返回按 y 坐标排序的文本列表 [(text, conf, (x,y)), ...]"""
        if self.engine_name == 'easyocr':
            try:
                results = self.engine.readtext(img, detail=1)
            except Exception as e:
                print(f"[OCR] EasyOCR 识别异常: {e}")
                return []
            if not results:
                return []

            texts = []
            for bbox, text, conf in results:
                if conf < 0.2:
                    continue
                t = text.strip()
                if not t:
                    continue
                x = bbox[0][0]
                y = bbox[0][1]
                texts.append((t, conf, (x, y)))

            texts.sort(key=lambda item: item[2][1])
            return texts

        elif self.engine_name == 'paddleocr':
            try:
                results = self.engine.ocr(img, cls=False)
            except Exception as e:
                print(f"[OCR] PaddleOCR 识别异常: {e}")
                return []
            if not results or not results[0]:
                return []

            texts = []
            for line in results[0]:
                bbox, (text, conf) = line
                if conf < 0.2:
                    continue
                t = text.strip()
                if not t:
                    continue
                texts.append((t, conf, (bbox[0][0], bbox[0][1])))
            texts.sort(key=lambda item: item[2][1])
            return texts

        elif self.engine_name == 'rapidocr':
            try:
                results, _ = self.engine(img)
            except Exception as e:
                print(f"[OCR] RapidOCR 识别异常: {e}")
                return []
            if not results:
                return []

            texts = []
            for line in results:
                bbox, text, conf = line
                conf = float(conf) if isinstance(conf, str) else conf
                if conf < 0.2:
                    continue
                t = text.strip()
                if not t:
                    continue
                texts.append((t, conf, (bbox[0][0], bbox[0][1])))
            texts.sort(key=lambda item: item[2][1])
            return texts

        return []

    # ── 消息聚类 ──────────────────────────────────────────

    def _cluster_texts(
        self,
        texts: List[Tuple[str, float, Tuple[float, float]]],
        img_height: int = 200,
    ) -> List[List[Tuple[str, float, Tuple[float, float]]]]:
        """按 y 间距聚类为消息组"""
        if not texts:
            return []

        gap_threshold = max(12, img_height * 0.04)

        groups = []
        current_group = [texts[0]]

        for i in range(1, len(texts)):
            prev_y = current_group[-1][2][1]
            curr_y = texts[i][2][1]
            gap = curr_y - prev_y

            if gap > gap_threshold:
                groups.append(current_group)
                current_group = [texts[i]]
            else:
                current_group.append(texts[i])

        groups.append(current_group)
        return groups

    # ── 主入口 ────────────────────────────────────────────

    def read_latest_message(self, window_rect: Tuple[int, int, int, int]) -> Optional[str]:
        """截图 → 预处理 → OCR → 聚类 → 取最新消息 → 去重"""
        if not self.available:
            return None

        img = self.capture_bottom(window_rect)
        if img is None:
            return None

        texts = self.recognize(img)

        if not texts:
            # 每 10 次无结果才打印一次，避免刷屏
            if self._capture_count % 10 == 0:
                print(f"[OCR] 本轮未识别到文字（共 {self._capture_count} 次截图）")
            return None

        # 聚类
        groups = self._cluster_texts(texts, img_height=img.shape[0])

        if not groups:
            return None

        # 取最新消息
        latest = groups[-1]
        full_text = ' '.join(t[0] for t in latest).strip()

        if not full_text:
            return None

        # MD5 去重
        text_hash = hashlib.md5(full_text.encode('utf-8')).hexdigest()
        if text_hash == self.last_text_hash:
            return None
        self.last_text_hash = text_hash

        if self.debug:
            print(f"[OCR] ✅ 识别到: {full_text[:80]}{'...' if len(full_text)>80 else ''}")

        return full_text

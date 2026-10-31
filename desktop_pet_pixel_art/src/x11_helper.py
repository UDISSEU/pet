import re
from io import BytesIO

try:
    from Xlib import X, display as xlib_display
    from Xlib.ext import shape as xlib_shape
    XLIB_AVAILABLE = True
except ImportError:
    X = None
    xlib_display = None
    xlib_shape = None
    XLIB_AVAILABLE = False


class X11Helper:
    def __init__(self):
        self.ok = False
        self.last_shape_error = None
        self.dpy = None
        self.root_win = None
        if not XLIB_AVAILABLE:
            return
        try:
            self.dpy = xlib_display.Display()
            self.root_win = self.dpy.screen().root
            self.ok = True
        except Exception:
            self.ok = False

    def get_active_window_info(self):
        if not self.ok:
            return None
        try:
            net_active = self.dpy.intern_atom("_NET_ACTIVE_WINDOW")
            prop = self.root_win.get_full_property(net_active, X.AnyPropertyType)
            if not prop or not prop.value:
                return None
            win_id = prop.value[0]
            win = self.dpy.create_resource_object("window", win_id)
            name = win.get_wm_name() or ""
            klass = win.get_wm_class() or ("", "")
            class_name = klass[0] if isinstance(klass, tuple) and klass else ""
            return (class_name.lower(), name.lower())
        except Exception:
            return None

    def get_open_windows(self, exclude_win_id=None):
        if not self.ok:
            return []
        try:
            net_client_list = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = self.root_win.get_full_property(net_client_list, X.AnyPropertyType)
            if not prop or not prop.value:
                return []

            results = []
            for win_id in prop.value:
                if exclude_win_id is not None and win_id == exclude_win_id:
                    continue
                try:
                    win = self.dpy.create_resource_object("window", win_id)
                    geom = win.get_geometry()
                    x = geom.x
                    y = geom.y
                    w, h = geom.width, geom.height
                    if w < 200 or h < 150:
                        continue
                    results.append({"id": win_id, "x": x, "y": y, "w": w, "h": h})
                except Exception:
                    continue
            return results
        except Exception:
            return []

    def window_exists(self, win_id):
        if not self.ok:
            return False
        try:
            net_list = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = self.root_win.get_full_property(net_list, X.AnyPropertyType)
            return bool(prop and prop.value and win_id in list(prop.value))
        except Exception:
            return False

    def apply_shape_mask(self, tk_window_id, pil_rgba_image):
        if not self.ok:
            return False
        try:
            bit_order = self.dpy.display.info.bitmap_format_bit_order

            alpha = pil_rgba_image.split()[3]
            mask_img = alpha.point(lambda p: 255 if p > 20 else 0).convert("1")

            buffer = BytesIO()
            mask_img.save(buffer, format="XBM")
            xbm_text = buffer.getvalue().decode("ascii", errors="ignore")
            hex_bytes = re.findall(r"0x([0-9a-fA-F]{2})", xbm_text)
            if not hex_bytes:
                return False
            width, height = mask_img.size
            raw = [int(h, 16) for h in hex_bytes]
            if bit_order != X.LSBFirst:
                raw = [int(f"{b:08b}"[::-1], 2) for b in raw]
            # O X11 exige cada linha alinhada a bitmap_format_scanline_pad bits.
            pad_bits = self.dpy.display.info.bitmap_format_scanline_pad
            src_stride = (width + 7) // 8
            dst_stride = ((width + pad_bits - 1) // pad_bits) * (pad_bits // 8)
            rows = []
            for y in range(height):
                row = bytes(raw[y * src_stride:(y + 1) * src_stride])
                rows.append(row + b"\x00" * (dst_stride - src_stride))
            data = b"".join(rows)
            win = self.dpy.create_resource_object("window", tk_window_id)
            pixmap = win.create_pixmap(width, height, 1)
            gc = pixmap.create_gc(foreground=1, background=0)
            pixmap.put_image(gc, 0, 0, width, height, X.XYBitmap, 1, 0, data)

            win.shape_mask(xlib_shape.SO.Set, xlib_shape.SK.Bounding, 0, 0, pixmap)
            win.shape_mask(xlib_shape.SO.Set, xlib_shape.SK.Input, 0, 0, pixmap)
            self.dpy.sync()
            extents = win.shape_query_extents()

            gc.free()
            pixmap.free()
            if not extents.bounding_shaped:
                raise RuntimeError("o servidor X11 não ativou a máscara da janela")
            return True
        except Exception as exc:
            self.last_shape_error = f"{type(exc).__name__}: {exc}"
            return False

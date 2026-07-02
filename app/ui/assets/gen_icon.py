"""生成 Pan-Auto 应用图标（cloud + sync 箭头）。"""
import struct
import io
import math


def _create_icon_rgba(size: int) -> bytes:
    """生成带云+同步箭头的 RGBA 图标数据。"""
    pixels = bytearray(size * size * 4)
    cx, cy = size / 2, size / 2
    r = size / 2

    # 颜色
    blue1 = (47, 107, 255)  # #2f6bff
    blue2 = (29, 78, 216)   # #1d4ed8
    white = (255, 255, 255)

    def set_px(x, y, color, alpha=255):
        if 0 <= x < size and 0 <= y < size:
            idx = (y * size + x) * 4
            pixels[idx] = color[0]
            pixels[idx+1] = color[1]
            pixels[idx+2] = color[2]
            pixels[idx+3] = alpha

    def dist(x1, y1, x2, y2):
        return math.sqrt((x1-x2)**2 + (y1-y2)**2)

    def lerp_color(c1, c2, t):
        return tuple(int(c1[i] + (c2[i]-c1[i])*t) for i in range(3))

    # 圆角矩形背景 + 渐变
    corner_r = size * 0.2
    for y in range(size):
        for x in range(size):
            # 圆角矩形判定
            inside = True
            # 四个角
            corners = [
                (corner_r, corner_r),
                (size - corner_r, corner_r),
                (corner_r, size - corner_r),
                (size - corner_r, size - corner_r),
            ]
            if x < corner_r and y < corner_r:
                inside = dist(x, y, corner_r, corner_r) <= corner_r
            elif x >= size - corner_r and y < corner_r:
                inside = dist(x, y, size - corner_r, corner_r) <= corner_r
            elif x < corner_r and y >= size - corner_r:
                inside = dist(x, y, corner_r, size - corner_r) <= corner_r
            elif x >= size - corner_r and y >= size - corner_r:
                inside = dist(x, y, size - corner_r, size - corner_r) <= corner_r

            if inside:
                t = x / size  # 左到右渐变
                color = lerp_color(blue1, blue2, t)
                set_px(x, y, color)

    # 白色云朵（由多个圆组合）
    scale = size / 64
    cloud_circles = [
        (24*scale, 30*scale, 10*scale),  # 左圆
        (32*scale, 24*scale, 13*scale),  # 中上大圆
        (40*scale, 30*scale, 10*scale),  # 右圆
        (26*scale, 26*scale, 9*scale),   # 左上
        (38*scale, 26*scale, 9*scale),   # 右上
    ]
    # 云底部矩形
    cloud_bottom_y = 32 * scale
    cloud_bottom_h = 8 * scale
    cloud_left = 16 * scale
    cloud_right = 48 * scale

    for y in range(size):
        for x in range(size):
            in_cloud = False
            for ccx, ccy, cr in cloud_circles:
                if dist(x, y, ccx, ccy) <= cr:
                    in_cloud = True
                    break
            if not in_cloud and cloud_left <= x <= cloud_right and cloud_bottom_y <= y <= cloud_bottom_y + cloud_bottom_h:
                in_cloud = True
            if in_cloud:
                set_px(x, y, white)

    # 同步箭头（两个弧形箭头，在云下方）
    arrow_cy = 46 * scale
    arrow_cx = 32 * scale
    arrow_r = 7 * scale
    arrow_thick = 2.2 * scale

    for y in range(size):
        for x in range(size):
            d = dist(x, y, arrow_cx, arrow_cy)
            if abs(d - arrow_r) <= arrow_thick:
                angle = math.atan2(y - arrow_cy, x - arrow_cx)
                # 上半弧（右侧）
                if -math.pi * 0.8 <= angle <= math.pi * 0.1:
                    set_px(x, y, white)
                # 下半弧（左侧）
                elif math.pi * 0.2 <= angle <= math.pi * 0.9:
                    set_px(x, y, white)

    # 箭头尖端
    def draw_triangle(tx, ty, angle, tri_size):
        for dy in range(-int(tri_size*2), int(tri_size*2)+1):
            for dx in range(-int(tri_size*2), int(tri_size*2)+1):
                rx = dx * math.cos(angle) - dy * math.sin(angle)
                ry = dx * math.sin(angle) + dy * math.cos(angle)
                if rx >= 0 and abs(ry) <= rx * 0.7 and rx <= tri_size:
                    set_px(int(tx+dx), int(ty+dy), white)

    # 右箭头（上弧终端）
    ax1 = arrow_cx + arrow_r * math.cos(math.pi * 0.1)
    ay1 = arrow_cy + arrow_r * math.sin(math.pi * 0.1)
    draw_triangle(int(ax1), int(ay1), -math.pi/2, 4*scale)

    # 左箭头（下弧终端）
    ax2 = arrow_cx + arrow_r * math.cos(math.pi * 0.2)
    ay2 = arrow_cy + arrow_r * math.sin(math.pi * 0.2)
    draw_triangle(int(ax2), int(ay2), math.pi/2, 4*scale)

    return bytes(pixels)


def _create_bmp_data(rgba: bytes, size: int) -> bytes:
    """创建 ICO 内嵌的 BMP 数据（BITMAPINFOHEADER + 像素 + 掩码）。"""
    header = struct.pack('<IiiHHIIiiII',
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight (XOR + AND)
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression
        0,           # biSizeImage
        0, 0,        # biXPelsPerMeter, biYPelsPerMeter
        0, 0,        # biClrUsed, biClrImportant
    )

    # BMP 像素是 bottom-up，BGRA 格式
    rows = []
    for y in range(size - 1, -1, -1):
        row = bytearray()
        for x in range(size):
            idx = (y * size + x) * 4
            r, g, b, a = rgba[idx], rgba[idx+1], rgba[idx+2], rgba[idx+3]
            row.extend([b, g, r, a])
        rows.append(bytes(row))

    # AND 掩码（全0 = 全不透明，由 alpha 控制）
    mask_row_size = ((size + 31) // 32) * 4
    mask = b'\x00' * mask_row_size * size

    return header + b''.join(rows) + mask


def create_ico(path: str):
    """生成多尺寸 ICO 文件。"""
    sizes = [16, 32, 48, 64, 128, 256]
    entries = []

    for s in sizes:
        rgba = _create_icon_rgba(s)
        bmp = _create_bmp_data(rgba, s)
        entries.append((s, bmp))

    # ICO 文件头
    header = struct.pack('<HHH', 0, 1, len(entries))
    offset = 6 + 16 * len(entries)

    dir_entries = b''
    data_blocks = b''
    for s, bmp in entries:
        w = 0 if s >= 256 else s
        h = 0 if s >= 256 else s
        dir_entries += struct.pack('<BBBBHHII',
            w, h,
            0,       # color palette
            0,       # reserved
            1,       # color planes
            32,      # bits per pixel
            len(bmp),
            offset,
        )
        data_blocks += bmp
        offset += len(bmp)

    with open(path, 'wb') as f:
        f.write(header + dir_entries + data_blocks)


if __name__ == '__main__':
    create_ico('app/ui/assets/app.ico')
    print('Icon created: app/ui/assets/app.ico')

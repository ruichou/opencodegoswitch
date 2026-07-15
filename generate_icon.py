"""生成 OpenCode Go Switch 图标 (256x256 .ico)"""
from PIL import Image, ImageDraw

size = 256
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 深色圆角背景
margin = 12
draw.rounded_rectangle(
    [margin, margin, size - margin, size - margin],
    radius=50,
    fill="#4f46e5"
)

# 中间白色圆形
cx, cy = size / 2, size / 2
r = 65
draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="white")

# 中间紫色小圆 (齿轮感)
r2 = 20
draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill="#4f46e5")

# 斜线装饰 (闪电/连接符号)
draw.line([cx - 35, cy - 35, cx + 35, cy + 35], fill="#4f46e5", width=8)
draw.line([cx - 35, cy - 35, cx + 20, cy - 35], fill="#4f46e5", width=8)
draw.line([cx + 35, cy + 35, cx - 20, cy + 35], fill="#4f46e5", width=8)

img.save("icon.ico", format="ICO", sizes=[(256, 256)])
print("✅ icon.ico 生成完成")

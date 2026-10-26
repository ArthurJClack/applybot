"""Generates assets/ApplyBot.ico (gradient rounded square with a paper plane). Requires Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "ApplyBot.ico"


def render(size: int = 512) -> Image.Image:
    grad = Image.new("RGBA", (size, size))
    top, bottom = (99, 102, 241), (192, 38, 211)  # indigo -> fuchsia, matches the UI accent
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.23), fill=255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    s = size / 24  # coordinates on a 24x24 grid, like the UI's "send" icon

    def pts(*p):
        return [(x * s, y * s) for x, y in p]

    d.polygon(pts((19.5, 4.5), (4.5, 10.6), (10.6, 13.4)), fill=(255, 255, 255, 255))
    d.polygon(pts((19.5, 4.5), (10.6, 13.4), (13.4, 19.5)), fill=(222, 218, 255, 255))
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    big = render(1024)  # supersampled so edges stay crisp when downscaled
    frames = [big.resize((n, n), Image.LANCZOS) for n in (256, 128, 64, 48, 32, 24, 16)]
    frames[0].save(OUT, append_images=frames[1:], sizes=[f.size for f in frames])
    frames[0].save(OUT.with_suffix(".png"))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

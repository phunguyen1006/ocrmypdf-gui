"""Create the Windows ICO companion for the canonical SVG logo."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def draw_logo(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(round(value * scale) for value in values)  # type: ignore[return-value]

    draw.rounded_rectangle(box((8, 8, 248, 248)), radius=round(48 * scale), fill="#111111")
    draw.polygon(
        [
            (round(64 * scale), round(38 * scale)),
            (round(150 * scale), round(38 * scale)),
            (round(192 * scale), round(80 * scale)),
            (round(192 * scale), round(218 * scale)),
            (round(64 * scale), round(218 * scale)),
        ],
        fill="#ffffff",
    )
    draw.polygon(
        [(round(150 * scale), round(38 * scale)), (round(150 * scale), round(80 * scale)), (round(192 * scale), round(80 * scale))],
        fill="#d8d8d8",
    )
    line_width = max(1, round(10 * scale))
    for y, length in ((112, 66), (136, 50), (160, 38)):
        draw.line(
            (round(86 * scale), round(y * scale), round((86 + length) * scale), round(y * scale)),
            fill="#111111",
            width=line_width,
        )
    draw.ellipse(box((134, 138, 194, 198)), fill="#ffffff", outline="#111111", width=max(1, round(10 * scale)))
    draw.line((round(186 * scale), round(190 * scale), round(214 * scale), round(218 * scale)), fill="#111111", width=max(1, round(12 * scale)))
    return image


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "assets" / "ocrmypdf-gui.ico"
    output.parent.mkdir(parents=True, exist_ok=True)
    draw_logo(256).save(output, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(output)


if __name__ == "__main__":
    main()

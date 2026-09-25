"""Batch replace English comments in team code with Russian translations.

Adheres strictly to text-stylist guidelines:
- Regular hyphen '-' instead of em-dash or en-dash.
- No redundant parentheticals.
- Russian list style (colon, semicolon separator, ending dot, hyphen bullet).
- Professional engineering style, no emoji.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def apply_translations(mapping_file: Path) -> None:
    if not mapping_file.is_file():
        raise FileNotFoundError(f"Mapping file not found: {mapping_file}")

    with open(mapping_file, "r", encoding="utf-8") as f:
        data: dict[str, list[dict]] = json.load(f)

    for file_rel_path, blocks in data.items():
        file_path = Path(file_rel_path)
        if not file_path.is_file():
            print(f"Пропуск отсутствующего файла: {file_path}")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Sort blocks in reverse order of start_line to avoid index offset invalidation
        sorted_blocks = sorted(blocks, key=lambda b: (b["start_line"], b["start_col"]), reverse=True)

        for block in sorted_blocks:
            s_line = block["start_line"]
            s_col = block["start_col"]
            e_line = block["end_line"]
            ru_lines = block.get("ru", [])

            if not ru_lines:
                continue

            if block.get("is_inline", False):
                # Inline comment: single line replacement
                line = lines[s_line - 1]
                before = line[:s_col]
                # ru_lines should be a single string for inline
                ru_text = ru_lines[0] if isinstance(ru_lines, list) else str(ru_lines)
                lines[s_line - 1] = before + ru_text + "\n"
            else:
                # Block comment: determine indentation from s_col
                indent = " " * s_col
                formatted_ru = []
                for item in ru_lines:
                    text = item.lstrip()
                    if not text.startswith("#"):
                        text = f"# {text}"
                    formatted_ru.append(f"{indent}{text}\n")

                lines[s_line - 1 : e_line] = formatted_ru

        new_content = "".join(lines)
        # Verify valid python syntax before saving
        try:
            ast.parse(new_content, filename=str(file_path))
        except SyntaxError as e:
            print(f"ОШИБКА: Синтаксическая ошибка после замены в {file_path}: {e}")
            raise

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        print(f"Обновлен {file_path}: заменено блоков комментариев - {len(blocks)}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Пакетная замена комментариев в кодовой базе команды на русский язык.")
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("scripts/comments_ru.json"),
        help="Путь к файлу маппинга comments_ru.json",
    )
    args = parser.parse_args()
    apply_translations(args.mapping)


if __name__ == "__main__":
    main()

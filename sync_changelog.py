#!/usr/bin/env python3
"""
更新日志同步脚本
从 CHANGELOG.json 读取更新日志，自动同步到 readme.md、wiki/docs/index.md
"""

import json
import re
from pathlib import Path


def load_changelog():
    """加载 CHANGELOG.json"""
    with open("CHANGELOG.json", "r", encoding="utf-8") as f:
        return json.load(f)


def generate_markdown_changelog(changelog):
    """生成 Markdown 格式的更新日志"""
    lines = ["# 更新日志\n"]

    for version in changelog['history']:
        lines.append(f"### {version['version']}（{version['date']}）\n")
        if "note" in version:
            lines.append(f"> **{version['note']}**\n")
        for change in version['changes']:
            lines.append(f"- {change}")
        lines.append("")

    return "\n".join(lines)


def update_readme(changelog_md):
    """更新 readme.md 中的更新日志部分"""
    readme_path = Path("readme.md")
    content = readme_path.read_text(encoding="utf-8")

    # 匹配更新日志部分直到下一个一级标题或文件结尾
    pattern = r"(# 更新日志\n)(.*?)(?=\n# |\Z)"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        # 替换更新日志部分
        before_log = content[:match.start()]
        after_log = content[match.end():]
        new_content = before_log + changelog_md + after_log
    else:
        # 如果没有找到，添加到文件末尾
        new_content = content + "\n\n" + changelog_md

    readme_path.write_text(new_content, encoding="utf-8")
    print("✓ readme.md 已更新")


def update_wiki_docs(changelog_md):
    """更新 wiki/docs/index.md 中的更新日志部分"""
    wiki_path = Path("wiki/docs/index.md")
    content = wiki_path.read_text(encoding="utf-8")

    # 查找更新日志部分直到文件结尾
    pattern = r"(# 更新日志\n)(.*?)(?=\n---|\Z)"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        # 替换更新日志部分
        before_log = content[:match.start()]
        after_log = content[match.end():]
        new_content = before_log + changelog_md + after_log
    else:
        # 如果没有找到，添加到文件末尾
        new_content = content + "\n\n---\n\n" + changelog_md

    wiki_path.write_text(new_content, encoding="utf-8")
    print("✓ wiki/docs/index.md 已更新")


def main():
    """主函数"""
    print("🔄 开始同步更新日志...\n")

    try:
        # 加载 CHANGELOG.json
        changelog = load_changelog()

        # 生成 Markdown 格式的更新日志
        changelog_md = generate_markdown_changelog(changelog)

        # 更新各个文件
        update_readme(changelog_md)
        update_wiki_docs(changelog_md)

        print(f"\n✅ 更新日志同步完成！当前版本: {changelog['history'][0]['version']}")

    except Exception as e:
        print(f"\n❌ 同步失败: {e}")
        exit(1)


if __name__ == "__main__":
    main()
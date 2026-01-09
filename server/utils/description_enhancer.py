"""
简介增强模块

用于检测简介中缺失的关键信息（集数、IMDb链接、豆瓣链接），
并使用PT-Gen API重新获取以补充缺失的信息。
"""

import re
import logging


def check_missing_fields(description: str,
                         imdb_link: str = "",
                         douban_link: str = "") -> dict:
    """
    检查简介中是否缺少关键字段（集数、IMDb链接、豆瓣链接）
    
    Args:
        description: 简介文本
        imdb_link: 当前的IMDb链接
        douban_link: 当前的豆瓣链接
    
    Returns:
        Dict包含:
        - has_episode_count: bool, 是否有集数信息
        - has_imdb_link: bool, 是否有IMDb链接
        - has_douban_link: bool, 是否有豆瓣链接
        - needs_enhancement: bool, 是否需要增强
    """
    result = {
        "has_episode_count": False,
        "has_imdb_link": bool(imdb_link),
        "has_douban_link": bool(douban_link),
        "needs_enhancement": False
    }

    # 检查集数信息
    episode_patterns = [
        r'[◎❁]\s*集\s*数\s+\d+',
        r'[◎❁]\s*集\s*数\s*[:：]\s*\d+',
        r'集\s*数\s*[:：]\s*\d+',
        r'Episodes?\s*[:：]\s*\d+',
        r'Total\s+Episodes?\s*[:：]\s*\d+',
    ]

    for pattern in episode_patterns:
        if re.search(pattern, description, re.IGNORECASE):
            result["has_episode_count"] = True
            break

    # 判断是否需要增强
    result["needs_enhancement"] = (not result["has_episode_count"]
                                   or not result["has_imdb_link"]
                                   or not result["has_douban_link"])

    return result


def enhance_description_if_needed(current_description: str,
                                  imdb_link: str = "",
                                  douban_link: str = "",
                                  subtitle: str = "",
                                  posters: str = "") -> tuple:
    """
    统一检查简介完整性和缺失信息（集数/IMDb/豆瓣链接）
    
    Args:
        current_description: 当前简介文本
        imdb_link: IMDb链接
        douban_link: 豆瓣链接
        subtitle: 副标题（用于搜索）
        posters: 海报链接
    
    Returns:
        (enhanced_description, enhanced_poster, new_imdb_link, changed)
        - enhanced_description: 增强后的简介
        - enhanced_poster: 海报链接
        - new_imdb_link: 新的IMDb链接（如果获取到）
        - changed: 是否发生了变化
    """
    from utils import check_intro_completeness, upload_data_movie_info, extract_origin_from_description

    # 1. 首先检查简介完整性
    completeness_check = check_intro_completeness(current_description)

    # 2. 检查缺失的关键字段（集数、IMDb、豆瓣）
    missing_fields_check = check_missing_fields(current_description, imdb_link,
                                                douban_link)

    # 判断是否需要增强
    needs_enhancement = (not completeness_check["is_complete"]
                         or missing_fields_check["needs_enhancement"])

    if not needs_enhancement:
        logging.info("简介完整且包含所有关键信息，无需增强")
        return current_description, "", imdb_link, False

    # 记录所有缺失的字段
    all_missing_fields = []

    if not completeness_check["is_complete"]:
        all_missing_fields.extend(completeness_check['missing_fields'])

    if not missing_fields_check["has_episode_count"]:
        all_missing_fields.append("集数")
    if not missing_fields_check["has_imdb_link"]:
        all_missing_fields.append("IMDb链接")
    if not missing_fields_check["has_douban_link"]:
        all_missing_fields.append("豆瓣链接")

    logging.info(f"检测到简介缺少: {', '.join(all_missing_fields)}")
    print(f"[*] 检测到简介缺少: {', '.join(all_missing_fields)}")

    # 如果没有任何链接，无法获取
    if not imdb_link and not douban_link:
        logging.warning("没有IMDb或豆瓣链接，无法增强简介")
        return current_description, "", imdb_link, False

    # 尝试从PT-Gen获取新简介
    try:
        logging.info("尝试从豆瓣/IMDb重新获取完整简介...")
        print("[*] 尝试从豆瓣/IMDb重新获取完整简介...")

        # 检查海报是否来自豆瓣
        media_type = "intro"
        douban_match = re.search(r'https?://img(\d+)\.doubanio\.com.*?/(p\d+)', posters)
        if not douban_match:
            media_type = ""
            
        status, posters, new_description, new_imdb, new_douban, _ = upload_data_movie_info(
            media_type, douban_link, imdb_link, subtitle=subtitle
        )

        if not status or not new_description:
            logging.warning(f"获取简介失败: {posters}")
            return current_description, "", imdb_link, False

        # 检查新简介的完整性和关键信息
        new_completeness = check_intro_completeness(new_description)
        new_missing_fields = check_missing_fields(new_description, new_imdb
                                                  or imdb_link, new_douban
                                                  or douban_link)

        # 判断新简介是否有改进
        has_improvement = False
        improvements = []

        # 检查完整性改进
        if not completeness_check["is_complete"] and new_completeness[
                "is_complete"]:
            has_improvement = True
            improvements.extend(completeness_check['missing_fields'])

        # 检查关键字段改进
        if not missing_fields_check["has_episode_count"] and new_missing_fields[
                "has_episode_count"]:
            has_improvement = True
            improvements.append("集数")

        if not missing_fields_check["has_imdb_link"] and new_imdb:
            has_improvement = True
            improvements.append("IMDb链接")

        if not has_improvement:
            logging.info("新获取的简介没有改进，保留原简介")
            return current_description, posters, imdb_link, False

        logging.info(f"✅ 新简介补充了缺失的信息: {', '.join(set(improvements))}")
        print(f"[✓] 新简介补充了: {', '.join(set(improvements))}")

        # 返回新简介和海报
        return new_description, posters, new_imdb or imdb_link, True

    except Exception as e:
        logging.error(f"增强简介时出错: {e}", exc_info=True)
        return current_description, "", imdb_link, False

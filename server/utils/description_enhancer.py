"""
简介增强模块

用于检测简介中缺失的关键信息（集数、IMDb链接、豆瓣链接），
并使用PT-Gen API重新获取以补充缺失的信息。
"""

import re
import logging


def check_missing_fields(description: str, imdb_link: str = "", douban_link: str = "") -> dict:
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
        r'◎\s*集\s*数\s+\d+',
        r'◎\s*集\s*数\s*[:：]\s*\d+',
        r'集\s*数\s*[:：]\s*\d+',
        r'Episodes?\s*[:：]\s*\d+',
        r'Total\s+Episodes?\s*[:：]\s*\d+',
    ]
    
    for pattern in episode_patterns:
        if re.search(pattern, description, re.IGNORECASE):
            result["has_episode_count"] = True
            break
    
    # 判断是否需要增强
    result["needs_enhancement"] = (
        not result["has_episode_count"] or
        not result["has_imdb_link"] or
        not result["has_douban_link"]
    )
    
    return result


def enhance_description_if_needed(
    current_description: str,
    imdb_link: str = "",
    douban_link: str = ""
) -> tuple:
    """
    如果简介缺少关键信息，尝试使用PT-Gen重新获取并智能合并
    
    Args:
        current_description: 当前简介文本
        imdb_link: IMDb链接
        douban_link: 豆瓣链接
    
    Returns:
        (enhanced_description, new_imdb_link, changed)
        - enhanced_description: 增强后的简介
        - new_imdb_link: 新的IMDb链接（如果获取到）
        - changed: 是否发生了变化
    """
    # 检查缺失字段
    check_result = check_missing_fields(current_description, imdb_link, douban_link)
    
    if not check_result["needs_enhancement"]:
        logging.info("简介包含所有关键信息，无需增强")
        return current_description, imdb_link, False
    
    # 记录缺失的字段
    missing_fields = []
    if not check_result["has_episode_count"]:
        missing_fields.append("集数")
    if not check_result["has_imdb_link"]:
        missing_fields.append("IMDb链接")
    if not check_result["has_douban_link"]:
        missing_fields.append("豆瓣链接")
    
    logging.info(f"检测到简介缺少关键信息: {', '.join(missing_fields)}")
    print(f"[*] 检测到简介缺少: {', '.join(missing_fields)}")
    
    # 如果没有任何链接，无法获取
    if not imdb_link and not douban_link:
        logging.warning("没有IMDb或豆瓣链接，无法增强简介")
        return current_description, imdb_link, False
    
    # 尝试从PT-Gen获取新简介
    try:
        from utils.media_helper import upload_data_movie_info
        
        logging.info("尝试从PT-Gen获取完整简介...")
        print("[*] 尝试从PT-Gen获取完整简介...")
        
        status, poster, new_description, new_imdb = upload_data_movie_info(
            douban_link, imdb_link
        )
        
        if not status or not new_description:
            logging.warning(f"获取简介失败: {poster}")
            return current_description, imdb_link, False
        
        # 检查新简介是否包含缺失的信息
        new_check = check_missing_fields(new_description, new_imdb or imdb_link, douban_link)
        
        # 判断新简介是否有改进
        has_improvement = False
        improvements = []
        
        if not check_result["has_episode_count"] and new_check["has_episode_count"]:
            has_improvement = True
            improvements.append("集数")
        
        if not check_result["has_imdb_link"] and new_imdb:
            has_improvement = True
            improvements.append("IMDb链接")
        
        if not has_improvement:
            logging.info("新获取的简介没有包含缺失的信息，保留原简介")
            return current_description, imdb_link, False
        
        logging.info(f"✅ 新简介补充了缺失的信息: {', '.join(improvements)}")
        print(f"[✓] 新简介补充了: {', '.join(improvements)}")
        
        # 返回新简介
        return new_description, new_imdb or imdb_link, True
        
    except Exception as e:
        logging.error(f"增强简介时出错: {e}", exc_info=True)
        return current_description, imdb_link, False

# sites/lucky.py

from loguru import logger
import time
import os
import traceback
import cloudscraper
from http.cookies import SimpleCookie


# [关键新增] 将 cookies_raw2jar 函数直接集成到此文件中
def cookies_raw2jar(raw: str) -> dict:
    """
    使用 SimpleCookies 将原始 Cookie 字符串解析为字典。
    """
    if not raw:
        raise ValueError("Cookie 字符串不能为空。")
    cookie = SimpleCookie(raw)
    return {key: morsel.value for key, morsel in cookie.items()}


def upload(
    site_info,
    source_params,
    modified_torrent_path,
    main_title,
    subtitle,
    imdb_link,
    intro,
    mediainfo,
):
    """
    lucky站点的专用上传函数。
    返回一个元组 (bool, str)，表示成功与否和相关消息。
    """
    post_url = f"{site_info['base_url']}/takeupload.php"
    time_out = 40
    tags = []

    logger.info("正在为 lucky 站点适配上传参数...")

    try:
        # (此处省略了和之前版本完全相同的参数选择逻辑，保持不变)
        if "电影" in source_params.get("类型"):
            select_type = "401"
        else:
            select_type = "405"

        if (
            "web" in source_params.get("媒介").lower()
            and "dl" in source_params.get("媒介").lower()
        ):
            medium_sel = "11"
        elif "blu" in source_params.get("媒介").lower():
            medium_sel = "1"
        else:
            medium_sel = "7"

        if "264" in source_params.get("编码").lower():
            codec_sel = "1"
        elif "265" in source_params.get("编码").lower():
            codec_sel = "6"
        else:
            codec_sel = "1"

        if "AAC" in source_params.get("音频编码").upper():
            audiocodec_sel = "6"
        elif "DDP" in source_params.get("音频编码").upper():
            audiocodec_sel = "12"
        else:
            audiocodec_sel = "7"

        if "8K" in source_params.get("分辨率"):
            standard_sel = "7"
        elif "2160" in source_params.get("分辨率"):
            standard_sel = "6"
        elif "1080" in source_params.get("分辨率"):
            standard_sel = "1"
        elif "720" in source_params.get("分辨率"):
            standard_sel = "3"
        elif "480" in source_params.get("分辨率"):
            standard_sel = "4"
        else:
            standard_sel = "8"

        team_sel = "5"

        if "国语" in source_params.get("标签"):
            tags.append(5)
        if "中字" in source_params.get("类型"):
            tags.append(6)

        tags = list(set(tags))
        tags.sort()

        logger.info("参数适配完成。")

        with open(modified_torrent_path, "rb") as torrent_file:
            files = {
                "file": (
                    os.path.basename(modified_torrent_path),
                    torrent_file,
                    "application/x-bittorrent",
                ),
                "nfo": ("", b"", "application/octet-stream"),
            }

            description = (
                f"{intro.get('声明', '')}\n"
                f"{intro.get('海报', '')}\n"
                f"{intro.get('正文', '')}\n"
                f"{intro.get('截图', '')}"
            )

            data = {
                "name": main_title,
                "small_descr": subtitle,
                "url": imdb_link or "",
                "color": "0",
                "font": "0",
                "size": "0",
                "descr": description,
                "technical_info": mediainfo,
                "type": select_type,
                "medium_sel[4]": medium_sel,
                "codec_sel[4]": codec_sel,
                "audiocodec_sel[4]": audiocodec_sel,
                "standard_sel[4]": standard_sel,
                "team_sel[4]": team_sel,
                "uplver": "yes",
            }
            for i, tag_id in enumerate(tags):
                data[f"tags[4][{i}]"] = tag_id

            cleaned_cookie_str = site_info.get("cookie", "").strip()
            if not cleaned_cookie_str:
                logger.error("目标站点 Cookie 为空，无法发布。")
                return False, "目标站点 Cookie 未配置。"

            # [关键修复] 将 cookie 字符串转换为字典
            cookie_jar = cookies_raw2jar(cleaned_cookie_str)

            scraper = cloudscraper.create_scraper()
            headers = {
                # 不再在这里传递 cookie
                "origin": site_info.get("base_url"),
                "referer": f"{site_info.get('base_url')}/upload.php",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            }

            logger.info("正在向 lucky 站点提交发布请求...")
            # [关键修复] 使用 cookies 参数传递 cookie 字典
            response = scraper.post(
                post_url,
                headers=headers,
                cookies=cookie_jar,
                data=data,
                files=files,
                timeout=time_out,
            )
            response.raise_for_status()

            if "details.php" in response.url and "uploaded=1" in response.url:
                logger.success("发布成功！已跳转到种子详情页。")
                return True, f"发布成功！新种子页面: {response.url}"
            elif "login.php" in response.url:
                logger.error("发布失败，Cookie 已失效，被重定向到登录页。")
                return False, "发布失败，Cookie 已失效或无效。"
            else:
                logger.error(f"发布失败，站点返回未知响应。")
                logger.debug(f"响应URL: {response.url}")
                logger.debug(f"响应内容前500字符: {response.text[:500]}")
                return False, f"发布失败，请检查站点返回信息。 URL: {response.url}"

    except Exception as e:
        logger.error(f"发布到 lucky 站点时发生错误: {e}")
        logger.error(traceback.format_exc())
        return False, f"请求异常: {e}"

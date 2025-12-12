# utils/torrent_manager.py

import logging
import os
import tempfile
import json
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

# 导入下载器客户端
from qbittorrentapi import Client as QbClient, exceptions as QbExceptions
from transmission_rpc import Client as TrClient, TransmissionError

# 延迟导入以避免循环依赖
# from core.services import _prepare_api_config


class TorrentManager:
    """种子管理器，负责跨下载器的种子操作"""

    def __init__(self, db_manager, config_manager):
        self.db_manager = db_manager
        self.config_manager = config_manager

    def get_downloader_client(self, downloader_id: str):
        """获取指定下载器的客户端实例"""
        config = self.config_manager.get()
        downloaders = config.get("downloaders", [])

        # 找到匹配的下载器配置
        downloader_config = None
        for d in downloaders:
            if d.get("id") == downloader_id and d.get("enabled", True):
                downloader_config = d
                break

        if not downloader_config:
            raise ValueError(f"未找到启用状态的下载数器配置: {downloader_id}")

        # 准备API配置（延迟导入以避免循环依赖）
        from core.services import _prepare_api_config
        api_config = _prepare_api_config(downloader_config)

        # 创建客户端实例
        try:
            if downloader_config["type"] == "qbittorrent":
                client = QbClient(**api_config)
                # 测试连接
                client.auth.log_in()
                return client

            elif downloader_config["type"] == "transmission":
                client = TrClient(**api_config)
                # 测试连接
                client.get_session()
                return client

            else:
                raise ValueError(f"不支持的下载器类型: {downloader_config['type']}")

        except Exception as e:
            logging.error(f"无法连接到下载器 {downloader_id}: {e}")
            raise

    def find_torrents_by_site(self, downloader_id: str, site_name: str, torrent_name: str, torrent_size: int, save_path: str = None) -> List[Dict[str, Any]]:
        """
        先从数据库中查找匹配的种子记录，然后获取hash去下载器进行操作

        Args:
            downloader_id: 下载器ID
            site_name: 站点名称
            torrent_name: 种子名称
            torrent_size: 种子大小
            save_path: 保存路径（可选，用于更精确匹配）

        Returns:
            匹配的种子列表
        """
        try:
            # 第一步：从数据库查找匹配的种子记录
            torrent_hashes = self._find_torrents_from_database(site_name, torrent_name, torrent_size, save_path, downloader_id)

            if not torrent_hashes:
                logging.info(f"数据库中未找到匹配的种子记录: {torrent_name}")
                return []

            logging.info(f"在数据库中找到 {len(torrent_hashes)} 个匹配的种子记录")

            # 第二步：获取下载器客户端并验证种子存在
            client = self.get_downloader_client(downloader_id)

            if isinstance(client, QbClient):
                return self._verify_qbittorrent_torrents(client, torrent_hashes, torrent_name, torrent_size)
            elif isinstance(client, TrClient):
                return self._verify_transmission_torrents(client, torrent_hashes, torrent_name, torrent_size)
            else:
                raise ValueError(f"不支持的客户端类型: {type(client)}")

        except Exception as e:
            logging.error(f"查找种子失败: {e}")
            raise

    def _find_torrents_from_database(self, site_name: str, torrent_name: str, torrent_size: int, save_path: str = None, downloader_id: str = None) -> List[str]:
        """从数据库中查找匹配的种子记录，返回hash列表（使用更灵活的匹配策略）"""
        conn = None
        cursor = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 首先尝试精确匹配
            exact_matches = self._find_exact_matches(cursor, torrent_name, torrent_size, site_name, save_path, downloader_id)
            if exact_matches:
                logging.info(f"精确匹配找到 {len(exact_matches)} 个记录")
                return exact_matches

            # 如果精确匹配失败，尝试模糊匹配
            logging.info("精确匹配失败，尝试模糊匹配...")
            fuzzy_matches = self._find_fuzzy_matches(cursor, torrent_name, torrent_size, site_name, save_path, downloader_id)
            if fuzzy_matches:
                logging.info(f"模糊匹配找到 {len(fuzzy_matches)} 个记录")
                return fuzzy_matches

            logging.info("未找到匹配的种子记录")
            return []

        except Exception as e:
            logging.error(f"从数据库查找种子失败: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _find_exact_matches(self, cursor, torrent_name: str, torrent_size: int, site_name: str, save_path: str = None, downloader_id: str = None) -> List[str]:
        """精确匹配种子记录"""
        conditions = ["name = %s", "size = %s", "sites = %s", "state != '不存在'"]
        params = [torrent_name, torrent_size, site_name]

        if save_path:
            conditions.append("save_path = %s")
            params.append(save_path)

        if downloader_id:
            conditions.append("downloader_id = %s")
            params.append(downloader_id)

        return self._execute_query(cursor, conditions, params, "精确匹配")

    def _find_fuzzy_matches(self, cursor, torrent_name: str, torrent_size: int, site_name: str, save_path: str = None, downloader_id: str = None) -> List[str]:
        """模糊匹配种子记录"""
        # 策略1: 匹配名称、站点和相近大小（1GB误差范围）
        conditions1 = ["name = %s", "sites = %s", "ABS(size - %s) < %s", "state != '不存在'"]
        params1 = [torrent_name, site_name, torrent_size, 1024 * 1024 * 1024]  # 1GB误差范围

        if downloader_id:
            conditions1.append("downloader_id = %s")
            params1.append(downloader_id)

        matches1 = self._execute_query(cursor, conditions1, params1, "模糊匹配-名称站点大小")
        if matches1:
            return matches1

        # 策略2: 匹配完整名称和站点（不限制大小）
        conditions2 = ["name LIKE %s", "sites = %s", "state != '不存在'"]
        params2 = [f"%{torrent_name}%", site_name]

        if downloader_id:
            conditions2.append("downloader_id = %s")
            params2.append(downloader_id)

        matches2 = self._execute_query(cursor, conditions2, params2, "模糊匹配-完整名称站点")
        if matches2:
            return matches2

        return []

    def _extract_keywords(self, torrent_name: str) -> str:
        """从种子名称中提取关键词"""
        # 移除常见的无关词汇，保留主要识别信息
        import re

        # 移除年份、分辨率、编码格式等
        cleaned = re.sub(r'\d{4}', '', torrent_name)  # 移除年份
        cleaned = re.sub(r'1080[pP]|720[pP]|4[Kk]', '', cleaned)  # 移除分辨率
        cleaned = re.sub(r'x264|x265|HEVC|AVC', '', cleaned)  # 移除编码
        cleaned = re.sub(r'BluRay|BDMV|WEB-DL', '', cleaned)  # 移除来源

        # 提取主要词汇（长度>3的单词）
        words = [word for word in re.split(r'[.\s\-\_]+', cleaned) if len(word) > 3]

        return ' '.join(words[:3])  # 返回前3个关键词

    def _execute_query(self, cursor, conditions: List[str], params: List, match_type: str) -> List[str]:
        """执行数据库查询"""
        try:
            query = f"SELECT hash, name, size, save_path, state, sites FROM torrents WHERE {' AND '.join(conditions)}"
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"

            # 替换占位符
            formatted_query = query.replace("%s", placeholder)
            cursor.execute(formatted_query, tuple(params))

            rows = cursor.fetchall()
            torrent_hashes = []

            for row in rows:
                torrent_hashes.append(row['hash'])
                logging.debug(f"{match_type}找到: hash={row['hash']}, name={row['name']}, size={row['size']}, site={row['sites']}")

            return torrent_hashes

        except Exception as e:
            logging.error(f"{match_type}查询失败: {e}")
            return []

    def find_similar_torrents(self, torrent_name: str, torrent_size: int) -> List[Dict[str, Any]]:
        """
        仅基于种子名称和大小查找相似的种子（不限制站点）
        帮助用户找到可能的匹配项

        Args:
            torrent_name: 种子名称
            torrent_size: 种子大小

        Returns:
            相似的种子列表
        """
        conn = None
        cursor = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 使用完整名称进行模糊匹配
            conditions = [
                "name LIKE %s",
                "state != '不存在'"
            ]
            params = [f"%{torrent_name}%"]

            query = f"SELECT hash, name, size, save_path, state, sites, downloader_id FROM torrents WHERE {' AND '.join(conditions)} ORDER BY ABS(size - %s) ASC LIMIT 10"
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"

            # 添加size参数到params末尾用于ORDER BY
            all_params = params + [torrent_size]
            formatted_query = query.replace("%s", placeholder)
            cursor.execute(formatted_query, tuple(all_params))

            rows = cursor.fetchall()
            similar_torrents = []

            for row in rows:
                similar_torrents.append({
                    'hash': row['hash'],
                    'name': row['name'],
                    'size': row['size'],
                    'save_path': row['save_path'],
                    'state': row['state'],
                    'sites': row['sites'],
                    'downloader_id': row['downloader_id'],
                    'size_diff': abs(row['size'] - torrent_size)
                })

            logging.info(f"找到 {len(similar_torrents)} 个相似的种子")
            return similar_torrents

        except Exception as e:
            logging.error(f"查找相似种子失败: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _verify_qbittorrent_torrents(self, client: QbClient, torrent_hashes: List[str], torrent_name: str, torrent_size: int) -> List[Dict[str, Any]]:
        """验证qBittorrent中是否存在指定的种子"""
        try:
            # 获取所有种子
            all_torrents = client.torrents.info()

            # 创建hash到种子信息的映射
            torrent_map = {t.hash: t for t in all_torrents}

            matched_torrents = []
            for torrent_hash in torrent_hashes:
                if torrent_hash in torrent_map:
                    torrent = torrent_map[torrent_hash]

                    # 验证名称和大小（双重确认）
                    name_match = torrent.name == torrent_name
                    size_match = abs(torrent.size - torrent_size) < 1024 * 1024  # 1MB误差范围

                    if name_match and size_match:
                        matched_torrents.append({
                            'hash': torrent.hash,
                            'name': torrent.name,
                            'size': torrent.size,
                            'state': torrent.state
                        })
                        logging.info(f"验证通过: {torrent.name} ({torrent.hash})")
                    else:
                        logging.warning(f"种子信息不匹配: hash={torrent_hash}, 期望名称={torrent_name}, 实际名称={torrent.name}, 期望大小={torrent_size}, 实际大小={torrent.size}")
                else:
                    logging.warning(f"下载器中未找到种子: {torrent_hash}")

            return matched_torrents

        except Exception as e:
            logging.error(f"验证qBittorrent种子失败: {e}")
            raise

    def _verify_transmission_torrents(self, client: TrClient, torrent_hashes: List[str], torrent_name: str, torrent_size: int) -> List[Dict[str, Any]]:
        """验证Transmission中是否存在指定的种子"""
        try:
            # 获取所有种子
            all_torrents = client.get_torrents()

            # 创建hash到种子信息的映射
            torrent_map = {t.hashString: t for t in all_torrents}

            matched_torrents = []
            for torrent_hash in torrent_hashes:
                if torrent_hash in torrent_map:
                    torrent = torrent_map[torrent_hash]

                    # 验证名称和大小（双重确认）
                    name_match = torrent.name == torrent_name
                    size_match = abs(torrent.total_size - torrent_size) < 1024 * 1024  # 1MB误差范围

                    if name_match and size_match:
                        matched_torrents.append({
                            'hash': torrent.hashString,
                            'name': torrent.name,
                            'size': torrent.total_size,
                            'state': torrent.status
                        })
                        logging.info(f"验证通过: {torrent.name} ({torrent.hashString})")
                    else:
                        logging.warning(f"种子信息不匹配: hash={torrent_hash}, 期望名称={torrent_name}, 实际名称={torrent.name}, 期望大小={torrent_size}, 实际大小={torrent.total_size}")
                else:
                    logging.warning(f"下载器中未找到种子: {torrent_hash}")

            return matched_torrents

        except Exception as e:
            logging.error(f"验证Transmission种子失败: {e}")
            raise

    
    def pause_torrents(self, downloader_id: str, torrent_hashes: List[str]) -> bool:
        """
        暂停指定的种子

        Args:
            downloader_id: 下载器ID
            torrent_hashes: 种子hash列表

        Returns:
            是否成功暂停
        """
        try:
            client = self.get_downloader_client(downloader_id)

            if isinstance(client, QbClient):
                # qBittorrent暂停种子
                client.torrents.pause(torrent_hashes)
                logging.info(f"在qBittorrent中暂停了 {len(torrent_hashes)} 个种子")
                return True

            elif isinstance(client, TrClient):
                # Transmission暂停种子
                client.stop_torrent(torrent_hashes)
                logging.info(f"在Transmission中暂停了 {len(torrent_hashes)} 个种子")
                return True

            else:
                raise ValueError(f"不支持的客户端类型: {type(client)}")

        except Exception as e:
            logging.error(f"暂停种子失败: {e}")
            return False

    def export_torrent_files(self, downloader_id: str, torrent_hashes: List[str], export_dir: str) -> List[str]:
        """
        导出种子文件

        Args:
            downloader_id: 下载器ID
            torrent_hashes: 种子hash列表
            export_dir: 导出目录

        Returns:
            导出的文件路径列表
        """
        try:
            # 获取配置，以便生成路径映射
            config = self.config_manager.get()
            downloaders = config.get("downloaders", [])
            downloader_config = next((d for d in downloaders if d.get("id") == downloader_id), None)

            # 为 Transmission 下载器自动生成路径映射
            path_mapping = self._generate_transmission_path_mapping(downloader_config, downloaders)

            client = self.get_downloader_client(downloader_id)
            exported_files = []

            # 确保导出目录存在
            os.makedirs(export_dir, exist_ok=True)

            if isinstance(client, QbClient):
                # qBittorrent导出种子文件
                for torrent_hash in torrent_hashes:
                    try:
                        # 获取种子文件内容
                        torrent_data = client.torrents.export(torrent_hash)

                        # 保存到文件
                        filename = f"{torrent_hash}.torrent"
                        filepath = os.path.join(export_dir, filename)

                        with open(filepath, 'wb') as f:
                            f.write(torrent_data)

                        exported_files.append(filepath)
                        logging.info(f"导出种子文件: {filepath}")

                    except Exception as e:
                        logging.error(f"导出种子 {torrent_hash} 失败: {e}")
                        continue

            elif isinstance(client, TrClient):
                # Transmission直接读取本地种子文件
                for torrent_hash in torrent_hashes:
                    try:
                        # 获取种子信息，包括种子文件路径
                        torrent_info = client.get_torrent(torrent_hash)

                        if hasattr(torrent_info, 'torrent_file') and torrent_info.torrent_file:
                            # 使用路径映射读取种子文件
                            torrent_data = self._read_transmission_torrent_file(
                                torrent_info.torrent_file,
                                path_mapping
                            )

                            if torrent_data:
                                # 保存到导出目录
                                filename = f"{torrent_hash}.torrent"
                                filepath = os.path.join(export_dir, filename)

                                with open(filepath, 'wb') as f:
                                    f.write(torrent_data)

                                exported_files.append(filepath)
                                logging.info(f"导出Transmission种子文件: {filepath}")
                            else:
                                logging.error(f"无法读取Transmission种子文件: {torrent_hash}")
                        else:
                            logging.error(f"无法获取种子 {torrent_hash} 的文件路径")

                    except Exception as e:
                        logging.error(f"导出Transmission种子 {torrent_hash} 失败: {e}")
                        continue
            else:
                raise ValueError(f"不支持的客户端类型: {type(client)}")

            logging.info(f"成功导出 {len(exported_files)} 个种子文件")
            return exported_files

        except Exception as e:
            logging.error(f"导出种子文件失败: {e}")
            raise

    def _generate_transmission_path_mapping(self, downloader_config: Dict[str, Any], all_downloaders: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        """
        为 Transmission 下载器自动生成路径映射

        Args:
            downloader_config: 当前下载器配置
            all_downloaders: 所有下载器配置列表

        Returns:
            路径映射字典，格式: {'remote_prefix': '/path/in/container', 'local_prefix': '/data/tr_torrents/tr1'}
        """
        if not downloader_config or downloader_config.get("type") != "transmission":
            return None

        # 计算当前是第几个 transmission 下载器
        transmission_count = 0
        current_tr_index = 0

        for i, downloader in enumerate(all_downloaders):
            if downloader.get("type") == "transmission":
                transmission_count += 1
                if downloader.get("id") == downloader_config.get("id"):
                    current_tr_index = transmission_count
                    break

        if current_tr_index == 0:
            logging.warning(f"未找到当前下载器 {downloader_config.get('id')} 在配置中的位置")
            return None

        # 生成映射路径
        local_prefix = f"/data/tr_torrents/tr{current_tr_index}"

        # 常见的 Transmission 种子文件路径（容器内）
        possible_remote_prefixes = [
            "/config/transmission-daemon/torrents",  # Docker 镜像常用
            "/config/torrents",                    # Docker 镜像简化版
            "/var/lib/transmission-daemon/.config/transmission-daemon/torrents",  # Debian/Ubuntu
            "/var/lib/transmission/.config/transmission-daemon/torrents",          # 其他系统
            "~/.config/transmission-daemon/torrents",                             # 用户目录
        ]

        path_mapping = {
            "remote_prefix": possible_remote_prefixes[0],  # 默认使用第一个
            "local_prefix": local_prefix
        }

        logging.info(f"为 Transmission 下载器 {downloader_config.get('id')} 生成路径映射: {path_mapping}")
        return path_mapping

    def _read_transmission_torrent_file(self, remote_file_path: str, path_mapping: Dict[str, str] = None) -> Optional[bytes]:
        """
        读取 Transmission 种子文件，支持 Docker 路径映射

        Args:
            remote_file_path: Transmission API 返回的绝对路径 (如 /config/torrents/hash.torrent)
            path_mapping: 配置中的映射字典 {'remote_prefix': '/config/torrents', 'local_prefix': '/data/tr_torrents/tr1'}

        Returns:
            种子文件内容，失败返回None
        """
        local_file_path = remote_file_path  # 默认情况

        # 1. 如果有配置映射，优先使用映射转换路径
        if path_mapping:
            remote_prefix = path_mapping.get('remote_prefix')
            local_prefix = path_mapping.get('local_prefix')

            if remote_prefix and local_prefix and remote_file_path.startswith(remote_prefix):
                # 执行路径替换
                # 例如: /config/torrents/123.torrent -> /data/tr_torrents/tr1/123.torrent
                local_file_path = remote_file_path.replace(remote_prefix, local_prefix, 1)
                # 规范化路径 (处理 Windows/Linux 斜杠差异)
                local_file_path = os.path.normpath(local_file_path)
                logging.info(f"路径映射转换: {remote_file_path} -> {local_file_path}")

        # 2. 尝试直接读取 (处理映射转换后的路径，或者未映射时的原始路径)
        try:
            logging.info(f"尝试读取本地种子文件: {local_file_path}")

            if not os.path.exists(local_file_path):
                # 如果映射后还是找不到，尝试使用旧的自动搜索逻辑作为 fallback
                logging.warning(f"本地路径不存在: {local_file_path}，尝试回退搜索策略...")
                return self._fallback_search_torrent_file(remote_file_path)

            if not os.access(local_file_path, os.R_OK):
                logging.error(f"文件存在但无读取权限: {local_file_path}")
                return None

            with open(local_file_path, 'rb') as f:
                content = f.read()

            if not content:
                logging.warning(f"种子文件为空: {local_file_path}")
                return None

            # 验证种子文件格式
            if content.startswith(b'd8:') or content.startswith(b'<?xml'):
                logging.info(f"成功读取种子文件: {local_file_path}, 大小: {len(content)} 字节")
                return content
            else:
                logging.warning(f"文件不是有效的种子文件格式: {local_file_path}")
                return None

        except Exception as e:
            logging.error(f"读取文件发生异常: {e}")
            return None

    def _fallback_search_torrent_file(self, original_path: str) -> Optional[bytes]:
        """
        保留原有的自动搜索逻辑作为备选方案

        Args:
            original_path: 原始的种子文件路径

        Returns:
            种子文件内容，失败返回None
        """
        try:
            filename = os.path.basename(original_path)
            logging.info(f"回退搜索策略: 查找种子文件 {filename}")

            # 常见的种子文件目录列表
            search_paths = [
                # Docker镜像常用路径
                '/data/tr_torrents/tr1',
                '/data/tr_torrents/tr2',
                '/data/tr_torrents/tr3',
                '/data/tr_torrents/tr4',
                '/data/tr_torrents/tr5',
                '/config/transmission-daemon/torrents',
                '/config/torrents',
                # 系统包安装的路径
                '/var/lib/transmission-daemon/.config/transmission-daemon/torrents',
                '/var/lib/transmission/.config/transmission-daemon/torrents',
                # 用户目录
                '/home/transmission/.config/transmission-daemon/torrents',
                os.path.expanduser('~/.config/transmission-daemon/torrents'),
            ]

            # 在这些目录中查找文件
            for base_path in search_paths:
                potential_path = os.path.join(base_path, filename)
                if os.path.exists(potential_path) and os.access(potential_path, os.R_OK):
                    logging.info(f"回退搜索找到种子文件: {potential_path}")

                    with open(potential_path, 'rb') as f:
                        content = f.read()

                    if content.startswith(b'd8:') or content.startswith(b'<?xml'):
                        logging.info(f"回退搜索成功读取种子文件: {potential_path}, 大小: {len(content)} 字节")
                        return content

            logging.warning(f"回退搜索策略失败，未找到种子文件: {filename}")
            return None

        except Exception as e:
            logging.error(f"回退搜索策略发生异常: {e}")
            return None


    def _get_site_info(self, site_name: str) -> Optional[Dict[str, Any]]:
        """从数据库获取站点信息，包括速度限制设置"""
        if not site_name:
            return None

        conn = None
        cursor = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 查询站点信息
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"
            cursor.execute(f"SELECT nickname, base_url, cookie, speed_limit FROM sites WHERE nickname = {placeholder}", (site_name,))

            row = cursor.fetchone()
            if row:
                return dict(row)
            else:
                logging.warning(f"未找到站点 '{site_name}' 的配置信息")
                return None

        except Exception as e:
            logging.error(f"获取站点信息失败: {e}")
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def add_torrents_to_downloader(self, target_downloader_id: str, torrent_files: List[str],
                                   save_path: Optional[str] = None, paused: bool = False, site_name: str = None) -> Dict[str, Any]:
        """
        将种子文件添加到目标下载器

        Args:
            target_downloader_id: 目标下载器ID
            torrent_files: 种子文件路径列表
            save_path: 保存路径（可选）
            paused: 是否添加为暂停状态
            site_name: 站点名称（用于获取速度限制设置）

        Returns:
            添加结果统计
        """
        try:
            client = self.get_downloader_client(target_downloader_id)

            # 获取站点速度限制信息
            site_info = self._get_site_info(site_name) if site_name else None

            success_count = 0
            failed_count = 0
            failed_items = []

            if isinstance(client, QbClient):
                # qBittorrent添加种子
                for torrent_file in torrent_files:
                    try:
                        # 准备添加选项
                        add_options = {
                            'paused': paused
                        }
                        if save_path:
                            add_options['savepath'] = save_path

                        # 如果站点设置了速度限制，添加速度限制参数
                        if site_info and site_info.get('speed_limit', 0) > 0:
                            speed_limit = int(site_info['speed_limit']) * 1024 * 1024  # 转换为 bytes/s
                            add_options['upload_limit'] = speed_limit
                            logging.info(f"为站点 '{site_name}' 设置上传速度限制: {site_info['speed_limit']} MB/s")

                        # 添加种子
                        result = client.torrents.add(torrent_files=torrent_file, **add_options)
                        success_count += 1
                        logging.info(f"成功添加种子到qBittorrent: {torrent_file}")

                    except Exception as e:
                        failed_count += 1
                        failed_items.append({'file': torrent_file, 'error': str(e)})
                        logging.error(f"添加种子到qBittorrent失败 {torrent_file}: {e}")

            elif isinstance(client, TrClient):
                # Transmission添加种子
                for torrent_file in torrent_files:
                    try:
                        # 读取种子文件内容
                        with open(torrent_file, 'rb') as f:
                            torrent_data = f.read()

                        # 准备添加选项
                        add_options = {
                            'paused': paused
                        }
                        if save_path:
                            add_options['download_dir'] = save_path

                        # 添加种子
                        result = client.add_torrent(torrent_data, **add_options)
                        success_count += 1

                        # 如果站点设置了速度限制，则在添加后设置速度限制
                        if site_info and site_info.get('speed_limit', 0) > 0:
                            try:
                                # 转换为 KBps: MB/s * 1024 = KBps
                                speed_limit_kbps = int(site_info['speed_limit']) * 1024
                                client.change_torrent(result.id,
                                                      upload_limit=speed_limit_kbps,
                                                      upload_limited=True)
                                logging.info(f"为站点 '{site_name}' 设置上传速度限制: {site_info['speed_limit']} MB/s ({speed_limit_kbps} KBps)")
                            except Exception as e:
                                logging.warning(f"设置速度限制失败，但种子已添加成功: {e}")

                        logging.info(f"成功添加种子到Transmission: {torrent_file}")

                    except Exception as e:
                        failed_count += 1
                        failed_items.append({'file': torrent_file, 'error': str(e)})
                        logging.error(f"添加种子到Transmission失败 {torrent_file}: {e}")
            else:
                raise ValueError(f"不支持的客户端类型: {type(client)}")

            result = {
                'success': success_count > 0,
                'total': len(torrent_files),
                'success_count': success_count,
                'failed_count': failed_count,
                'failed_items': failed_items
            }

            logging.info(f"添加种子完成: 成功 {success_count}, 失败 {failed_count}")
            return result

        except Exception as e:
            logging.error(f"添加种子到下载器失败: {e}")
            raise

    def transfer_torrents_between_downloaders(self, source_downloader_id: str, target_downloader_id: str,
                                            site_name: str, torrent_name: str, torrent_size: int,
                                            save_path: Optional[str] = None) -> Dict[str, Any]:
        """
        完整的种子转移流程：查找->暂停->导出->添加
        仅使用种子文件进行转移，适用于PT站点

        Args:
            source_downloader_id: 源下载器ID
            target_downloader_id: 目标下载器ID
            site_name: 站点名称
            torrent_name: 种子名称
            torrent_size: 种子大小
            save_path: 保存路径（可选）

        Returns:
            转移结果统计
        """
        try:
            # 第一步：查找种子
            logging.info(f"开始查找种子: {torrent_name}")
            matched_torrents = self.find_torrents_by_site(source_downloader_id, site_name, torrent_name, torrent_size, save_path)

            if not matched_torrents:
                return {
                    'success': False,
                    'message': f"未找到匹配的种子: {torrent_name}",
                    'step': 'find',
                    'found_count': 0
                }

            torrent_hashes = [t['hash'] for t in matched_torrents]
            logging.info(f"找到 {len(torrent_hashes)} 个匹配的种子")

            # 第二步：暂停种子
            logging.info("开始暂停种子")
            pause_success = self.pause_torrents(source_downloader_id, torrent_hashes)

            if not pause_success:
                return {
                    'success': False,
                    'message': "暂停种子失败",
                    'step': 'pause',
                    'found_count': len(matched_torrents)
                }

            # 第三步：尝试使用种子文件转移
            logging.info("尝试使用种子文件转移")
            export_dir = tempfile.mkdtemp(prefix="pt_nexus_transfer_")
            try:
                exported_files = self.export_torrent_files(source_downloader_id, torrent_hashes, export_dir)

                if not exported_files:
                    return {
                        'success': False,
                        'message': "导出种子文件失败，无法进行转移",
                        'step': 'export',
                        'found_count': len(matched_torrents),
                        'method': 'torrent_file'
                    }

                # 添加到目标下载器
                add_result = self.add_torrents_to_downloader(target_downloader_id, exported_files, save_path, paused=True, site_name=site_name)

                return {
                    'success': add_result['success'],
                    'message': "种子转移完成（使用种子文件）" if add_result['success'] else "种子转移部分成功",
                    'step': 'complete',
                    'method': 'torrent_file',
                    'found_count': len(matched_torrents),
                    'pause_success': pause_success,
                    'exported_count': len(exported_files),
                    'add_result': add_result
                }

            finally:
                # 清理临时文件
                import shutil
                shutil.rmtree(export_dir, ignore_errors=True)

        except Exception as e:
            logging.error(f"种子转移失败: {e}")
            return {
                'success': False,
                'message': f"种子转移失败: {str(e)}",
                'step': 'error',
                'error': str(e)
            }

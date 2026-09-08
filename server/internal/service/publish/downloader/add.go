package downloader

import (
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/pt-nexus/server/internal/platform/logx"
	acquirefetch "github.com/pt-nexus/server/internal/service/acquire/fetch"
	"github.com/pt-nexus/server/internal/service/downloaderclient"
	processingpersist "github.com/pt-nexus/server/internal/service/processing/persist"
	processingshared "github.com/pt-nexus/server/internal/service/processing/shared"
	publishguard "github.com/pt-nexus/server/internal/service/publish/guard"
	publishuploader "github.com/pt-nexus/server/internal/service/publish/uploader"
	"gorm.io/gorm"
)

// AddToDownloaderRepo 定义“按详情页反查站点并下载种子”所需依赖。
type AddToDownloaderRepo interface {
	DB() *gorm.DB
}

// AddToDownloader 将发布 URL 或本地种子添加到下载器。
// 参数/返回：payload 为前端传参；rootConfig 为全局配置；repo 可用于从 URL 反查站点并下载种子；返回接口响应与状态码。
// 失败场景：缺少 url/downloaderId、下载器配置错误、添加失败等会返回对应错误；savePath 为空时使用下载器默认路径。
// 副作用：可能发起网络请求下载 torrent，并向下载器添加任务。
func AddToDownloader(payload map[string]any, rootConfig map[string]any, repo AddToDownloaderRepo) (map[string]any, int) {
	rawURL := strings.TrimSpace(processingshared.ToString(payload["url"], ""))
	defaultDownloaderID := resolveDefaultDownloaderID(rootConfig)
	savePath, downloaderID := ResolveEffectiveTarget(payload, "", "", defaultDownloaderID)

	if rawURL == "" || downloaderID == "" {
		return map[string]any{"success": false, "message": "错误：缺少必要参数 (url, downloaderId)。"}, 400
	}

	// 🚫 自动添加前预检查（对齐 Python）：避免触发做种/队列限制。
	canContinue, limitMessage := publishguard.CheckDownloaderGate(downloaderID, rootConfig)
	if !canContinue {
		if strings.TrimSpace(limitMessage) == "" {
			limitMessage = "已触发限制"
		}
		return map[string]any{
			"success":       false,
			"message":       strings.TrimSpace(limitMessage),
			"downloader_id": nil,
			"limit_reached": true,
			"pre_check":     true,
		}, 200
	}

	downloader, err := downloaderclient.FromConfig(rootConfig, downloaderID)
	if err != nil {
		return map[string]any{"success": false, "message": err.Error()}, 400
	}

	manualTags := processingpersist.ParseStringArray(payload["tags"])
	siteNicknameHint := resolvePayloadSiteNickname(payload)
	addOptions := downloaderclient.AddTorrentOptions{Paused: false}
	detailSite := map[string]any{}

	addMessage := ""
	queuedTorrent := ""
	addedTorrentHash := ""
	tagApplyError := ""
	startedAt := time.Now()
	isLocalTorrent := strings.HasPrefix(strings.ToLower(rawURL), "file://") || publishuploader.LooksLikeLocalTorrentPath(rawURL)

	if !isLocalTorrent {
		db := (*gorm.DB)(nil)
		if repo != nil {
			db = repo.DB()
		}
		if db != nil {
			detailSite = acquirefetch.FindSiteByDetailURL(db, rawURL)
			if speedLimit := resolveSiteSpeedLimitMBps(detailSite); speedLimit > 0 {
				addOptions.UploadLimitMBps = speedLimit
			}
		}
	}

	resolvedSiteNickname := siteNicknameHint
	if resolvedSiteNickname == "" {
		resolvedSiteNickname = strings.TrimSpace(processingshared.ToString(detailSite["nickname"], ""))
	}
	if resolvedSiteNickname == "" {
		resolvedSiteNickname = resolveSiteNicknameFromDetail(detailSite)
	}
	configuredTags, configuredCategory := resolveConfiguredTagsAndCategory(rootConfig, resolvedSiteNickname)
	addOptions.Tags = mergeTagLists(manualTags, configuredTags)
	if downloader.Type == "transmission" && configuredCategory != "" {
		addOptions.Tags = appendUniqueTag(addOptions.Tags, configuredCategory)
	}
	if downloader.Type == "qbittorrent" {
		addOptions.Category = configuredCategory
	}

	if strings.HasPrefix(strings.ToLower(rawURL), "file://") {
		parsed, parseErr := url.Parse(rawURL)
		if parseErr != nil || strings.TrimSpace(parsed.Path) == "" {
			return map[string]any{"success": false, "message": "file:// URL 无效"}, 400
		}
		filePath := parsed.Path
		if content, readErr := os.ReadFile(filePath); readErr == nil {
			addedTorrentHash = parseTorrentInfoHash(content)
		}
		if err := downloader.AddTorrentFileWithOptions(filePath, savePath, addOptions); err != nil {
			return map[string]any{"success": false, "message": "添加种子文件失败: " + err.Error()}, 500
		}
		queuedTorrent = filePath
		addMessage = "已通过本地种子文件添加到下载器"
	} else if publishuploader.LooksLikeLocalTorrentPath(rawURL) {
		if content, readErr := os.ReadFile(rawURL); readErr == nil {
			addedTorrentHash = parseTorrentInfoHash(content)
		}
		if err := downloader.AddTorrentFileWithOptions(rawURL, savePath, addOptions); err != nil {
			return map[string]any{"success": false, "message": "添加种子文件失败: " + err.Error()}, 500
		}
		queuedTorrent = rawURL
		addMessage = "已通过本地种子文件添加到下载器"
	} else {
		addedByData := false
		downloadByDataErr := error(nil)
		if len(detailSite) > 0 {
		if _, _, torrentBytes, dlErr := acquirefetch.DownloadTorrentForSource(detailSite, rawURL); dlErr == nil && len(torrentBytes) > 0 {
			if pubURL := strings.TrimSpace(processingshared.ToString(payload["publishURL"], "")); pubURL != "" {
				if rewritten, rErr := acquirefetch.RewriteTorrentComment(torrentBytes, pubURL); rErr == nil && len(rewritten) > 0 {
					torrentBytes = rewritten
				} else if rErr != nil {
					logx.Warnf(downloaderTagLogModule, "发布种子重写 comment 失败 url=%s publishURL=%s err=%v", rawURL, pubURL, rErr)
				}
			}
			addedTorrentHash = parseTorrentInfoHash(torrentBytes)
			fileName := fmt.Sprintf("auto-%d.torrent", time.Now().UnixNano())
			if err := downloader.AddTorrentDataWithOptions(torrentBytes, fileName, savePath, addOptions); err == nil {
					addedByData = true
					addMessage = "已从详情页下载种子并添加到下载器"
				} else {
					downloadByDataErr = fmt.Errorf("下载种子后写入下载器失败: %w", err)
				}
			} else if dlErr != nil {
				downloadByDataErr = fmt.Errorf("从详情页下载种子失败: %w", dlErr)
			}
		}
		if !addedByData {
			if len(detailSite) > 0 && !looksLikeDirectDownloadURL(rawURL) {
				if downloadByDataErr == nil {
					downloadByDataErr = fmt.Errorf("详情页链接未能解析出可直接下载的 torrent 文件")
				}
				return map[string]any{"success": false, "message": "添加下载任务失败: " + downloadByDataErr.Error()}, 500
			}
			if err := downloader.AddTorrentURLWithOptions(rawURL, savePath, addOptions); err != nil {
				return map[string]any{"success": false, "message": "添加下载任务失败: " + err.Error()}, 500
			}
			addMessage = "已通过 URL 添加到下载器"
		}
	}

	if addedTorrentHash != "" && len(addOptions.Tags) > 0 {
		if err := applyTorrentTagsWithRetry(downloader, addedTorrentHash, addOptions.Tags); err != nil {
			tagApplyError = err.Error()
			logx.Warnf(downloaderTagLogModule, "下载器任务已添加但站点标签补写失败 downloader=%s hash=%s site=%s tags=%v err=%v", downloader.Name, addedTorrentHash, resolvedSiteNickname, addOptions.Tags, err)
		} else {
			logx.Infof(downloaderTagLogModule, "下载器站点标签补写成功 downloader=%s hash=%s site=%s tags=%v", downloader.Name, addedTorrentHash, resolvedSiteNickname, addOptions.Tags)
		}
	}

	resultMessage := addMessage
	if tagApplyError != "" {
		resultMessage += "；任务已添加，但标签补写失败"
	}
	return map[string]any{
		"success":          true,
		"message":          resultMessage,
		"downloader_id":    downloader.ID,
		"downloader_name":  downloader.Name,
		"hash":             addedTorrentHash,
		"queued_torrent":   queuedTorrent,
		"site_nickname":    resolvedSiteNickname,
		"applied_tags":     addOptions.Tags,
		"tag_apply_error":  tagApplyError,
		"applied_category": configuredCategory,
		"cost_ms":          time.Since(startedAt).Milliseconds(),
	}, 200
}

const downloaderTagLogModule = "发布-下载器标签"

// parseTorrentInfoHash 从 torrent 文件内容中提取 infohash。
// 参数/返回：content 为 bencode 编码的 torrent 文件；解析成功返回小写 infohash，否则返回空字符串。
// 失败场景：内容为空或 torrent 格式非法时返回空字符串。
// 副作用：无。
func parseTorrentInfoHash(content []byte) string {
	if len(content) == 0 {
		return ""
	}
	meta, err := acquirefetch.ParseTorrentMeta(content)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(meta.InfoHash)
}

// applyTorrentTagsWithRetry 在添加任务后等待下载器完成入库，再补写标签。
// 参数/返回：downloader 为目标下载器；hash 为任务 infohash；tags 为要写入的标签；返回最后一次接口错误。
// 失败场景：下载器暂时未完成任务入库或标签接口持续返回错误时返回错误。
// 副作用：最多向下载器发起三次标签写入请求，并短暂等待任务可见。
func applyTorrentTagsWithRetry(downloader downloaderclient.Downloader, hash string, tags []string) error {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if err := downloader.ApplyTorrentTags([]string{hash}, tags); err == nil {
			return nil
		} else {
			lastErr = err
		}
		if attempt < 2 {
			time.Sleep(300 * time.Millisecond)
		}
	}
	return lastErr
}

func resolveSiteSpeedLimitMBps(site map[string]any) int {
	if len(site) == 0 {
		return 0
	}
	value, exists := site["speed_limit"]
	if !exists || value == nil {
		return 0
	}
	limit := int(processingshared.ToFloat(value))
	if limit <= 0 {
		return 0
	}
	return limit
}

// resolvePayloadSiteNickname 从发布/加种请求中提取目标站点显示名。
// 参数/返回：payload 为请求参数；优先返回 nickname 类字段，其次回退到 targetSite/site 字段。
// 失败场景：payload 为空或字段为空时返回空字符串。
// 副作用：无。
func resolvePayloadSiteNickname(payload map[string]any) string {
	if len(payload) == 0 {
		return ""
	}
	for _, key := range []string{
		"siteNickname",
		"site_nickname",
		"targetSiteNickname",
		"target_site_nickname",
		"targetNickname",
		"target_nickname",
		"targetSite",
		"target_site",
		"siteName",
		"site_name",
		"nickname",
		"site",
	} {
		if value := strings.TrimSpace(processingshared.ToString(payload[key], "")); value != "" {
			return value
		}
	}
	return ""
}

// resolveSiteNicknameFromDetail 从详情页反查到的站点记录中提取显示名。
// 参数/返回：site 为 sites 表记录；优先返回 nickname，其次回退到站点名称或站点标识。
// 失败场景：记录为空或字段为空时返回空字符串。
// 副作用：无。
func resolveSiteNicknameFromDetail(site map[string]any) string {
	if len(site) == 0 {
		return ""
	}
	for _, key := range []string{"nickname", "site_name", "name", "site"} {
		if value := strings.TrimSpace(processingshared.ToString(site[key], "")); value != "" {
			return value
		}
	}
	return ""
}

// resolveConfiguredTagsAndCategory 解析设置中心下载器标签/分类配置。
// 参数/返回：rootConfig 为全局配置，siteNickname 用于替换“站点/{站点名称}”占位符；返回标签列表和分类。
// 失败场景：配置缺失或字段类型异常时返回空结果。
// 副作用：无。
func resolveConfiguredTagsAndCategory(rootConfig map[string]any, siteNickname string) ([]string, string) {
	if len(rootConfig) == 0 {
		return []string{}, ""
	}
	tagsConfig, ok := rootConfig["tags_config"].(map[string]any)
	if !ok {
		return []string{}, ""
	}

	categoryName := ""
	if categoryConfig, ok := tagsConfig["category"].(map[string]any); ok {
		if processingpersist.BoolFromAny(categoryConfig["enabled"]) {
			categoryName = strings.TrimSpace(processingshared.ToString(categoryConfig["category"], ""))
		}
	}

	finalTags := []string{}
	if tagsConfigMap, ok := tagsConfig["tags"].(map[string]any); ok {
		tagsEnabled := processingpersist.BoolFromAny(tagsConfigMap["enabled"])
		for _, rawTag := range processingpersist.ParseStringArray(tagsConfigMap["tags"]) {
			tag := strings.TrimSpace(rawTag)
			if tag == "" {
				continue
			}
			isSiteNameTag := tag == "站点/{站点名称}"
			if !tagsEnabled && !isSiteNameTag {
				continue
			}
			if isSiteNameTag {
				if siteNickname == "" {
					continue
				}
				tag = "站点/" + siteNickname
			}
			finalTags = appendUniqueTag(finalTags, tag)
		}
	}

	return finalTags, categoryName
}

// mergeTagLists 合并多个标签列表并去重，保持原始顺序。
// 参数/返回：inputs 为待合并标签列表；返回去重后的标签切片。
// 失败场景：输入为空时返回空切片。
// 副作用：无。
func mergeTagLists(inputs ...[]string) []string {
	merged := make([]string, 0)
	for _, input := range inputs {
		for _, tag := range input {
			merged = appendUniqueTag(merged, tag)
		}
	}
	return merged
}

// appendUniqueTag 向标签列表追加单个标签并去重。
// 参数/返回：tags 为原列表，tag 为待追加值；返回去重后的列表。
// 失败场景：tag 为空时返回原列表。
// 副作用：无。
func appendUniqueTag(tags []string, tag string) []string {
	trimmed := strings.TrimSpace(tag)
	if trimmed == "" {
		return tags
	}
	for _, current := range tags {
		if current == trimmed {
			return tags
		}
	}
	return append(tags, trimmed)
}

func looksLikeDirectDownloadURL(raw string) bool {
	lower := strings.ToLower(strings.TrimSpace(raw))
	if lower == "" {
		return false
	}
	return strings.Contains(lower, "/download.php") ||
		strings.Contains(lower, ".torrent") ||
		strings.Contains(lower, "/api/torrent/") && strings.Contains(lower, "/download/") ||
		strings.Contains(lower, "/api/torrent/download/") ||
		matchesTTGDownloadPattern(lower)
}

// matchesTTGDownloadPattern 匹配 TTG 的 /dl/{id}/{passkey} 下载链接格式。
func matchesTTGDownloadPattern(lower string) bool {
	idx := strings.Index(lower, "/dl/")
	if idx < 0 {
		return false
	}
	rest := lower[idx+4:]
	parts := strings.SplitN(rest, "/", 2)
	if len(parts) < 2 {
		return false
	}
	for _, ch := range parts[0] {
		if ch < '0' || ch > '9' {
			return false
		}
	}
	return len(parts[0]) > 0 && len(parts[1]) > 0
}

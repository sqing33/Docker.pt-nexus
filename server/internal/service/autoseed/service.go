package autoseed

import (
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"hash/fnv"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/pt-nexus/server/internal/config"
	"github.com/pt-nexus/server/internal/platform/logx"
	"github.com/pt-nexus/server/internal/repository"
	"github.com/pt-nexus/server/internal/service/acquire/fetch"
	"github.com/pt-nexus/server/internal/service/downloaderclient"
	processingrepair "github.com/pt-nexus/server/internal/service/processing/repair"
	processingshared "github.com/pt-nexus/server/internal/service/processing/shared"
	"gorm.io/gorm"
)

const (
	moduleAutoSeed         = "自动发种"
	minDownloaderFreeBytes = int64(10 * 1024 * 1024 * 1024)
)

var autoSeedEpisodePattern = regexp.MustCompile(`(?i)(?:\bs\d{1,3}e\d{1,4}\b|\bep\d{1,4}\b|第\s*\d{1,4}\s*集)`)

// rewriteTorrentCommentIfNeeded 在本地 .torrent 文件存在时，把详情页地址写入其 comment 字段，
// 以便后续下载器同步时能通过 extractDetailFromComment 解析出 details。保持 infohash 不变。
// torrentPath 为 fetchItemDetails 下载到本地的种子文件路径；detailURL 为站点详情页地址。
// 失败静默（仅记录日志），不影响后续添加下载器流程。
func rewriteTorrentCommentIfNeeded(torrentPath, detailURL string) {
	torrentPath = strings.TrimSpace(torrentPath)
	detailURL = strings.TrimSpace(detailURL)
	if torrentPath == "" || detailURL == "" {
		return
	}
	content, err := os.ReadFile(torrentPath)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "写入种子 comment 前读取文件失败 path=%s err=%v", torrentPath, err)
		return
	}
	if len(content) == 0 {
		return
	}
	rewritten, err := fetch.RewriteTorrentComment(content, detailURL)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "重写种子 comment 失败 path=%s detail=%s err=%v", torrentPath, detailURL, err)
		return
	}
	if len(rewritten) == 0 {
		return
	}
	if err := os.WriteFile(torrentPath, rewritten, 0o644); err != nil {
		logx.Warnf(moduleAutoSeed, "写回种子 comment 失败 path=%s err=%v", torrentPath, err)
	}
}

// EnqueueFn 定义自动发种向现有发布队列投递任务的函数签名。
type EnqueueFn func(payload map[string]any) (map[string]any, int)

// FetchSeedFn 定义自动发种复用详情抓取与种子下载链路的函数签名。
type FetchSeedFn func(payload map[string]any) (map[string]any, int)

// Service 编排自动发种规则、RSS 拉取、下载器推送、进度同步和发布入队。
// 参数/返回：依赖仓储、配置和发布队列函数；接口方法返回结果 map 与错误。
// 失败场景：配置缺失、RSS 请求失败、下载器不可用或数据库写入失败时返回 error。
// 副作用：会发起网络请求、写数据库、向下载器添加/删除任务，并启动后台 goroutine。
type Service struct {
	repo      *repository.AutoSeedRepository
	cfg       *config.Manager
	enqueueFn EnqueueFn
	fetchFn   FetchSeedFn

	stopCh    chan struct{}
	doneCh    chan struct{}
	triggerCh chan int64
	once      sync.Once
}

// NewService 创建自动发种服务实例。
func NewService(repo *repository.AutoSeedRepository, cfg *config.Manager) *Service {
	return &Service{
		repo:      repo,
		cfg:       cfg,
		stopCh:    make(chan struct{}),
		doneCh:    make(chan struct{}),
		triggerCh: make(chan int64, 32),
	}
}

// SetEnqueueFn 注入发布队列入队函数。
func (s *Service) SetEnqueueFn(fn EnqueueFn) {
	if s == nil {
		return
	}
	s.enqueueFn = fn
}

// SetFetchSeedFn 注入详情抓取与种子下载函数。
func (s *Service) SetFetchSeedFn(fn FetchSeedFn) {
	if s == nil {
		return
	}
	s.fetchFn = fn
}

// Start 启动后台自动发种轮询任务。
func (s *Service) Start() {
	if s == nil {
		return
	}
	s.once.Do(func() {
		go s.run()
		logx.Infof(moduleAutoSeed, "自动发种调度器已启动")
	})
}

// Stop 停止后台自动发种轮询任务。
func (s *Service) Stop() {
	if s == nil {
		return
	}
	select {
	case <-s.stopCh:
	default:
		close(s.stopCh)
		<-s.doneCh
	}
}

// TriggerRule 手动触发指定规则立即拉取一次 RSS。
func (s *Service) TriggerRule(ruleID int64) {
	if s == nil || ruleID <= 0 {
		return
	}
	select {
	case s.triggerCh <- ruleID:
	default:
		logx.Warnf(moduleAutoSeed, "手动触发队列已满 rule_id=%d", ruleID)
	}
}

func (s *Service) run() {
	defer close(s.doneCh)
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			s.processTick()
		case ruleID := <-s.triggerCh:
			s.processRuleByID(ruleID)
		case <-s.stopCh:
			return
		}
	}
}

func (s *Service) processTick() {
	if s == nil || s.repo == nil {
		return
	}
	now := time.Now()
	rules, err := s.repo.FindDueRules(now)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "查询到期规则失败 err=%v", err)
		return
	}
	for idx := range rules {
		s.processRule(&rules[idx])
	}
	s.SyncProgressAndAutoPublish("")
	s.cleanupExpiredRetainedSeeds()
}

func (s *Service) processRuleByID(ruleID int64) {
	rule, err := s.repo.GetRule(ruleID)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "查询手动规则失败 rule_id=%d err=%v", ruleID, err)
		return
	}
	s.processRule(rule)
}

func (s *Service) processRule(rule *repository.AutoSeedRule) {
	if s == nil || s.repo == nil || rule == nil {
		return
	}
	next := time.Now().Add(time.Duration(clampInt(rule.PullIntervalMinutes, 1, 1440)) * time.Minute)

	root := s.rootConfig()
	downloader, downloaderErr := downloaderclient.FromConfig(root, strings.TrimSpace(rule.DownloaderID))
	if downloaderErr != nil {
		_ = s.repo.MarkRulePulled(rule.ID, next, "未获取到下载器: "+downloaderErr.Error(), rule.Enabled)
		logx.Warnf(moduleAutoSeed, "规则缺少下载器 rule_id=%d err=%v", rule.ID, downloaderErr)
		return
	}

	freeBytes, freeErr := downloader.FetchFreeSpaceBytes()
	if freeErr == nil && freeBytes > 0 && freeBytes < minDownloaderFreeBytes {
		reason := "下载器空间已满，可用空间不足 10GB"
		enabled := rule.Enabled
		if rule.AutoPause {
			enabled = false
		}
		_ = s.repo.MarkRulePulled(rule.ID, next, reason, enabled)
		logx.Warnf(moduleAutoSeed, "规则暂停 rule_id=%d reason=%s free_bytes=%d", rule.ID, reason, freeBytes)
		return
	}

	entries, err := fetchRSS(rule.RSSURL)
	if err != nil {
		_ = s.repo.MarkRulePulled(rule.ID, next, "RSS 拉取失败: "+err.Error(), rule.Enabled)
		logx.Warnf(moduleAutoSeed, "RSS 拉取失败 rule_id=%d err=%v", rule.ID, err)
		return
	}

	for _, entry := range entries {
		item := s.buildItemFromEntry(rule, entry)
		reason := rejectReason(rule, item)
		if reason != "" {
			item.Status = repository.AutoSeedItemStatusRejected
			item.RejectReason = reason
			_, _, _ = s.repo.UpsertItem(item)
			continue
		}
		created, isNew, err := s.repo.UpsertItem(item)
		if err != nil {
			logx.Warnf(moduleAutoSeed, "写入 RSS 记录失败 rule_id=%d name=%s err=%v", rule.ID, item.Name, err)
			continue
		}
		if created == nil {
			continue
		}
		if !isNew {
			if !shouldRetryAutoSeedItem(created) {
				continue
			}
			previousReason := created.RejectReason
			item.ID = created.ID
			item.CreatedAt = created.CreatedAt
			if err := s.repo.ResetItemForRetry(item); err != nil {
				logx.Warnf(moduleAutoSeed, "重置自动发种记录失败 rule_id=%d item_id=%d name=%s err=%v", rule.ID, created.ID, item.Name, err)
				continue
			}
			created = item
			logx.Infof(moduleAutoSeed, "自动发种记录重新推送 rule_id=%d item_id=%d name=%s previous_reason=%s", rule.ID, created.ID, created.Name, previousReason)
		}
		fetchResult, fetchReason := s.fetchItemDetails(created)
		if fetchReason != "" {
			_ = s.repo.MarkItemRejected(created.ID, fetchReason)
			continue
		}
		if reason := rejectReason(rule, created); reason != "" {
			_ = s.repo.MarkItemRejected(created.ID, reason)
			continue
		}
		skipChecking := false
		siteSpeedLimit := s.repo.GetSiteSpeedLimit(rule.SourceSite)
		options := downloaderclient.AddTorrentOptions{
			Paused:          rule.AutoPause,
			Tags:            parseJSONStrings(rule.TagsJSON),
			UploadLimitMBps: siteSpeedLimit,
			SkipChecking:    &skipChecking,
		}
		torrentPath := strings.TrimSpace(toString(fetchResult["torrent_path"], ""))
		var addErr error
		if torrentPath != "" {
			rewriteTorrentCommentIfNeeded(torrentPath, toString(fetchResult["detail_url"], ""))
			addErr = downloader.AddTorrentFileWithOptions(torrentPath, "", options)
		} else {
			addErr = downloader.AddTorrentURLWithOptions(created.TorrentURL, "", options)
		}
		if addErr != nil {
			_ = s.repo.MarkItemRejected(created.ID, "推送下载器失败: "+addErr.Error())
			continue
		}
		hash := firstNonEmpty(toString(fetchResult["hash"], ""), s.findDownloaderHash(downloader, created.Name))
		_ = s.repo.MarkItemPushed(created.ID, firstNonEmpty(created.DownloaderID, item.DownloaderID), hash, "")
	}

	_ = s.repo.MarkRulePulled(rule.ID, next, "", rule.Enabled)
}

// SyncProgressAndAutoPublish 同步下载器进度，并对已完成记录执行自动整理和发布。
func (s *Service) SyncProgressAndAutoPublish(downloaderID string) {
	items, err := s.repo.ListProgressItems(downloaderID)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "查询进度记录失败 err=%v", err)
		return
	}
	root := s.rootConfig()
	byDownloader := map[string][]repository.AutoSeedItem{}
	for _, item := range items {
		if strings.TrimSpace(item.DownloaderID) == "" {
			continue
		}
		byDownloader[item.DownloaderID] = append(byDownloader[item.DownloaderID], item)
	}
	for id, rows := range byDownloader {
		d, err := downloaderclient.FromConfig(root, id)
		if err != nil {
			continue
		}
		snapshots, err := d.FetchTorrents()
		if err != nil {
			logx.Warnf(moduleAutoSeed, "同步下载器进度失败 downloader_id=%s err=%v", id, err)
			continue
		}
		for _, item := range rows {
			if strings.TrimSpace(item.DownloaderHash) == "" {
				item.DownloaderHash = s.findItemInfoHash(item)
				// 内存补全后立即回写 DB，避免后续保种清理因 downloader_hash 为空查不到记录
				if strings.TrimSpace(item.DownloaderHash) != "" {
					_ = s.repo.UpdateItemDownloaderHash(item.ID, item.DownloaderID, item.DownloaderHash)
				}
			}
			if snapshot, ok := matchSnapshot(item, snapshots); ok {
				downloaded := snapshot.Progress >= 99.9
				_ = s.repo.UpdateItemProgress(item.ID, snapshot.Progress, downloaded, snapshot.Hash)
				if reason := restrictedTagRejectReason(&item); reason != "" {
					_ = s.repo.MarkItemRejected(item.ID, reason)
					continue
				}
				if downloaded && (item.Status == repository.AutoSeedItemStatusPushed || item.Status == repository.AutoSeedItemStatusOrganized) {
					s.autoOrganizeAndPublish(item)
				}
			}
		}
	}
}

func (s *Service) findItemInfoHash(item repository.AutoSeedItem) string {
	if s == nil || s.repo == nil || strings.TrimSpace(item.TorrentID) == "" {
		return ""
	}
	siteName := firstNonEmpty(item.SiteName, item.SourceSite)
	if siteName == "" {
		return ""
	}
	row, err := s.repo.GetSeedParameter(item.TorrentID, siteName)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(toString(row["hash"], ""))
}

// autoOrganizeAndPublish 在种子下载完成后补全整理状态并投递自动发种任务。
// 参数/返回：item 为已完成下载的自动发种记录；发布结果写入记录和发布队列。
// 失败场景：规则不存在、未配置目标站点、缺少源站种子信息或入队失败时记录原因并保留可重试状态。
// 副作用：更新自动发种记录，并向发布队列写入任务和日志。
func (s *Service) autoOrganizeAndPublish(item repository.AutoSeedItem) {
	if item.RuleID <= 0 {
		return
	}
	rule, err := s.repo.GetRule(item.RuleID)
	if err != nil {
		reason := "自动发种未执行：未找到规则"
		_ = s.repo.UpdateItemPublishFeedback(item.ID, item.PublishResultsJSON, reason)
		logx.Warnf(moduleAutoSeed, "%s item_id=%d rule_id=%d err=%v", reason, item.ID, item.RuleID, err)
		return
	}
	nowText := time.Now().Format(repository.PublishQueueTimeLayout)
	if rule.AutoOrganize && item.Status == repository.AutoSeedItemStatusPushed {
		item.Status = repository.AutoSeedItemStatusOrganized
		item.OrganizedAt = &nowText
		if strings.TrimSpace(item.TorrentID) == "" {
			item.TorrentID = inferTorrentID(item)
		}
		if strings.TrimSpace(item.SiteName) == "" {
			item.SiteName = firstNonEmpty(item.SourceSite, rule.SourceSite)
		}
		_ = s.repo.UpdateItemBasics(&item)
	}
	targetSites := parseJSONStrings(rule.TargetSitesJSON)
	if len(targetSites) == 0 {
		reason := "自动发种未执行：规则未配置发布站点"
		_ = s.repo.UpdateItemPublishFeedback(item.ID, item.PublishResultsJSON, reason)
		logx.Warnf(moduleAutoSeed, "%s item_id=%d rule_id=%d", reason, item.ID, rule.ID)
		return
	}
	if strings.TrimSpace(item.TorrentID) == "" || strings.TrimSpace(firstNonEmpty(item.SiteName, item.SourceSite)) == "" {
		reason := "自动发种未执行：缺少源站种子信息"
		_ = s.repo.UpdateItemPublishFeedback(item.ID, item.PublishResultsJSON, reason)
		logx.Warnf(moduleAutoSeed, "%s item_id=%d", reason, item.ID)
		return
	}
	siteName := firstNonEmpty(item.SiteName, item.SourceSite, rule.SourceSite)
	if s.shouldRefreshAutoSeedScreenshots(item, siteName) {
		if err := s.refreshAutoSeedScreenshots(item, siteName); err != nil {
			reason := "自动发种未执行：截图自动生成失败: " + err.Error()
			_ = s.repo.UpdateItemPublishFeedback(item.ID, item.PublishResultsJSON, reason)
			logx.Warnf(moduleAutoSeed, "自动发种随机截图刷新失败 item_id=%d rule_id=%d site=%s err=%v", item.ID, rule.ID, siteName, err)
			return
		}
	}
	if _, err := s.PublishItems([]int64{item.ID}, targetSites); err != nil {
		reason := "自动发种未执行：发布入队失败: " + err.Error()
		_ = s.repo.UpdateItemPublishFeedback(item.ID, item.PublishResultsJSON, reason)
		logx.Warnf(moduleAutoSeed, "自动发种入队失败 item_id=%d rule_id=%d err=%v", item.ID, rule.ID, err)
	}
}

// shouldRefreshAutoSeedScreenshots 判断自动发种入队前是否需要强制重建正式截图。
// 参数/返回：item 为自动发种记录，siteName 为源站；返回 true 表示需要随机生成 3 张正式截图。
// 失败场景：种子参数读取失败时仅记录日志并跳过强制刷新，由后续发布流程继续处理。
// 副作用：会读取 seed_parameters 中的截图与人工确认状态。
func (s *Service) shouldRefreshAutoSeedScreenshots(item repository.AutoSeedItem, siteName string) bool {
	if isAutoSeedAlwaysRefreshScreenshotSource(siteName) {
		return true
	}
	if s == nil || s.repo == nil {
		return false
	}
	torrentID := strings.TrimSpace(item.TorrentID)
	if torrentID == "" {
		torrentID = inferTorrentID(item)
	}
	if torrentID == "" || strings.TrimSpace(siteName) == "" {
		return false
	}
	row, err := s.repo.GetSeedParameter(torrentID, siteName)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "读取自动发种截图状态失败 item_id=%d torrent_id=%s site=%s err=%v", item.ID, torrentID, siteName, err)
		return false
	}
	return needsRefreshAutoSeedScreenshotsFromSeedRow(siteName, row)
}

func needsRefreshAutoSeedScreenshotsFromSeedRow(siteName string, row map[string]any) bool {
	if isAutoSeedAlwaysRefreshScreenshotSource(siteName) {
		return true
	}
	screenshots := strings.TrimSpace(toString(row["screenshots"], ""))
	status := processingshared.NormalizeScreenshotReviewStatus(
		toString(row["screenshot_review_status"], processingshared.ScreenshotReviewStatusNone),
	)
	return screenshots == "" || processingshared.NeedsScreenshotManualReview(status)
}

// refreshAutoSeedScreenshots 为自动发种记录重新生成 3 张随机正式截图，并写回种子参数。
// 参数/返回：item 为已下载完成的自动发种记录；siteName 为实际源站名称；失败时返回错误并阻止继续发种。
// 副作用：会读取当前下载器保存路径、调用截图生成流程、写回 seed_parameters.screenshots。
func (s *Service) refreshAutoSeedScreenshots(item repository.AutoSeedItem, siteName string) error {
	if s == nil || s.repo == nil {
		return errors.New("自动发种仓储未初始化")
	}
	if strings.TrimSpace(siteName) == "" {
		return errors.New("源站名称不能为空")
	}
	record, ok, err := s.resolveItemCurrentTorrentRecord(item)
	if err != nil {
		return err
	}
	if !ok {
		return errors.New("下载器中未找到已完成任务，无法生成截图")
	}
	if record.Progress > 0 && record.Progress < 99.9 {
		return fmt.Errorf("下载器任务尚未完成，当前进度 %.1f%%", record.Progress)
	}
	savePath := strings.TrimSpace(record.SavePath)
	if savePath == "" {
		return errors.New("下载器任务缺少可用于截图的路径")
	}
	torrentID := strings.TrimSpace(item.TorrentID)
	if torrentID == "" {
		torrentID = inferTorrentID(item)
	}
	if torrentID == "" {
		return errors.New("未找到种子 ID")
	}
	contentName := firstNonEmpty(record.Name, item.Name, item.Subtitle)
	downloaderHash := firstNonEmpty(item.DownloaderHash, record.Hash)
	if downloaderHash == "" {
		return errors.New("下载器任务缺少可用于截图的 hash")
	}
	input := processingrepair.ScreenshotGenerateInput{
		Payload: map[string]any{
			"downloader_id":   item.DownloaderID,
			"downloader_hash": downloaderHash,
			"save_path":       savePath,
			"torrent_name":    contentName,
			"name":            contentName,
		},
		SourceInfo: map[string]any{
			"save_path":  savePath,
			"main_title": contentName,
		},
		ContentName: contentName,
		RootConfig:  s.rootConfig(),
	}
	urls, err := processingrepair.GenerateAndUploadRandomScreenshots(input, processingrepair.ScreenshotCountFromConfig(input.RootConfig))
	if err != nil {
		return err
	}
	screenshots := strings.TrimSpace(processingrepair.ToBBCodeImages(urls))
	if screenshots == "" {
		return errors.New("未生成有效截图")
	}
	if err := s.repo.UpdateSeedParameterScreenshotsByTorrentIDAndSiteName(torrentID, siteName, screenshots); err != nil {
		return err
	}
	logx.Infof(moduleAutoSeed, "自动发种随机截图刷新成功 item_id=%d torrent_id=%s site=%s count=%d", item.ID, torrentID, siteName, len(urls))
	return nil
}

func isNovaHDSource(siteName string) bool {
	normalized := strings.ToLower(strings.TrimSpace(siteName))
	switch normalized {
	case "novahd", "nova hd", "nova-hd", "nova_hd", "novahd.top":
		return true
	default:
		return strings.Contains(normalized, "novahd")
	}
}

func isDStudioSource(siteName string) bool {
	normalized := strings.ToLower(strings.TrimSpace(siteName))
	switch normalized {
	case "ds", "dstudio", "depth studio", "dstudio.me", "屌丝":
		return true
	default:
		return strings.Contains(normalized, "dstudio") || strings.Contains(normalized, "depth studio") || strings.Contains(normalized, "屌丝")
	}
}

func isAutoSeedAlwaysRefreshScreenshotSource(siteName string) bool {
	return isNovaHDSource(siteName) || isDStudioSource(siteName)
}

// ListRules 返回自动发种规则列表。
func (s *Service) ListRules() ([]repository.AutoSeedRule, error) {
	return s.repo.ListRules()
}

// SaveRule 新增或更新自动发种规则。
func (s *Service) SaveRule(rule *repository.AutoSeedRule) error {
	normalizeRule(rule)
	if rule.ID > 0 {
		return s.repo.UpdateRule(rule)
	}
	return s.repo.CreateRule(rule)
}

// DeleteRule 删除自动发种规则。
func (s *Service) DeleteRule(id int64) error {
	return s.repo.DeleteRule(id)
}

// ListItems 查询自动发种列表，并附加最新发布日志摘要。
func (s *Service) ListItems(query repository.AutoSeedListQuery) ([]repository.AutoSeedItem, int64, error) {
	rows, total, err := s.repo.ListItems(query)
	if err != nil {
		return nil, 0, err
	}
	s.enrichItemSeedParameters(rows)
	s.enrichItemSavePaths(rows)
	s.enrichItemPublishResults(rows)
	return rows, total, nil
}

// AddManualURL 将用户输入的种子地址加入自动发种列表，并自动抓取详情页数据和推送下载器。
func (s *Service) AddManualURL(torrentURL, downloaderID, sourceSite string) error {
	torrentURL = strings.TrimSpace(torrentURL)
	if torrentURL == "" {
		return errors.New("种子地址不能为空")
	}
	sourceSite = strings.TrimSpace(sourceSite)
	if sourceSite == "" {
		return errors.New("请选择源站")
	}
	torrentID := firstNonEmpty(inferTorrentIDFromURL(torrentURL), torrentURL)
	item := &repository.AutoSeedItem{
		RuleID:       0,
		SourceSite:   sourceSite,
		GUID:         stableID(torrentURL),
		TorrentURL:   torrentURL,
		DetailURL:    torrentURL,
		Name:         filepath.Base(strings.Split(torrentURL, "?")[0]),
		Status:       repository.AutoSeedItemStatusPending,
		DownloaderID: strings.TrimSpace(downloaderID),
		SiteName:     sourceSite,
		TorrentID:    torrentID,
	}
	if item.Name == "." || item.Name == "/" || strings.TrimSpace(item.Name) == "" {
		item.Name = torrentURL
	}
	if err := s.repo.CreateManualItem(item); err != nil {
		return err
	}
	fetchResult, fetchReason := s.fetchItemDetails(item)
	if fetchReason != "" {
		_ = s.repo.MarkItemRejected(item.ID, fetchReason)
		return nil
	}
	if reason := restrictedTagRejectReason(item); reason != "" {
		_ = s.repo.MarkItemRejected(item.ID, reason)
		return nil
	}
	if strings.TrimSpace(downloaderID) == "" {
		_ = s.repo.MarkItemRejected(item.ID, "未获取到下载器")
		return nil
	}
	d, err := downloaderclient.FromConfig(s.rootConfig(), downloaderID)
	if err != nil {
		_ = s.repo.MarkItemRejected(item.ID, "未获取到下载器: "+err.Error())
		return nil
	}
	addErr := error(nil)
	manualOptions := newAutoSeedAddTorrentOptions(false, []string{"PT Nexus", "自动发种"}, 0)
	torrentPath := toString(fetchResult["torrent_path"], "")
	if torrentPath != "" {
		rewriteTorrentCommentIfNeeded(torrentPath, toString(fetchResult["detail_url"], ""))
		addErr = d.AddTorrentFileWithOptions(torrentPath, "", manualOptions)
	} else {
		addErr = d.AddTorrentURLWithOptions(torrentURL, "", manualOptions)
	}
	if addErr != nil {
		_ = s.repo.MarkItemRejected(item.ID, "推送下载器失败: "+addErr.Error())
		return nil
	}
	downloaderHash := firstNonEmpty(toString(fetchResult["hash"], ""), s.findDownloaderHash(d, item.Name))
	_ = s.repo.MarkItemPushed(item.ID, item.DownloaderID, downloaderHash, "")
	return nil
}

// OrganizeItem 保存人工整理后的基础种子信息。

// PushItems 将未推送的自动发种记录补抓详情并推送到下载器，进入后续自动整理和发布流程。
// 参数/返回：ids 为待推送记录主键集合；返回每条记录的推送结果与总体成功状态。
// 失败场景：仓储未初始化、未选择记录、下载器配置缺失、详情抓取失败或推送下载器失败。
// 副作用：会写回自动发种记录状态、推送时间与下载器 hash，并可能更新详情页抓取结果。
func (s *Service) PushItems(ids []int64) (map[string]any, error) {
	if s == nil || s.repo == nil {
		return nil, errors.New("自动发种仓储未初始化")
	}
	if len(ids) == 0 {
		return nil, errors.New("请选择要推送的种子")
	}

	results := make([]map[string]any, 0, len(ids))
	pushedCount := 0
	for _, id := range ids {
		item, err := s.repo.GetItem(id)
		if err != nil {
			results = append(results, map[string]any{"id": id, "success": false, "message": err.Error()})
			continue
		}
		if item == nil {
			results = append(results, map[string]any{"id": id, "success": false, "message": "种子记录为空"})
			continue
		}
		switch item.Status {
		case repository.AutoSeedItemStatusPushed, repository.AutoSeedItemStatusOrganized, repository.AutoSeedItemStatusPublished:
			results = append(results, map[string]any{"id": id, "success": false, "message": "已推送或已进入后续流程"})
			continue
		}

		downloaderID, options, err := s.resolveAutoSeedPushSettings(item)
		if err != nil {
			_ = s.repo.MarkItemRejected(item.ID, "推送下载器失败: "+err.Error())
			results = append(results, map[string]any{"id": id, "success": false, "message": err.Error()})
			continue
		}
		item.DownloaderID = downloaderID

		fetchResult, fetchReason := s.fetchItemDetails(item)
		if fetchReason != "" {
			_ = s.repo.MarkItemRejected(item.ID, fetchReason)
			results = append(results, map[string]any{"id": id, "success": false, "message": fetchReason})
			continue
		}
		if reason := restrictedTagRejectReason(item); reason != "" {
			_ = s.repo.MarkItemRejected(item.ID, reason)
			results = append(results, map[string]any{"id": id, "success": false, "message": reason})
			continue
		}

		downloader, err := downloaderclient.FromConfig(s.rootConfig(), downloaderID)
		if err != nil {
			reason := "推送下载器失败: " + err.Error()
			_ = s.repo.MarkItemRejected(item.ID, reason)
			results = append(results, map[string]any{"id": id, "success": false, "message": reason})
			continue
		}
		if err := s.pushFetchedItemToDownloader(item, fetchResult, downloader, options); err != nil {
			reason := "推送下载器失败: " + err.Error()
			_ = s.repo.MarkItemRejected(item.ID, reason)
			results = append(results, map[string]any{"id": id, "success": false, "message": reason})
			continue
		}

		pushedCount++
		results = append(results, map[string]any{
			"id":      id,
			"success": true,
			"message": "已推送到下载器",
		})
	}

	if pushedCount == 0 {
		return map[string]any{"success": false, "results": results}, errors.New("没有可推送的种子")
	}
	return map[string]any{
		"success":      true,
		"pushed_count": pushedCount,
		"results":      results,
	}, nil
}

// resolveAutoSeedPushSettings 为自动发种推送按钮准备下载器与附加参数。
// 参数/返回：item 为待推送记录；返回下载器 ID 与 AddTorrentOptions。
// 失败场景：记录未配置下载器且无法从规则回填时返回错误。
// 副作用：必要时读取对应自动发种规则，但不会写库。
func (s *Service) resolveAutoSeedPushSettings(item *repository.AutoSeedItem) (string, downloaderclient.AddTorrentOptions, error) {
	options := newAutoSeedAddTorrentOptions(false, []string{"PT Nexus", "自动发种"}, 0)
	if item == nil {
		return "", options, errors.New("种子记录为空")
	}

	downloaderID := strings.TrimSpace(item.DownloaderID)
	paused := false
	tags := []string{"PT Nexus", "自动发种"}

	if item.RuleID > 0 && s != nil && s.repo != nil {
		if rule, err := s.repo.GetRule(item.RuleID); err == nil && rule != nil {
			if downloaderID == "" {
				downloaderID = strings.TrimSpace(rule.DownloaderID)
			}
			paused = rule.AutoPause
			if ruleTags := parseJSONStrings(rule.TagsJSON); len(ruleTags) > 0 {
				tags = ruleTags
			}
		} else if err != nil {
			logx.Warnf(moduleAutoSeed, "读取自动发种规则失败 item_id=%d rule_id=%d err=%v", item.ID, item.RuleID, err)
		}
	}

	if strings.TrimSpace(downloaderID) == "" {
		return "", options, errors.New("未获取到下载器")
	}
	uploadLimit := 0
	if s != nil && s.repo != nil {
		uploadLimit = s.repo.GetSiteSpeedLimit(firstNonEmpty(item.SiteName, item.SourceSite))
	}
	return downloaderID, newAutoSeedAddTorrentOptions(paused, tags, uploadLimit), nil
}

// pushFetchedItemToDownloader 将已经抓取到详情页信息的自动发种记录推送到下载器。
// 参数/返回：item 为待推送记录，fetchResult 为详情抓取结果，downloader 为目标下载器。
// 失败场景：种子路径/URL 无法添加、下载器调用失败、写回推送状态失败。
// 副作用：会向下载器添加任务，并将记录标记为已推送。
func (s *Service) pushFetchedItemToDownloader(item *repository.AutoSeedItem, fetchResult map[string]any, downloader downloaderclient.Downloader, options downloaderclient.AddTorrentOptions) error {
	if s == nil || s.repo == nil || item == nil {
		return errors.New("自动发种仓储未初始化")
	}
	torrentPath := strings.TrimSpace(toString(fetchResult["torrent_path"], ""))
	var addErr error
	if torrentPath != "" {
		rewriteTorrentCommentIfNeeded(torrentPath, toString(fetchResult["detail_url"], ""))
		addErr = downloader.AddTorrentFileWithOptions(torrentPath, "", options)
	} else {
		addErr = downloader.AddTorrentURLWithOptions(item.TorrentURL, "", options)
	}
	if addErr != nil {
		return addErr
	}
	downloaderHash := firstNonEmpty(toString(fetchResult["hash"], ""), s.findDownloaderHash(downloader, item.Name))
	return s.repo.MarkItemPushed(item.ID, item.DownloaderID, downloaderHash, "")
}

// newAutoSeedAddTorrentOptions 构造自动发种推送到下载器时使用的附加参数。
// 参数/返回：paused 控制是否暂停加入，tags 为下载器标签，uploadLimitMBps 为上传限速(MB/s,0=不限)；返回可直接用于 AddTorrent 调用的参数。
// 失败场景：无。
// 副作用：无。
func newAutoSeedAddTorrentOptions(paused bool, tags []string, uploadLimitMBps int) downloaderclient.AddTorrentOptions {
	skipChecking := false
	return downloaderclient.AddTorrentOptions{
		Paused:          paused,
		Tags:            compactStrings(tags),
		UploadLimitMBps: uploadLimitMBps,
		SkipChecking:    &skipChecking,
	}
}
func (s *Service) OrganizeItem(id int64, patch map[string]any) error {
	item, err := s.repo.GetItem(id)
	if err != nil {
		return err
	}
	item.Name = toString(patch["name"], item.Name)
	item.ResourceType = toString(patch["resource_type"], item.ResourceType)
	item.Medium = toString(patch["medium"], item.Medium)
	item.TorrentID = toString(patch["torrent_id"], item.TorrentID)
	item.SiteName = toString(patch["site_name"], item.SiteName)
	if tags, ok := patch["tags"].([]any); ok {
		item.TagsJSON = encodeStrings(anySliceToStrings(tags))
	}
	if strings.TrimSpace(item.TorrentID) != "" {
		row, err := s.repo.GetSeedParameter(item.TorrentID, firstNonEmpty(item.SiteName, item.SourceSite))
		if err != nil {
			logx.Warnf(moduleAutoSeed, "同步整理后的种子参数失败 item_id=%d torrent_id=%s site=%s err=%v", item.ID, item.TorrentID, firstNonEmpty(item.SiteName, item.SourceSite), err)
		} else {
			applySeedParameterRow(item, row)
		}
	}
	nowText := time.Now().Format(repository.PublishQueueTimeLayout)
	item.OrganizedAt = &nowText
	item.Status = repository.AutoSeedItemStatusOrganized
	return s.repo.UpdateItemBasics(item)
}

// PublishItems 将自动发种记录投递到已有发布队列。
func (s *Service) PublishItems(ids []int64, targetSites []string) (map[string]any, error) {
	if s == nil || s.enqueueFn == nil {
		return nil, errors.New("发布队列未初始化")
	}
	targetSites = compactStrings(targetSites)
	if len(ids) == 0 {
		return nil, errors.New("请选择要发布的种子")
	}
	if len(targetSites) == 0 {
		return nil, errors.New("请选择发布站点")
	}
	results := make([]map[string]any, 0, len(ids)*len(targetSites))
	queuedItems := 0
	for _, id := range ids {
		item, err := s.repo.GetItem(id)
		if err != nil {
			results = append(results, map[string]any{"id": id, "success": false, "message": err.Error()})
			continue
		}
		torrentID := strings.TrimSpace(item.TorrentID)
		if torrentID == "" {
			torrentID = inferTorrentID(*item)
		}
		siteName := strings.TrimSpace(firstNonEmpty(item.SiteName, item.SourceSite))
		if torrentID == "" || siteName == "" {
			results = append(results, map[string]any{"id": id, "success": false, "message": "缺少 torrent_id 或源站"})
			continue
		}
		currentSavePath := s.resolveItemSavePath(item)
		interval, concurrency := s.resolveDownloaderPublishSettings(item.DownloaderID)
		downloadURL := s.resolveItemDownloadURL(item)
		now := time.Now()
		itemResults := make([]map[string]any, 0, len(targetSites))
		queuedTargets := 0
		failedTargets := make([]string, 0, len(targetSites))
		for idx, target := range targetSites {
			seed := map[string]any{
				"torrent_id":    torrentID,
				"site_name":     siteName,
				"nickname":      item.SourceSite,
				"downloader_id": item.DownloaderID,
			}
			if downloadURL != "" {
				seed["torrent_url"] = downloadURL
			}
			if currentSavePath != "" {
				seed["save_path"] = currentSavePath
			}
			payload := map[string]any{
				"target_site_name": target,
				"publish_scene":    "auto_seed",
				"publish_trigger":  fmt.Sprintf("auto:%d", id),
				"seeds":            []any{seed},
			}
			wave := idx / concurrency
			if wave > 0 && interval > 0 {
				payload["scheduled_at"] = now.Add(time.Duration(wave) * interval).Format(repository.PublishQueueTimeLayout)
			}
			result, code := s.enqueueFn(payload)
			entry := map[string]any{"id": id, "target_site": target, "status": code, "result": result}
			results = append(results, entry)
			itemResults = append(itemResults, entry)
			if code < 400 && boolFromAny(result["success"]) {
				queuedTargets++
			} else {
				failedTargets = append(failedTargets, target+"："+toString(result["message"], fmt.Sprintf("入队失败（HTTP %d）", code)))
			}
		}
		encoded, _ := json.Marshal(mergeAutoSeedPublishResults(item.PublishResultsJSON, itemResults))
		if queuedTargets > 0 {
			queuedItems++
			// 发布成功后确保下载器 hash 已回写 DB，否则保种清理查不到记录
			s.ensureItemDownloaderInfo(item)
			// 标记源站 seed_parameters 为已整理，让种子列表"源站数据状态"显示为绿色
			if rows, err := s.repo.MarkSeedParameterReviewed(torrentID, siteName); err != nil {
				logx.Warnf(moduleAutoSeed, "标记种子已整理失败 item_id=%d torrent_id=%s site=%s err=%v", id, torrentID, siteName, err)
			} else if rows > 0 {
				logx.Infof(moduleAutoSeed, "已标记种子为已整理 item_id=%d torrent_id=%s site=%s", id, torrentID, siteName)
			}
			_ = s.repo.MarkItemPublished(id, string(encoded))
			continue
		}
		reason := "自动发种未入队"
		if len(failedTargets) > 0 {
			reason += "：" + strings.Join(failedTargets, "；")
		}
		_ = s.repo.UpdateItemPublishFeedback(id, string(encoded), reason)
	}
	if queuedItems == 0 {
		return map[string]any{"success": false, "results": results}, errors.New("所有目标站点均未加入发布队列")
	}
	return map[string]any{"success": true, "results": results}, nil
}

// DeleteItems 删除记录，并尝试同步删除下载器中的任务和文件。
func (s *Service) DeleteItems(ids []int64, deleteFiles bool) (int64, error) {
	root := s.rootConfig()
	for _, id := range ids {
		item, err := s.repo.GetItem(id)
		if err != nil || strings.TrimSpace(item.DownloaderID) == "" || strings.TrimSpace(item.DownloaderHash) == "" {
			continue
		}
		d, err := downloaderclient.FromConfig(root, item.DownloaderID)
		if err != nil {
			continue
		}
		if err := d.DeleteTorrents([]string{item.DownloaderHash}, deleteFiles); err != nil {
			logx.Warnf(moduleAutoSeed, "删除下载器任务失败 item_id=%d err=%v", id, err)
		}
	}
	return s.repo.DeleteItems(ids)
}

// cleanupExpiredRetainedSeeds 清理超过规则保种时间的已发布种子，并同步删除下载器任务和文件。
// 参数/返回：无入参；失败仅记录日志，避免阻断自动发种主轮询。
// 失败场景：数据库查询失败、下载器连接失败或删除接口失败时记录告警并继续处理其他记录。
// 副作用：会请求下载器删除种子和文件，并删除对应 auto_seed_items 记录。
func (s *Service) cleanupExpiredRetainedSeeds() {
	if s == nil || s.repo == nil {
		return
	}
	candidates, err := s.repo.ListRetentionCandidates(500)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "查询保种到期记录失败 err=%v", err)
		return
	}
	if len(candidates) == 0 {
		return
	}

	items := make([]repository.AutoSeedItem, 0, len(candidates))
	for _, candidate := range candidates {
		items = append(items, candidate.AutoSeedItem)
	}
	latestByTorrent := map[string]time.Time{}
	logs, err := s.repo.FindPublishLogsForItems(items)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "查询保种发布时间失败 err=%v", err)
	} else {
		for _, entry := range logs {
			torrentID := strings.TrimSpace(entry.TorrentID)
			if torrentID == "" {
				continue
			}
			if value, ok := parseAutoSeedStoredTime(firstNonEmpty(entry.UpdatedAt, entry.CreatedAt)); ok {
				if current, exists := latestByTorrent[torrentID]; !exists || value.After(current) {
					latestByTorrent[torrentID] = value
				}
			}
		}
	}

	now := time.Now()
	cleaned := 0
	skipped := 0
	for _, candidate := range candidates {
		retention := candidate.SeedRetentionMinutes
		if retention <= 0 {
			continue
		}
		lastPublishedAt, ok := latestAutoSeedPublishTime(candidate, latestByTorrent)
		if !ok {
			// 找不到发布时间时回退到 updated_at，避免永久跳过导致种子永不清理
			if value, parsed := parseAutoSeedStoredTime(candidate.UpdatedAt); parsed {
				lastPublishedAt = value
				ok = true
			}
		}
		if !ok || now.Sub(lastPublishedAt) < time.Duration(retention)*time.Minute {
			skipped++
			continue
		}
		// 保种清理：先删下载器任务和文件，成功后再删 DB 记录；
		// 下载器删除失败时不删 DB，下一轮重试，避免"DB 删了但文件还在"。
		deleted, err := s.deleteRetainedSeed(candidate.AutoSeedItem)
		if err != nil {
			logx.Warnf(moduleAutoSeed, "保种到期清理失败(下载器未删除,下轮重试) item_id=%d rule_id=%d retention_minutes=%d err=%v", candidate.ID, candidate.RuleID, retention, err)
			continue
		}
		if deleted > 0 {
			cleaned += int(deleted)
			logx.Infof(moduleAutoSeed, "保种到期已删除种子和文件 item_id=%d rule_id=%d retention_minutes=%d last_publish_at=%s", candidate.ID, candidate.RuleID, retention, lastPublishedAt.Format(repository.PublishQueueTimeLayout))
		}
	}
	if cleaned > 0 || skipped > 0 {
		logx.Infof(moduleAutoSeed, "保种到期清理完成 deleted=%d skipped=%d", cleaned, skipped)
	}
}

// deleteRetainedSeed 删除保种到期的种子：先删下载器任务和文件，成功后再删 DB 记录。
// 下载器删除失败时返回 error，不删 DB 记录，由调用方决定下一轮重试。
// hash 为空时先尝试从下载器按 name 匹配补全，补全失败则直接删 DB（下载器里可能已无此任务）。
func (s *Service) deleteRetainedSeed(item repository.AutoSeedItem) (int64, error) {
	if s == nil || s.repo == nil {
		return 0, errors.New("service is nil")
	}
	downloaderID := strings.TrimSpace(item.DownloaderID)
	downloaderHash := strings.TrimSpace(item.DownloaderHash)
	if downloaderID == "" {
		// 无下载器信息，直接删 DB 记录
		return s.repo.DeleteItems([]int64{item.ID})
	}
	// hash 为空时先尝试从下载器按 name 匹配补全
	if downloaderHash == "" {
		root := s.rootConfig()
		if d, err := downloaderclient.FromConfig(root, downloaderID); err == nil {
			downloaderHash = s.findDownloaderHash(d, firstNonEmpty(item.Name, item.Subtitle))
		}
		if downloaderHash != "" {
			_ = s.repo.UpdateItemDownloaderHash(item.ID, downloaderID, downloaderHash)
		} else {
			// 仍无法获取 hash，直接删 DB 记录（下载器里可能已无此任务）
			logx.Warnf(moduleAutoSeed, "保种清理 hash 为空且无法补全，仅删 DB 记录 item_id=%d downloader_id=%s", item.ID, downloaderID)
			return s.repo.DeleteItems([]int64{item.ID})
		}
	}
	root := s.rootConfig()
	d, err := downloaderclient.FromConfig(root, downloaderID)
	if err != nil {
		return 0, fmt.Errorf("下载器配置读取失败: %w", err)
	}
	if err := d.DeleteTorrents([]string{downloaderHash}, true); err != nil {
		return 0, fmt.Errorf("删除下载器任务失败: %w", err)
	}
	return s.repo.DeleteItems([]int64{item.ID})
}

// Progress 返回下载器进度页数据。
func (s *Service) Progress(downloaderID string) ([]repository.AutoSeedItem, error) {
	s.SyncProgressAndAutoPublish(downloaderID)
	rows, err := s.repo.ListProgressItems(downloaderID)
	if err != nil {
		return nil, err
	}
	s.enrichItemSeedParameters(rows)
	s.enrichItemSavePaths(rows)
	s.enrichItemPublishResults(rows)
	return rows, nil
}

func (s *Service) rootConfig() map[string]any {
	if s == nil || s.cfg == nil {
		return map[string]any{}
	}
	return s.cfg.Get()
}

func (s *Service) buildItemFromEntry(rule *repository.AutoSeedRule, entry feedEntry) *repository.AutoSeedItem {
	resourceType, medium := classifyEntry(entry)
	torrentURL := firstNonEmpty(entry.EnclosureURL, entry.Link)
	return &repository.AutoSeedItem{
		RuleID:       rule.ID,
		SourceSite:   rule.SourceSite,
		GUID:         firstNonEmpty(entry.GUID, stableID(torrentURL+entry.Title)),
		TorrentURL:   torrentURL,
		DetailURL:    firstNonEmpty(entry.Link, torrentURL),
		Name:         entry.Title,
		SizeBytes:    entry.SizeBytes,
		ResourceType: resourceType,
		Medium:       medium,
		TagsJSON:     encodeStrings(entry.Categories),
		Status:       repository.AutoSeedItemStatusPending,
		DownloaderID: rule.DownloaderID,
		SiteName:     rule.SourceSite,
		TorrentID:    inferTorrentIDFromURL(firstNonEmpty(entry.Link, torrentURL)),
	}
}

// fetchItemDetails 抓取源站详情并回填自动发种记录，确保推送下载器前已取得源站标签。
// 参数/返回：item 为已写入数据库的自动发种记录；成功返回抓取结果，失败返回可直接展示的未推送原因。
// 失败场景：详情抓取函数未注入、缺少源站定位信息或抓取接口返回失败。
// 副作用：会发起源站请求，并更新自动发种记录及对应的种子参数。
func (s *Service) fetchItemDetails(item *repository.AutoSeedItem) (map[string]any, string) {
	if s == nil || s.fetchFn == nil {
		return nil, "未获取到源站标签，不允许下载"
	}
	if item == nil {
		return nil, "RSS 数据为空"
	}
	searchTerm := firstNonEmpty(item.TorrentID, item.DetailURL, item.TorrentURL)
	if strings.TrimSpace(item.SourceSite) == "" || strings.TrimSpace(searchTerm) == "" {
		return nil, "未获取到源站详情，不允许下载"
	}
	result, status := s.fetchFn(map[string]any{
		"sourceSite":           item.SourceSite,
		"searchTerm":           searchTerm,
		"torrentName":          item.Name,
		"downloaderId":         item.DownloaderID,
		"savePath":             "",
		"screenshotReviewMode": "background",
		"task_id":              fmt.Sprintf("auto-seed-%d", item.ID),
	})
	if status >= 400 || !boolFromAny(result["success"]) {
		return result, "详情页数据抓取失败: " + toString(result["message"], "未知错误")
	}
	s.applyFetchedDetails(item, result)
	return result, ""
}

func (s *Service) findDownloaderHash(d downloaderclient.Downloader, title string) string {
	snapshots, err := d.FetchTorrents()
	if err != nil {
		return ""
	}
	if snapshot, ok := matchSnapshot(repository.AutoSeedItem{Name: title}, snapshots); ok {
		return snapshot.Hash
	}
	return ""
}

// ensureItemDownloaderInfo 发布成功后确保下载器信息（hash）已回写 DB。
// 推送下载器时可能未拿到 hash（findDownloaderHash 未匹配到），导致 DB 里 downloader_hash 为空，
// 保种清理的 ListRetentionCandidates 查询条件 downloader_hash <> '' 会过滤掉这些记录。
// 此方法在发布成功后补全：先从 seed_parameters 查 hash，再从下载器按 name 匹配查 hash，回写 DB。
func (s *Service) ensureItemDownloaderInfo(item *repository.AutoSeedItem) {
	if s == nil || s.repo == nil || item == nil {
		return
	}
	downloaderID := strings.TrimSpace(item.DownloaderID)
	downloaderHash := strings.TrimSpace(item.DownloaderHash)
	if downloaderID != "" && downloaderHash != "" {
		return
	}
	// 优先从 seed_parameters 查 hash
	if downloaderHash == "" {
		downloaderHash = s.findItemInfoHash(*item)
	}
	// 再从下载器按 name 匹配查 hash
	if downloaderHash == "" && downloaderID != "" {
		root := s.rootConfig()
		if d, err := downloaderclient.FromConfig(root, downloaderID); err == nil {
			downloaderHash = s.findDownloaderHash(d, firstNonEmpty(item.Name, item.Subtitle))
		}
	}
	if downloaderID != "" || downloaderHash != "" {
		if err := s.repo.UpdateItemDownloaderHash(item.ID, downloaderID, downloaderHash); err != nil {
			logx.Warnf(moduleAutoSeed, "回填下载器 hash 失败 item_id=%d err=%v", item.ID, err)
		} else {
			logx.Infof(moduleAutoSeed, "回填下载器 hash 成功 item_id=%d downloader_id=%s hash=%s", item.ID, downloaderID, downloaderHash)
		}
	}
}

func (s *Service) resolveItemCurrentSavePath(item repository.AutoSeedItem) string {
	record, ok, err := s.resolveItemCurrentTorrentRecord(item)
	if err != nil || !ok {
		return ""
	}
	return strings.TrimSpace(record.SavePath)
}

// resolveItemSavePath 解析自动发种记录发布时使用的保存路径。
// 优先使用规则配置的 save_path，留空则回退到下载器中种子的实际保存路径。
func (s *Service) resolveItemSavePath(item *repository.AutoSeedItem) string {
	if item == nil {
		return s.resolveItemCurrentSavePath(repository.AutoSeedItem{})
	}
	if item.RuleID > 0 && s != nil && s.repo != nil {
		if rule, err := s.repo.GetRule(item.RuleID); err == nil && rule != nil {
			if path := strings.TrimSpace(rule.SavePath); path != "" {
				return path
			}
		}
	}
	return s.resolveItemCurrentSavePath(*item)
}

// resolveItemDownloadURL 解析自动发种记录发布时使用的种子下载地址。
// 优先使用规则配置的 download_url，其次使用 RSS 拉取时保存的 torrent_url。
func (s *Service) resolveItemDownloadURL(item *repository.AutoSeedItem) string {
	if item == nil {
		return ""
	}
	if item.RuleID > 0 && s != nil && s.repo != nil {
		if rule, err := s.repo.GetRule(item.RuleID); err == nil && rule != nil {
			if url := strings.TrimSpace(rule.DownloadURL); url != "" {
				return url
			}
		}
	}
	return strings.TrimSpace(item.TorrentURL)
}

func (s *Service) resolveItemCurrentTorrentRecord(item repository.AutoSeedItem) (repository.AutoSeedTorrentRecord, bool, error) {
	downloaderID := strings.TrimSpace(item.DownloaderID)
	downloaderHash := strings.TrimSpace(item.DownloaderHash)
	if s == nil || downloaderID == "" || downloaderHash == "" {
		return repository.AutoSeedTorrentRecord{}, false, nil
	}
	if s.repo != nil {
		record, err := s.repo.FindTorrentByDownloaderHash(downloaderID, downloaderHash)
		if err == nil {
			record.Hash = firstNonEmpty(record.Hash, downloaderHash)
			return record, true, nil
		}
		if !errors.Is(err, gorm.ErrRecordNotFound) {
			logx.Warnf(moduleAutoSeed, "发布前按 hash 查询 torrents 路径失败 downloader_id=%s hash=%s err=%v", downloaderID, downloaderHash, err)
			return repository.AutoSeedTorrentRecord{}, false, err
		}
	}
	downloader, err := downloaderclient.FromConfig(s.rootConfig(), downloaderID)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "发布前回填下载器任务失败 downloader_id=%s hash=%s err=%v", downloaderID, downloaderHash, err)
		return repository.AutoSeedTorrentRecord{}, false, err
	}
	snapshots, err := downloader.FetchTorrents()
	if err != nil {
		logx.Warnf(moduleAutoSeed, "发布前拉取下载器任务失败 downloader_id=%s hash=%s err=%v", downloaderID, downloaderHash, err)
		return repository.AutoSeedTorrentRecord{}, false, err
	}
	snapshot, ok := matchSnapshotByHash(downloaderHash, snapshots)
	if !ok {
		return repository.AutoSeedTorrentRecord{}, false, nil
	}
	return repository.AutoSeedTorrentRecord{
		Hash:         strings.TrimSpace(snapshot.Hash),
		Name:         strings.TrimSpace(snapshot.Name),
		SavePath:     bestSnapshotMediaPath(snapshot),
		Progress:     snapshot.Progress,
		DownloaderID: downloaderID,
	}, true, nil
}

func (s *Service) applyFetchedDetails(item *repository.AutoSeedItem, fetchResult map[string]any) {
	if s == nil || s.repo == nil || item == nil {
		return
	}
	torrentID := firstNonEmpty(toString(fetchResult["torrent_id"], ""), item.TorrentID)
	siteName := firstNonEmpty(toString(fetchResult["nickname"], ""), toString(fetchResult["site_name"], ""), item.SiteName, item.SourceSite)
	row, err := s.repo.GetSeedParameter(torrentID, siteName)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "查询抓取种子参数失败 item_id=%d torrent_id=%s site=%s err=%v", item.ID, torrentID, siteName, err)
	}

	item.TorrentID = torrentID
	item.SiteName = siteName
	item.DetailURL = firstNonEmpty(toString(fetchResult["detail_url"], ""), item.DetailURL)
	item.Name = firstNonEmpty(toString(row["title"], ""), toString(row["name"], ""), toString(fetchResult["name"], ""), item.Name)
	item.Subtitle = firstNonEmpty(toString(row["subtitle"], ""), item.Subtitle)
	item.ResourceType = firstNonEmpty(toString(row["type"], ""), item.ResourceType)
	item.Medium = firstNonEmpty(toString(row["medium"], ""), item.Medium)
	if size := toInt64(fetchResult["size_bytes"], 0); size > 0 {
		item.SizeBytes = size
	}
	if tags := parseStringArrayAny(row["tags"]); len(tags) > 0 {
		item.TagsJSON = encodeStrings(tags)
	}
	if strings.TrimSpace(item.TagsJSON) == "" {
		item.TagsJSON = encodeStrings([]string{"PT Nexus", "自动发种"})
	}
	if err := s.repo.UpdateItemFetchedDetails(item); err != nil {
		logx.Warnf(moduleAutoSeed, "回填自动发种详情失败 item_id=%d err=%v", item.ID, err)
	}
}

func applySeedParameterRow(item *repository.AutoSeedItem, row map[string]any) {
	if item == nil || len(row) == 0 {
		return
	}
	item.TorrentID = firstNonEmpty(toString(row["torrent_id"], ""), item.TorrentID)
	item.SiteName = firstNonEmpty(toString(row["site_name"], ""), item.SiteName)
	item.Name = firstNonEmpty(toString(row["title"], ""), toString(row["name"], ""), item.Name)
	item.Subtitle = firstNonEmpty(toString(row["subtitle"], ""), item.Subtitle)
	item.ResourceType = firstNonEmpty(toString(row["type"], ""), item.ResourceType)
	item.Medium = firstNonEmpty(toString(row["medium"], ""), item.Medium)
	if tags := parseStringArrayAny(row["tags"]); len(tags) > 0 {
		item.TagsJSON = encodeStrings(tags)
	}
}

// resolveDownloaderPublishSettings 从下载器配置读取自动发种发布间隔和并发数。
func (s *Service) resolveDownloaderPublishSettings(downloaderID string) (time.Duration, int) {
	concurrency := 1
	if s == nil || s.cfg == nil {
		return 0, concurrency
	}
	root := s.cfg.Get()
	for _, raw := range toSlice(root["downloaders"]) {
		item := toMap(raw)
		if strings.TrimSpace(toString(item["id"], "")) != strings.TrimSpace(downloaderID) {
			continue
		}
		minutes := toInt(item["publish_interval_minutes"], 0)
		if value := toInt(item["publish_concurrency"], 1); value > 0 {
			concurrency = value
		}
		if minutes <= 0 {
			return 0, concurrency
		}
		return time.Duration(minutes) * time.Minute, concurrency
	}
	return 0, concurrency
}

type feedEntry struct {
	Title        string
	Link         string
	GUID         string
	EnclosureURL string
	SizeBytes    int64
	Categories   []string
}

type rssDocument struct {
	Channel struct {
		Items []rssItem `xml:"item"`
	} `xml:"channel"`
	Entries []atomEntry `xml:"entry"`
}

type rssItem struct {
	Title     string `xml:"title"`
	Link      string `xml:"link"`
	GUID      string `xml:"guid"`
	Enclosure struct {
		URL    string `xml:"url,attr"`
		Length string `xml:"length,attr"`
	} `xml:"enclosure"`
	Categories []string `xml:"category"`
}

type atomEntry struct {
	Title string `xml:"title"`
	ID    string `xml:"id"`
	Links []struct {
		Href   string `xml:"href,attr"`
		Rel    string `xml:"rel,attr"`
		Length string `xml:"length,attr"`
	} `xml:"link"`
	Categories []struct {
		Term string `xml:"term,attr"`
	} `xml:"category"`
}

func fetchRSS(rssURL string) ([]feedEntry, error) {
	rssURL = strings.TrimSpace(rssURL)
	if rssURL == "" {
		return nil, errors.New("RSS 地址不能为空")
	}
	client := &http.Client{Timeout: 45 * time.Second}
	req, err := http.NewRequest(http.MethodGet, rssURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "PT Nexus AutoSeed")
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 8*1024*1024))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("HTTP %d %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	doc := rssDocument{}
	if err := xml.Unmarshal(body, &doc); err != nil {
		return nil, fmt.Errorf("RSS 解析失败: %w", err)
	}
	result := make([]feedEntry, 0, len(doc.Channel.Items)+len(doc.Entries))
	for _, item := range doc.Channel.Items {
		result = append(result, feedEntry{
			Title:        strings.TrimSpace(item.Title),
			Link:         strings.TrimSpace(item.Link),
			GUID:         strings.TrimSpace(item.GUID),
			EnclosureURL: strings.TrimSpace(item.Enclosure.URL),
			SizeBytes:    parseInt64(item.Enclosure.Length),
			Categories:   item.Categories,
		})
	}
	for _, entry := range doc.Entries {
		feed := feedEntry{Title: strings.TrimSpace(entry.Title), GUID: strings.TrimSpace(entry.ID)}
		for _, link := range entry.Links {
			if feed.Link == "" || strings.EqualFold(link.Rel, "alternate") {
				feed.Link = strings.TrimSpace(link.Href)
			}
			if strings.EqualFold(link.Rel, "enclosure") {
				feed.EnclosureURL = strings.TrimSpace(link.Href)
				feed.SizeBytes = parseInt64(link.Length)
			}
		}
		for _, category := range entry.Categories {
			feed.Categories = append(feed.Categories, category.Term)
		}
		result = append(result, feed)
	}
	return result, nil
}

func rejectReason(rule *repository.AutoSeedRule, item *repository.AutoSeedItem) string {
	if item == nil {
		return "RSS 数据为空"
	}
	if strings.TrimSpace(item.TorrentURL) == "" {
		return "未获取到种子地址"
	}
	if reason := restrictedTagRejectReason(item); reason != "" {
		return reason
	}
	if rule == nil {
		return ""
	}
	sizeGB := float64(item.SizeBytes) / 1024 / 1024 / 1024
	if rule.MinSizeGB > 0 && item.SizeBytes > 0 && sizeGB < rule.MinSizeGB {
		return "因大小限制"
	}
	if rule.MaxSizeGB > 0 && item.SizeBytes > 0 && sizeGB > rule.MaxSizeGB {
		return "因大小限制"
	}
	return ""
}

func restrictedTagRejectReason(item *repository.AutoSeedItem) string {
	if item == nil {
		return ""
	}
	for _, rawTag := range parseJSONStrings(item.TagsJSON) {
		tag := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(rawTag), "tag."))
		for _, restricted := range []string{"分集", "禁转", "限转"} {
			if strings.Contains(tag, restricted) {
				return fmt.Sprintf("因%s标签不允许下载", restricted)
			}
		}
	}
	if autoSeedEpisodePattern.MatchString(item.Name) {
		return "因分集标签不允许下载"
	}
	return ""
}

// shouldRetryAutoSeedItem 判断已存在的 RSS 记录是否应在下一轮重新尝试推送。
// 参数/返回：item 为数据库中的现有记录；返回 true 表示允许重新抓取详情并添加到下载器。
// 失败场景：空记录或已推送、已整理、已发布记录不会重试。
// 副作用：无，仅根据记录状态和失败原因做判断。
func shouldRetryAutoSeedItem(item *repository.AutoSeedItem) bool {
	if item == nil {
		return false
	}
	switch strings.TrimSpace(item.Status) {
	case repository.AutoSeedItemStatusPending:
		return true
	case repository.AutoSeedItemStatusRejected:
		return isRetryableAutoSeedRejectReason(item.RejectReason)
	default:
		return false
	}
}

// isRetryableAutoSeedRejectReason 判断失败原因是否属于可通过修复配置后恢复的错误。
// 参数/返回：reason 为自动发种记录的失败原因；返回 true 表示下一轮 RSS 可以重新处理。
// 失败场景：空原因或明确的规则过滤原因不允许重试。
// 副作用：无。
func isRetryableAutoSeedRejectReason(reason string) bool {
	reason = strings.TrimSpace(reason)
	if reason == "" {
		return false
	}
	for _, marker := range []string{
		"详情页数据抓取失败",
		"推送下载器失败",
		"未获取到源站标签",
		"未获取到源站详情",
		"未获取到下载器",
	} {
		if strings.Contains(reason, marker) {
			return true
		}
	}
	return false
}

func classifyEntry(entry feedEntry) (string, string) {
	text := strings.ToLower(entry.Title + " " + strings.Join(entry.Categories, " "))
	resourceType := "电影"
	if strings.Contains(text, "season") || strings.Contains(text, "episode") || strings.Contains(text, "s0") || strings.Contains(text, "剧") || strings.Contains(text, "tv") {
		resourceType = "电视剧"
	}
	medium := ""
	for _, candidate := range []string{"Blu-ray", "Remux", "WEB-DL", "WEBRip", "HDTV", "DVD", "UHD"} {
		if strings.Contains(strings.ToLower(text), strings.ToLower(candidate)) {
			medium = candidate
			break
		}
	}
	return resourceType, medium
}

func matchSnapshot(item repository.AutoSeedItem, snapshots []downloaderclient.TorrentSnapshot) (downloaderclient.TorrentSnapshot, bool) {
	hash := strings.ToLower(strings.TrimSpace(item.DownloaderHash))
	for _, snapshot := range snapshots {
		if hash != "" && strings.EqualFold(snapshot.Hash, hash) {
			return snapshot, true
		}
	}
	name := strings.TrimSpace(item.Name)
	for _, snapshot := range snapshots {
		if name != "" && strings.TrimSpace(snapshot.Name) == name {
			return snapshot, true
		}
	}
	normalizedName := normalizeTorrentName(name)
	if normalizedName == "" {
		return downloaderclient.TorrentSnapshot{}, false
	}
	var matched downloaderclient.TorrentSnapshot
	matchedCount := 0
	for _, snapshot := range snapshots {
		if normalizeTorrentName(snapshot.Name) != normalizedName {
			continue
		}
		matched = snapshot
		matchedCount++
	}
	if matchedCount == 1 {
		return matched, true
	}
	return downloaderclient.TorrentSnapshot{}, false
}

func matchSnapshotByHash(hash string, snapshots []downloaderclient.TorrentSnapshot) (downloaderclient.TorrentSnapshot, bool) {
	hash = strings.TrimSpace(hash)
	if hash == "" {
		return downloaderclient.TorrentSnapshot{}, false
	}
	for _, snapshot := range snapshots {
		if strings.EqualFold(strings.TrimSpace(snapshot.Hash), hash) {
			return snapshot, true
		}
	}
	return downloaderclient.TorrentSnapshot{}, false
}

func normalizeTorrentName(value string) string {
	value = strings.TrimSuffix(strings.TrimSpace(value), ".torrent")
	for strings.HasPrefix(value, "[") {
		end := strings.Index(value, "]")
		if end <= 0 {
			break
		}
		value = strings.TrimSpace(value[end+1:])
	}
	var builder strings.Builder
	for _, char := range strings.ToLower(value) {
		if unicode.IsLetter(char) || unicode.IsDigit(char) {
			builder.WriteRune(char)
		}
	}
	return builder.String()
}

// enrichItemSeedParameters 从整理后的种子参数表回填自动发种列表展示字段。
func (s *Service) enrichItemSeedParameters(items []repository.AutoSeedItem) {
	if s == nil || s.repo == nil || len(items) == 0 {
		return
	}
	for idx := range items {
		torrentID := strings.TrimSpace(items[idx].TorrentID)
		if torrentID == "" {
			torrentID = inferTorrentID(items[idx])
		}
		siteName := firstNonEmpty(items[idx].SiteName, items[idx].SourceSite)
		if torrentID == "" || siteName == "" {
			continue
		}
		row, err := s.repo.GetSeedParameter(torrentID, siteName)
		if err != nil {
			logx.Warnf(moduleAutoSeed, "回填整理后的种子参数失败 item_id=%d torrent_id=%s site=%s err=%v", items[idx].ID, torrentID, siteName, err)
			continue
		}
		applySeedParameterRow(&items[idx], row)
	}
}

func (s *Service) enrichItemSavePaths(items []repository.AutoSeedItem) {
	if s == nil || len(items) == 0 {
		return
	}
	if s.repo != nil {
		// 按下载器分组缓存快照，避免同一下载器重复拉取。
		snapshotCache := map[string][]downloaderclient.TorrentSnapshot{}
		for idx := range items {
			downloaderID := strings.TrimSpace(items[idx].DownloaderID)
			downloaderHash := strings.TrimSpace(items[idx].DownloaderHash)
			if downloaderID == "" || downloaderHash == "" {
				continue
			}
			record, err := s.repo.FindTorrentByDownloaderHash(downloaderID, downloaderHash)
			if err == nil {
				if strings.TrimSpace(record.SavePath) != "" {
					items[idx].SavePath = strings.TrimSpace(record.SavePath)
				}
				continue
			}
			if !errors.Is(err, gorm.ErrRecordNotFound) {
				logx.Warnf(moduleAutoSeed, "回填自动发种列表保存路径失败 downloader_id=%s hash=%s err=%v", downloaderID, downloaderHash, err)
				continue
			}
			// torrents 表无记录，回退查下载器任务列表，确认种子是否已被删除。
			snapshots, ok := snapshotCache[downloaderID]
			if !ok {
				downloader, dErr := downloaderclient.FromConfig(s.rootConfig(), downloaderID)
				if dErr != nil {
					continue
				}
				fetched, fErr := downloader.FetchTorrents()
				if fErr != nil {
					logx.Warnf(moduleAutoSeed, "回填下载器保存路径失败 downloader_id=%s err=%v", downloaderID, fErr)
					snapshotCache[downloaderID] = []downloaderclient.TorrentSnapshot{}
				} else {
					snapshotCache[downloaderID] = fetched
					snapshots = fetched
				}
			}
			matched := false
			if len(snapshots) > 0 {
				if snapshot, found := matchSnapshotByHash(downloaderHash, snapshots); found {
					items[idx].SavePath = bestSnapshotMediaPath(snapshot)
					matched = true
				}
			}
			// torrents 表与下载器任务列表均无此种子，标记为已从下载器删除。
			if !matched {
				items[idx].DeletedFromDownloader = true
			}
		}
		return
	}
	root := s.rootConfig()
	byDownloader := map[string][]int{}
	for idx := range items {
		downloaderID := strings.TrimSpace(items[idx].DownloaderID)
		if downloaderID == "" {
			continue
		}
		byDownloader[downloaderID] = append(byDownloader[downloaderID], idx)
	}
	for downloaderID, indexes := range byDownloader {
		downloader, err := downloaderclient.FromConfig(root, downloaderID)
		if err != nil {
			continue
		}
		snapshots, err := downloader.FetchTorrents()
		if err != nil {
			logx.Warnf(moduleAutoSeed, "回填下载器保存路径失败 downloader_id=%s err=%v", downloaderID, err)
			continue
		}
		for _, idx := range indexes {
			if snapshot, ok := matchSnapshotByHash(items[idx].DownloaderHash, snapshots); ok {
				items[idx].SavePath = bestSnapshotMediaPath(snapshot)
			} else if strings.TrimSpace(items[idx].DownloaderHash) != "" {
				// 下载器任务列表中无此 hash 的种子，标记为已删除。
				items[idx].DeletedFromDownloader = true
			}
		}
	}
}

func (s *Service) enrichItemPublishResults(items []repository.AutoSeedItem) {
	if s == nil || s.repo == nil || len(items) == 0 {
		return
	}
	logs, err := s.repo.FindPublishLogsForItems(items)
	if err != nil {
		logx.Warnf(moduleAutoSeed, "回填发布结果失败 err=%v", err)
		return
	}
	logsByTorrent := map[string][]repository.PublishLogEntry{}
	for _, entry := range logs {
		torrentID := strings.TrimSpace(entry.TorrentID)
		if torrentID == "" {
			continue
		}
		logsByTorrent[torrentID] = append(logsByTorrent[torrentID], entry)
	}
	for idx := range items {
		torrentID := strings.TrimSpace(items[idx].TorrentID)
		if torrentID == "" {
			continue
		}
		latestBySite := make([]map[string]any, 0)
		seen := map[string]struct{}{}
		for _, entry := range logsByTorrent[torrentID] {
			targetSite := strings.TrimSpace(entry.TargetSite)
			targetKey := strings.ToLower(targetSite)
			if targetKey == "" {
				continue
			}
			if _, ok := seen[targetKey]; ok {
				continue
			}
			seen[targetKey] = struct{}{}
			latestBySite = append(latestBySite, autoSeedPublishResultFromLog(entry))
		}
		if len(latestBySite) == 0 {
			continue
		}
		encoded, _ := json.Marshal(mergeAutoSeedPublishResults(items[idx].PublishResultsJSON, latestBySite))
		merged := string(encoded)
		if merged != items[idx].PublishResultsJSON {
			if err := s.repo.UpdateItemPublishFeedback(items[idx].ID, merged, ""); err != nil {
				logx.Warnf(moduleAutoSeed, "更新自动发种发布结果失败 item_id=%d err=%v", items[idx].ID, err)
			}
		}
		items[idx].PublishResultsJSON = merged
	}
}

func bestSnapshotMediaPath(snapshot downloaderclient.TorrentSnapshot) string {
	if path := strings.TrimSpace(snapshot.ContentPath); path != "" {
		return path
	}
	return strings.TrimSpace(snapshot.SavePath)
}

func mergeAutoSeedPublishResults(existingJSON string, next []map[string]any) []map[string]any {
	merged := make([]map[string]any, 0)
	indexBySite := map[string]int{}
	for _, entry := range parseAutoSeedPublishResults(existingJSON) {
		site := autoSeedPublishResultSite(entry)
		if site == "" {
			continue
		}
		key := strings.ToLower(site)
		if _, exists := indexBySite[key]; exists {
			continue
		}
		indexBySite[key] = len(merged)
		merged = append(merged, entry)
	}
	for _, entry := range next {
		normalized := normalizeAutoSeedPublishResult(entry)
		site := autoSeedPublishResultSite(normalized)
		if site == "" {
			continue
		}
		key := strings.ToLower(site)
		if idx, exists := indexBySite[key]; exists {
			merged[idx] = normalized
			continue
		}
		indexBySite[key] = len(merged)
		merged = append(merged, normalized)
	}
	return merged
}

func parseAutoSeedPublishResults(value string) []map[string]any {
	value = strings.TrimSpace(value)
	if value == "" {
		return []map[string]any{}
	}
	raw := []map[string]any{}
	if err := json.Unmarshal([]byte(value), &raw); err == nil {
		return raw
	}
	items := []any{}
	if err := json.Unmarshal([]byte(value), &items); err != nil {
		return []map[string]any{}
	}
	result := make([]map[string]any, 0, len(items))
	for _, item := range items {
		if mapped, ok := item.(map[string]any); ok {
			result = append(result, mapped)
		}
	}
	return result
}

func normalizeAutoSeedPublishResult(entry map[string]any) map[string]any {
	if entry == nil {
		return map[string]any{}
	}
	if strings.TrimSpace(toString(entry["status_text"], "")) != "" || strings.TrimSpace(toString(entry["updated_at"], "")) != "" {
		return entry
	}
	result := toMap(entry["result"])
	statusText := strings.TrimSpace(toString(result["message"], "已入队"))
	success := boolFromAny(result["success"])
	if statusText == "" {
		if success {
			statusText = "已入队"
		} else {
			statusText = "发布失败"
		}
	}
	out := map[string]any{
		"target_site": autoSeedPublishResultSite(entry),
		"status":      toString(entry["status"], ""),
		"status_text": statusText,
		"result_url":  firstNonEmpty(toString(result["result_url"], ""), toString(result["url"], "")),
		"updated_at":  time.Now().Format(repository.PublishQueueTimeLayout),
	}
	return out
}

func autoSeedPublishResultFromLog(entry repository.PublishLogEntry) map[string]any {
	updatedAt := firstNonEmpty(entry.UpdatedAt, entry.CreatedAt)
	return map[string]any{
		"target_site":  strings.TrimSpace(entry.TargetSite),
		"status":       strings.TrimSpace(entry.Status),
		"status_text":  autoSeedPublishStatusText(entry.Status),
		"result_url":   strings.TrimSpace(entry.ResultURL),
		"updated_at":   updatedAt,
		"seeding_time": autoSeedElapsedText(updatedAt),
	}
}

func autoSeedPublishResultSite(entry map[string]any) string {
	result := toMap(entry["result"])
	return firstNonEmpty(
		toString(entry["target_site"], ""),
		toString(entry["targetSite"], ""),
		toString(result["target_site"], ""),
		toString(result["targetSite"], ""),
	)
}

func autoSeedPublishStatusText(status string) string {
	switch strings.TrimSpace(status) {
	case "success":
		return "发布成功"
	case "failed":
		return "发布失败"
	case "exists":
		return "已存在"
	case "edited":
		return "已更新"
	case "pre_check_limit":
		return "预检查限制"
	case "queued":
		return "等待发布"
	case "running":
		return "发布中"
	case "cancelled":
		return "已取消"
	default:
		return strings.TrimSpace(status)
	}
}

func autoSeedElapsedText(value string) string {
	start, ok := parseAutoSeedStoredTime(value)
	if !ok || start.IsZero() {
		return ""
	}
	elapsed := time.Since(start)
	if elapsed < 0 {
		elapsed = 0
	}
	days := int(elapsed.Hours()) / 24
	hours := int(elapsed.Hours()) % 24
	minutes := int(elapsed.Minutes()) % 60
	if days > 0 {
		if hours > 0 {
			return fmt.Sprintf("%d天%d小时", days, hours)
		}
		return fmt.Sprintf("%d天", days)
	}
	if hours > 0 {
		if minutes > 0 {
			return fmt.Sprintf("%d小时%d分钟", hours, minutes)
		}
		return fmt.Sprintf("%d小时", hours)
	}
	if minutes > 0 {
		return fmt.Sprintf("%d分钟", minutes)
	}
	return "刚刚"
}

func latestAutoSeedPublishTime(candidate repository.AutoSeedRetentionCandidate, latestByTorrent map[string]time.Time) (time.Time, bool) {
	item := candidate.AutoSeedItem
	if value, exists := parseAutoSeedStoredTime(candidate.LastPublishAt); exists {
		return value, true
	}
	torrentID := strings.TrimSpace(item.TorrentID)
	latest, ok := latestByTorrent[torrentID]
	if value, exists := latestAutoSeedPublishResultTime(item.PublishResultsJSON); exists && (!ok || value.After(latest)) {
		latest = value
		ok = true
	}
	if item.PublishedAt != nil {
		if value, exists := parseAutoSeedStoredTime(*item.PublishedAt); exists && (!ok || value.After(latest)) {
			latest = value
			ok = true
		}
	}
	return latest, ok
}

func latestAutoSeedPublishResultTime(resultsJSON string) (time.Time, bool) {
	var latest time.Time
	found := false
	for _, entry := range parseAutoSeedPublishResults(resultsJSON) {
		for _, key := range []string{"updated_at", "created_at", "published_at"} {
			value, ok := parseAutoSeedStoredTime(toString(entry[key], ""))
			if !ok {
				continue
			}
			if !found || value.After(latest) {
				latest = value
				found = true
			}
		}
	}
	return latest, found
}

func parseAutoSeedStoredTime(value string) (time.Time, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}, false
	}
	if parsed, err := time.ParseInLocation(repository.PublishQueueTimeLayout, value, time.Local); err == nil {
		return parsed, true
	}
	if parsed, err := time.Parse(time.RFC3339, value); err == nil {
		return parsed.Local(), true
	}
	return time.Time{}, false
}

func normalizeRule(rule *repository.AutoSeedRule) {
	if rule == nil {
		return
	}
	rule.Name = strings.TrimSpace(rule.Name)
	rule.SourceSite = strings.TrimSpace(rule.SourceSite)
	rule.RSSURL = strings.TrimSpace(rule.RSSURL)
	rule.DownloaderID = strings.TrimSpace(rule.DownloaderID)
	rule.TypesJSON = "[]"
	rule.MediaJSON = "[]"
	if rule.PullIntervalMinutes <= 0 {
		rule.PullIntervalMinutes = 30
	}
	if rule.PublishConcurrency <= 0 {
		rule.PublishConcurrency = 1
	}
	if rule.SeedRetentionMinutes < 0 {
		rule.SeedRetentionMinutes = 0
	}
	if strings.TrimSpace(rule.NextRunAt) == "" {
		rule.NextRunAt = time.Now().Format(repository.PublishQueueTimeLayout)
	}
}

func inferTorrentID(item repository.AutoSeedItem) string {
	return firstNonEmpty(item.TorrentID, inferTorrentIDFromURL(item.DetailURL), inferTorrentIDFromURL(item.TorrentURL), stableID(item.Name))
}

func inferTorrentIDFromURL(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	if _, err := strconv.ParseInt(value, 10, 64); err == nil {
		return value
	}
	for _, marker := range []string{"id=", "torrentid=", "torrent_id=", "/torrent/", "/dl/"} {
		idx := strings.LastIndex(strings.ToLower(value), marker)
		if idx < 0 {
			continue
		}
		raw := value[idx+len(marker):]
		for cut, ch := range raw {
			if (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || ch == '-' || ch == '_' {
				continue
			}
			return raw[:cut]
		}
		return raw
	}
	return ""
}

func stableID(value string) string {
	h := fnv.New64a()
	_, _ = h.Write([]byte(strings.TrimSpace(value)))
	return strconv.FormatUint(h.Sum64(), 16)
}

func parseJSONStrings(value string) []string {
	items := []string{}
	_ = json.Unmarshal([]byte(strings.TrimSpace(value)), &items)
	return compactStrings(items)
}

func encodeStrings(items []string) string {
	encoded, _ := json.Marshal(compactStrings(items))
	return string(encoded)
}

func compactStrings(items []string) []string {
	result := make([]string, 0, len(items))
	seen := map[string]struct{}{}
	for _, item := range items {
		trimmed := strings.TrimSpace(item)
		if trimmed == "" {
			continue
		}
		key := strings.ToLower(trimmed)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		result = append(result, trimmed)
	}
	return result
}

func anySliceToStrings(items []any) []string {
	result := make([]string, 0, len(items))
	for _, item := range items {
		result = append(result, toString(item, ""))
	}
	return result
}

func firstNonEmpty(items ...string) string {
	for _, item := range items {
		if strings.TrimSpace(item) != "" {
			return strings.TrimSpace(item)
		}
	}
	return ""
}

func parseInt64(value string) int64 {
	parsed, _ := strconv.ParseInt(strings.TrimSpace(value), 10, 64)
	return parsed
}

func clampInt(value, min, max int) int {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}

func toString(value any, fallback string) string {
	if value == nil {
		return fallback
	}
	if text, ok := value.(string); ok {
		if strings.TrimSpace(text) == "" {
			return fallback
		}
		return strings.TrimSpace(text)
	}
	text := strings.TrimSpace(fmt.Sprintf("%v", value))
	if text == "" || text == "<nil>" {
		return fallback
	}
	return text
}

func toInt(value any, fallback int) int {
	switch typed := value.(type) {
	case int:
		return typed
	case float64:
		return int(typed)
	case string:
		parsed, err := strconv.Atoi(strings.TrimSpace(typed))
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func toInt64(value any, fallback int64) int64 {
	switch typed := value.(type) {
	case int64:
		return typed
	case int:
		return int64(typed)
	case float64:
		return int64(typed)
	case json.Number:
		parsed, err := typed.Int64()
		if err == nil {
			return parsed
		}
	case string:
		parsed, err := strconv.ParseInt(strings.TrimSpace(typed), 10, 64)
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func toSlice(value any) []any {
	if typed, ok := value.([]any); ok {
		return typed
	}
	return []any{}
}

func toMap(value any) map[string]any {
	if typed, ok := value.(map[string]any); ok {
		return typed
	}
	return map[string]any{}
}

func boolFromAny(value any) bool {
	if typed, ok := value.(bool); ok {
		return typed
	}
	if text, ok := value.(string); ok {
		trimmed := strings.ToLower(strings.TrimSpace(text))
		return trimmed == "1" || trimmed == "true" || trimmed == "yes"
	}
	return false
}

func parseStringArrayAny(value any) []string {
	switch typed := value.(type) {
	case []string:
		return compactStrings(typed)
	case []any:
		return compactStrings(anySliceToStrings(typed))
	case []byte:
		return parseStringArrayAny(string(typed))
	case string:
		trimmed := strings.TrimSpace(typed)
		if trimmed == "" {
			return []string{}
		}
		parsed := []string{}
		if err := json.Unmarshal([]byte(trimmed), &parsed); err == nil {
			return compactStrings(parsed)
		}
		return compactStrings(strings.Split(trimmed, ","))
	default:
		return []string{}
	}
}

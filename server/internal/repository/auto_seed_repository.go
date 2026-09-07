package repository

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"gorm.io/gorm"
)

const (
	AutoSeedRuleStatusEnabled   = "enabled"
	AutoSeedRuleStatusPaused    = "paused"
	AutoSeedItemStatusPending   = "pending"
	AutoSeedItemStatusNotPushed = "not_pushed"
	AutoSeedItemStatusPushed    = "pushed"
	AutoSeedItemStatusOrganized = "organized"
	AutoSeedItemStatusPublished = "published"
	AutoSeedItemStatusRejected  = "rejected"
)

// AutoSeedRule 表示一条 RSS 自动发种规则，包含过滤条件、下载器和发布目标。
// 参数/返回：字段直接映射 auto_seed_rules 表，供仓储和接口复用。
// 失败场景：无直接失败场景。
// 副作用：无副作用，仅承载数据。
type AutoSeedRule struct {
	ID int64 `json:"id" gorm:"column:id;primaryKey"`

	Name         string `json:"name" gorm:"column:name"`
	Enabled      bool   `json:"enabled" gorm:"column:enabled"`
	PausedReason string `json:"paused_reason" gorm:"column:paused_reason"`

	SourceSite string `json:"source_site" gorm:"column:source_site"`
	RSSURL     string `json:"rss_url" gorm:"column:rss_url"`

	DownloaderID   string `json:"downloader_id" gorm:"column:downloader_id"`
	SavePath       string `json:"save_path" gorm:"column:save_path"`
	DownloadURL    string `json:"download_url" gorm:"column:download_url"`
	AutoPause      bool   `json:"auto_pause" gorm:"column:auto_pause"`
	AutoOrganize   bool   `json:"auto_organize" gorm:"column:auto_organize"`

	MinSizeGB       float64 `json:"min_size_gb" gorm:"column:min_size_gb"`
	MaxSizeGB       float64 `json:"max_size_gb" gorm:"column:max_size_gb"`
	TypesJSON       string  `json:"types_json" gorm:"column:types_json"`
	MediaJSON       string  `json:"media_json" gorm:"column:media_json"`
	TagsJSON        string  `json:"tags_json" gorm:"column:tags_json"`
	TargetSitesJSON string  `json:"target_sites_json" gorm:"column:target_sites_json"`

	PullIntervalMinutes    int     `json:"pull_interval_minutes" gorm:"column:pull_interval_minutes"`
	PublishIntervalMinutes int     `json:"publish_interval_minutes" gorm:"column:publish_interval_minutes"`
	PublishConcurrency     int     `json:"publish_concurrency" gorm:"column:publish_concurrency"`
	SeedRetentionMinutes   int     `json:"seed_retention_minutes" gorm:"column:seed_retention_minutes"`
	LastRunAt              *string `json:"last_run_at,omitempty" gorm:"column:last_run_at"`
	NextRunAt              string  `json:"next_run_at" gorm:"column:next_run_at"`

	CreatedAt string `json:"created_at" gorm:"column:created_at"`
	UpdatedAt string `json:"updated_at" gorm:"column:updated_at"`
}

func (AutoSeedRule) TableName() string { return "auto_seed_rules" }

// AutoSeedItem 表示从 RSS 或手工 URL 进入自动发种列表的一条种子记录。
// 参数/返回：字段直接映射 auto_seed_items 表，供列表、整理、发布、删除流程复用。
// 失败场景：无直接失败场景。
// 副作用：无副作用，仅承载数据。
type AutoSeedItem struct {
	ID int64 `json:"id" gorm:"column:id;primaryKey"`

	RuleID       int64  `json:"rule_id" gorm:"column:rule_id"`
	SourceSite   string `json:"source_site" gorm:"column:source_site"`
	GUID         string `json:"guid" gorm:"column:guid"`
	TorrentURL   string `json:"torrent_url" gorm:"column:torrent_url"`
	DetailURL    string `json:"detail_url" gorm:"column:detail_url"`
	Name         string `json:"name" gorm:"column:name"`
	Subtitle     string `json:"subtitle" gorm:"column:subtitle"`
	SavePath     string `json:"save_path" gorm:"-"`
	SizeBytes    int64  `json:"size_bytes" gorm:"column:size_bytes"`
	ResourceType string `json:"resource_type" gorm:"column:resource_type"`
	Medium       string `json:"medium" gorm:"column:medium"`
	TagsJSON     string `json:"tags_json" gorm:"column:tags_json"`

	Status             string `json:"status" gorm:"column:status"`
	RejectReason       string `json:"reject_reason" gorm:"column:reject_reason"`
	PublishResultsJSON string `json:"publish_results_json" gorm:"column:publish_results_json"`

	DownloaderID   string  `json:"downloader_id" gorm:"column:downloader_id"`
	DownloaderHash string  `json:"downloader_hash" gorm:"column:downloader_hash"`
	Progress       float64 `json:"progress" gorm:"column:progress"`
	Downloaded     bool    `json:"downloaded" gorm:"column:downloaded"`

	TorrentID string `json:"torrent_id" gorm:"column:torrent_id"`
	SiteName  string `json:"site_name" gorm:"column:site_name"`

	PushedAt    *string `json:"pushed_at,omitempty" gorm:"column:pushed_at"`
	OrganizedAt *string `json:"organized_at,omitempty" gorm:"column:organized_at"`
	PublishedAt *string `json:"published_at,omitempty" gorm:"column:published_at"`
	CreatedAt   string  `json:"created_at" gorm:"column:created_at"`
	UpdatedAt   string  `json:"updated_at" gorm:"column:updated_at"`
}

func (AutoSeedItem) TableName() string { return "auto_seed_items" }

// AutoSeedTorrentRecord 表示自动发种记录按 downloader_hash 匹配到的当前种子路径信息。
type AutoSeedTorrentRecord struct {
	Hash         string  `gorm:"column:hash"`
	Name         string  `gorm:"column:name"`
	SavePath     string  `gorm:"column:save_path"`
	Progress     float64 `gorm:"column:progress"`
	DownloaderID string  `gorm:"column:downloader_id"`
}

// AutoSeedRetentionCandidate 表示需要检查保种到期清理的自动发种记录。
type AutoSeedRetentionCandidate struct {
	AutoSeedItem
	SeedRetentionMinutes int    `gorm:"column:seed_retention_minutes"`
	LastPublishAt        string `gorm:"column:last_publish_at"`
}

// AutoSeedListQuery 定义自动发种列表的分页、筛选与搜索条件。
type AutoSeedListQuery struct {
	Page         int
	PageSize     int
	SourceSite   string
	Status       string
	ResourceType string
	DownloaderID string
	Search       string
}

// AutoSeedRepository 负责自动发种规则和 RSS 种子记录的数据库读写。
// 参数/返回：依赖 Store 访问数据库，方法返回 error 表示失败原因。
// 失败场景：数据库未初始化、查询或写入失败时返回 error。
// 副作用：会写入 auto_seed_rules、auto_seed_items 表。
type AutoSeedRepository struct {
	store *Store
}

// NewAutoSeedRepository 创建自动发种仓储实例。
// 参数/返回：store 为数据库连接容器，返回可复用的仓储对象。
// 失败场景：无直接失败场景。
// 副作用：无副作用。
func NewAutoSeedRepository(store *Store) *AutoSeedRepository {
	return &AutoSeedRepository{store: store}
}

// CreateRule 新增一条自动发种规则并补齐默认时间字段。
func (r *AutoSeedRepository) CreateRule(rule *AutoSeedRule) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	now := time.Now().Format(PublishQueueTimeLayout)
	rule.CreatedAt = now
	rule.UpdatedAt = now
	if rule.PullIntervalMinutes <= 0 {
		rule.PullIntervalMinutes = 30
	}
	if rule.PublishIntervalMinutes < 0 {
		rule.PublishIntervalMinutes = 0
	}
	if rule.PublishConcurrency <= 0 {
		rule.PublishConcurrency = 1
	}
	if rule.SeedRetentionMinutes < 0 {
		rule.SeedRetentionMinutes = 0
	}
	if strings.TrimSpace(rule.NextRunAt) == "" {
		rule.NextRunAt = now
	}
	return r.store.DB.Table("auto_seed_rules").Create(rule).Error
}

// UpdateRule 更新一条自动发种规则的可编辑字段。
func (r *AutoSeedRepository) UpdateRule(rule *AutoSeedRule) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	rule.UpdatedAt = time.Now().Format(PublishQueueTimeLayout)
	return r.store.DB.Table("auto_seed_rules").Where("id = ?", rule.ID).Updates(map[string]any{
		"name":                     rule.Name,
		"enabled":                  rule.Enabled,
		"paused_reason":            rule.PausedReason,
		"source_site":              rule.SourceSite,
		"rss_url":                  rule.RSSURL,
		"downloader_id":            rule.DownloaderID,
		"save_path":                rule.SavePath,
		"download_url":             rule.DownloadURL,
		"auto_pause":               rule.AutoPause,
		"auto_organize":            rule.AutoOrganize,
		"min_size_gb":              rule.MinSizeGB,
		"max_size_gb":              rule.MaxSizeGB,
		"types_json":               rule.TypesJSON,
		"media_json":               rule.MediaJSON,
		"tags_json":                rule.TagsJSON,
		"target_sites_json":        rule.TargetSitesJSON,
		"pull_interval_minutes":    rule.PullIntervalMinutes,
		"publish_interval_minutes": rule.PublishIntervalMinutes,
		"publish_concurrency":      rule.PublishConcurrency,
		"seed_retention_minutes":   rule.SeedRetentionMinutes,
		"next_run_at":              rule.NextRunAt,
		"updated_at":               rule.UpdatedAt,
	}).Error
}

// DeleteRule 删除规则以及该规则下尚未发布的 RSS 记录。
func (r *AutoSeedRepository) DeleteRule(id int64) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	return r.store.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Table("auto_seed_items").
			Where("rule_id = ? AND status NOT IN ?", id, []string{AutoSeedItemStatusPublished}).
			Delete(&AutoSeedItem{}).Error; err != nil {
			return err
		}
		result := tx.Table("auto_seed_rules").Where("id = ?", id).Delete(&AutoSeedRule{})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return errors.New("规则不存在")
		}
		return nil
	})
}

// GetRule 按 ID 查询自动发种规则。
func (r *AutoSeedRepository) GetRule(id int64) (*AutoSeedRule, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	row := AutoSeedRule{}
	if err := r.store.DB.Table("auto_seed_rules").Where("id = ?", id).First(&row).Error; err != nil {
		return nil, err
	}
	return &row, nil
}

// ListRules 返回全部自动发种规则，按最近创建倒序。
func (r *AutoSeedRepository) ListRules() ([]AutoSeedRule, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	rows := make([]AutoSeedRule, 0)
	if err := r.store.DB.Table("auto_seed_rules").Order("id DESC").Find(&rows).Error; err != nil {
		return nil, err
	}
	return rows, nil
}

// FindDueRules 查询到期且启用的 RSS 拉取规则。
func (r *AutoSeedRepository) FindDueRules(now time.Time) ([]AutoSeedRule, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	rows := make([]AutoSeedRule, 0)
	nowText := now.Format(PublishQueueTimeLayout)
	if err := r.store.DB.Table("auto_seed_rules").
		Where("enabled = ? AND next_run_at <= ?", true, nowText).
		Order("next_run_at ASC").
		Find(&rows).Error; err != nil {
		return nil, err
	}
	return rows, nil
}

// MarkRulePulled 更新规则的最近拉取时间、下次拉取时间和暂停原因。
func (r *AutoSeedRepository) MarkRulePulled(id int64, nextRunAt time.Time, pausedReason string, enabled bool) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	nowText := time.Now().Format(PublishQueueTimeLayout)
	return r.store.DB.Table("auto_seed_rules").Where("id = ?", id).Updates(map[string]any{
		"enabled":       enabled,
		"paused_reason": strings.TrimSpace(pausedReason),
		"last_run_at":   nowText,
		"next_run_at":   nextRunAt.Format(PublishQueueTimeLayout),
		"updated_at":    nowText,
	}).Error
}

// UpsertItem 按 rule_id + guid 幂等写入 RSS 种子记录。
func (r *AutoSeedRepository) UpsertItem(item *AutoSeedItem) (*AutoSeedItem, bool, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, false, errors.New("auto seed repo is nil")
	}
	if item == nil {
		return nil, false, errors.New("item is nil")
	}
	existing := AutoSeedItem{}
	err := r.store.DB.Table("auto_seed_items").
		Where("rule_id = ? AND guid = ?", item.RuleID, item.GUID).
		Limit(1).
		Find(&existing).Error
	if err != nil {
		return nil, false, err
	}
	if existing.ID > 0 {
		return &existing, false, nil
	}
	now := time.Now().Format(PublishQueueTimeLayout)
	item.CreatedAt = now
	item.UpdatedAt = now
	if strings.TrimSpace(item.Status) == "" {
		item.Status = AutoSeedItemStatusPending
	}
	if err := r.store.DB.Table("auto_seed_items").Create(item).Error; err != nil {
		return nil, false, err
	}
	return item, true, nil
}

// ResetItemForRetry 将已存在的 RSS 记录恢复为待推送状态，并刷新本次 RSS 提供的基础字段。
// 参数/返回：item 必须带有已有记录 ID 和最新 RSS 字段；返回数据库更新错误。
// 失败场景：仓储未初始化、item 为空或数据库更新失败时返回 error。
// 副作用：会清空上次失败原因、下载器 hash 和推送时间，使后续流程重新抓详情并推送下载器。
func (r *AutoSeedRepository) ResetItemForRetry(item *AutoSeedItem) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	if item == nil || item.ID <= 0 {
		return errors.New("item is nil")
	}
	return r.store.DB.Table("auto_seed_items").Where("id = ?", item.ID).Updates(map[string]any{
		"source_site":          item.SourceSite,
		"torrent_url":          item.TorrentURL,
		"detail_url":           item.DetailURL,
		"name":                 item.Name,
		"size_bytes":           item.SizeBytes,
		"resource_type":        item.ResourceType,
		"medium":               item.Medium,
		"tags_json":            item.TagsJSON,
		"status":               AutoSeedItemStatusPending,
		"reject_reason":        "",
		"publish_results_json": "",
		"downloader_id":        item.DownloaderID,
		"downloader_hash":      "",
		"progress":             0,
		"downloaded":           false,
		"torrent_id":           item.TorrentID,
		"site_name":            item.SiteName,
		"pushed_at":            nil,
		"updated_at":           time.Now().Format(PublishQueueTimeLayout),
	}).Error
}

// CreateManualItem 写入用户手动添加的种子 URL。
func (r *AutoSeedRepository) CreateManualItem(item *AutoSeedItem) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	now := time.Now().Format(PublishQueueTimeLayout)
	item.CreatedAt = now
	item.UpdatedAt = now
	if strings.TrimSpace(item.Status) == "" {
		item.Status = AutoSeedItemStatusPending
	}
	return r.store.DB.Table("auto_seed_items").Create(item).Error
}

// ListItems 分页查询自动发种种子列表。
func (r *AutoSeedRepository) ListItems(query AutoSeedListQuery) ([]AutoSeedItem, int64, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, 0, errors.New("auto seed repo is nil")
	}
	if query.Page < 1 {
		query.Page = 1
	}
	if query.PageSize < 1 || query.PageSize > 200 {
		query.PageSize = 20
	}
	db := r.store.DB.Table("auto_seed_items")
	if value := strings.TrimSpace(query.SourceSite); value != "" {
		db = db.Where("source_site = ?", value)
	}
	if values := autoSeedStatusFilterValues(query.Status); len(values) > 1 {
		db = db.Where("status IN ?", values)
	} else if len(values) == 1 {
		db = db.Where("status = ?", values[0])
	}
	if value := strings.TrimSpace(query.ResourceType); value != "" {
		db = db.Where("resource_type = ?", value)
	}
	if value := strings.TrimSpace(query.DownloaderID); value != "" {
		db = db.Where("downloader_id = ?", value)
	}
	if value := strings.TrimSpace(query.Search); value != "" {
		like := "%" + value + "%"
		db = db.Where("(name LIKE ? OR torrent_url LIKE ? OR detail_url LIKE ?)", like, like, like)
	}
	total := int64(0)
	if err := db.Count(&total).Error; err != nil {
		return nil, 0, err
	}
	rows := make([]AutoSeedItem, 0)
	offset := (query.Page - 1) * query.PageSize
	if err := db.Order("id DESC").Offset(offset).Limit(query.PageSize).Find(&rows).Error; err != nil {
		return nil, 0, err
	}
	return rows, total, nil
}

func autoSeedStatusFilterValues(status string) []string {
	value := strings.TrimSpace(status)
	if value == "" {
		return nil
	}
	if value == AutoSeedItemStatusNotPushed {
		return []string{AutoSeedItemStatusPending, AutoSeedItemStatusRejected}
	}
	return []string{value}
}

// GetItem 按 ID 查询自动发种种子记录。
func (r *AutoSeedRepository) GetItem(id int64) (*AutoSeedItem, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	row := AutoSeedItem{}
	if err := r.store.DB.Table("auto_seed_items").Where("id = ?", id).First(&row).Error; err != nil {
		return nil, err
	}
	return &row, nil
}

// UpdateItemBasics 更新种子的人工整理字段。
func (r *AutoSeedRepository) UpdateItemBasics(item *AutoSeedItem) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	nowText := time.Now().Format(PublishQueueTimeLayout)
	updates := map[string]any{
		"name":          item.Name,
		"subtitle":      item.Subtitle,
		"resource_type": item.ResourceType,
		"medium":        item.Medium,
		"tags_json":     item.TagsJSON,
		"torrent_id":    item.TorrentID,
		"site_name":     item.SiteName,
		"status":        item.Status,
		"organized_at":  item.OrganizedAt,
		"updated_at":    nowText,
	}
	return r.store.DB.Table("auto_seed_items").Where("id = ?", item.ID).Updates(updates).Error
}

// UpdateItemFetchedDetails 回填自动抓取到的种子基础信息，不改变当前流程状态。
func (r *AutoSeedRepository) UpdateItemFetchedDetails(item *AutoSeedItem) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	if item == nil || item.ID <= 0 {
		return errors.New("item is nil")
	}
	return r.store.DB.Table("auto_seed_items").Where("id = ?", item.ID).Updates(map[string]any{
		"name":          item.Name,
		"subtitle":      item.Subtitle,
		"detail_url":    item.DetailURL,
		"size_bytes":    item.SizeBytes,
		"resource_type": item.ResourceType,
		"medium":        item.Medium,
		"tags_json":     item.TagsJSON,
		"torrent_id":    item.TorrentID,
		"site_name":     item.SiteName,
		"updated_at":    time.Now().Format(PublishQueueTimeLayout),
	}).Error
}

// MarkItemPushed 更新种子推送下载器后的状态。
func (r *AutoSeedRepository) MarkItemPushed(id int64, downloaderID, downloaderHash, rejectReason string) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	nowText := time.Now().Format(PublishQueueTimeLayout)
	updates := map[string]any{
		"status":          AutoSeedItemStatusPushed,
		"downloader_hash": strings.TrimSpace(downloaderHash),
		"reject_reason":   strings.TrimSpace(rejectReason),
		"pushed_at":       nowText,
		"updated_at":      nowText,
	}
	if value := strings.TrimSpace(downloaderID); value != "" {
		updates["downloader_id"] = value
	}
	return r.store.DB.Table("auto_seed_items").Where("id = ?", id).Updates(updates).Error
}

// MarkItemRejected 标记种子未通过规则或推送失败。
func (r *AutoSeedRepository) MarkItemRejected(id int64, reason string) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	return r.store.DB.Table("auto_seed_items").Where("id = ?", id).Updates(map[string]any{
		"status":        AutoSeedItemStatusRejected,
		"reject_reason": strings.TrimSpace(reason),
		"updated_at":    time.Now().Format(PublishQueueTimeLayout),
	}).Error
}

// UpdateItemProgress 更新自动发种记录的下载进度。
func (r *AutoSeedRepository) UpdateItemProgress(id int64, progress float64, downloaded bool, hash string) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	updates := map[string]any{
		"progress":   progress,
		"downloaded": downloaded,
		"updated_at": time.Now().Format(PublishQueueTimeLayout),
	}
	if strings.TrimSpace(hash) != "" {
		updates["downloader_hash"] = strings.TrimSpace(hash)
	}
	return r.store.DB.Table("auto_seed_items").Where("id = ?", id).Updates(updates).Error
}

// FindTorrentByDownloaderHash 按自动发种记录中的下载器 ID 和 hash 匹配 torrents 表路径。
func (r *AutoSeedRepository) FindTorrentByDownloaderHash(downloaderID, hash string) (AutoSeedTorrentRecord, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return AutoSeedTorrentRecord{}, errors.New("auto seed repo is nil")
	}
	downloaderID = strings.TrimSpace(downloaderID)
	hash = strings.TrimSpace(hash)
	if downloaderID == "" || hash == "" {
		return AutoSeedTorrentRecord{}, gorm.ErrRecordNotFound
	}
	row := AutoSeedTorrentRecord{}
	err := r.store.DB.Table("torrents").
		Select("hash, name, save_path, progress, downloader_id").
		Where("downloader_id = ? AND LOWER(hash) = ? AND (is_hidden = 0 OR is_hidden IS NULL)", downloaderID, strings.ToLower(hash)).
		Limit(1).
		Scan(&row).Error
	if err != nil {
		return AutoSeedTorrentRecord{}, err
	}
	if strings.TrimSpace(row.Hash) == "" {
		return AutoSeedTorrentRecord{}, gorm.ErrRecordNotFound
	}
	return row, nil
}

// UpdateSeedParameterScreenshotsByTorrentIDAndSiteName 更新自动发种对应种子参数中的截图内容。
func (r *AutoSeedRepository) UpdateSeedParameterScreenshotsByTorrentIDAndSiteName(torrentID, siteName, screenshots string) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	torrentID = strings.TrimSpace(torrentID)
	siteName = strings.TrimSpace(siteName)
	screenshots = strings.TrimSpace(screenshots)
	if torrentID == "" || siteName == "" {
		return errors.New("torrentID or siteName is empty")
	}
	lowered := strings.ToLower(siteName)
	return r.store.DB.Table("seed_parameters").
		Where("torrent_id = ? AND (LOWER(site_name) = ? OR LOWER(nickname) = ?)", torrentID, lowered, lowered).
		Updates(map[string]any{
			"screenshots":              screenshots,
			"screenshot_review_status": "none",
			"updated_at":               time.Now().Format(PublishQueueTimeLayout),
		}).Error
}

// MarkItemPublished 写入发布结果并标记为已发布。
func (r *AutoSeedRepository) MarkItemPublished(id int64, resultsJSON string) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	nowText := time.Now().Format(PublishQueueTimeLayout)
	return r.store.DB.Table("auto_seed_items").Where("id = ?", id).Updates(map[string]any{
		"status":               AutoSeedItemStatusPublished,
		"publish_results_json": strings.TrimSpace(resultsJSON),
		"reject_reason":        "",
		"published_at":         nowText,
		"updated_at":           nowText,
	}).Error
}

// UpdateItemPublishFeedback 回写发布队列反馈，不改变自动发种记录的流程状态。
// 参数/返回：id 为自动发种记录主键，resultsJSON 为各目标站点的结果，reason 为未成功入队原因。
// 失败场景：仓储未初始化或数据库更新失败时返回错误。
// 副作用：更新 auto_seed_items 的发布结果、原因与更新时间。
func (r *AutoSeedRepository) UpdateItemPublishFeedback(id int64, resultsJSON, reason string) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("auto seed repo is nil")
	}
	return r.store.DB.Table("auto_seed_items").Where("id = ?", id).Updates(map[string]any{
		"publish_results_json": strings.TrimSpace(resultsJSON),
		"reject_reason":        strings.TrimSpace(reason),
		"updated_at":           time.Now().Format(PublishQueueTimeLayout),
	}).Error
}

// GetSeedParameter 查询自动抓取后写入的种子参数记录。
func (r *AutoSeedRepository) GetSeedParameter(torrentID, siteName string) (map[string]any, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	row := map[string]any{}
	err := r.store.DB.Table("seed_parameters").
		Where("torrent_id = ? AND (site_name = ? OR nickname = ?)", strings.TrimSpace(torrentID), strings.TrimSpace(siteName), strings.TrimSpace(siteName)).
		Order("updated_at DESC").
		Limit(1).
		Scan(&row).Error
	if err != nil {
		return nil, err
	}
	if len(row) == 0 {
		lowered := strings.ToLower(strings.TrimSpace(siteName))
		if lowered != "" {
			err = r.store.DB.Table("seed_parameters").
				Where("torrent_id = ? AND (LOWER(site_name) = ? OR LOWER(nickname) = ?)", strings.TrimSpace(torrentID), lowered, lowered).
				Order("updated_at DESC").
				Limit(1).
				Scan(&row).Error
			if err != nil {
				return nil, err
			}
		}
	}
	if len(row) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return row, nil
}

// DeleteItems 删除自动发种种子记录。
func (r *AutoSeedRepository) DeleteItems(ids []int64) (int64, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return 0, errors.New("auto seed repo is nil")
	}
	if len(ids) == 0 {
		return 0, nil
	}
	result := r.store.DB.Table("auto_seed_items").Where("id IN ?", ids).Delete(&AutoSeedItem{})
	if result.Error != nil {
		return 0, result.Error
	}
	return result.RowsAffected, nil
}

// ListRetentionCandidates 查询已发布且配置了保种时间的自动发种记录，用于后台到期清理。
func (r *AutoSeedRepository) ListRetentionCandidates(limit int) ([]AutoSeedRetentionCandidate, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	if limit <= 0 || limit > 1000 {
		limit = 500
	}
	// MySQL/PostgreSQL 中 last_publish_at 为日期类型，与空串比较/作为默认值会触发 1525 错误，仅 SQLite(TEXT) 保留空串写法。
	lastPublishAtSelect := "sp.last_publish_at AS last_publish_at"
	lastPublishAtNonEmpty := ""
	if r.store.DBType == "sqlite" {
		lastPublishAtSelect = "COALESCE(sp.last_publish_at, '') AS last_publish_at"
		lastPublishAtNonEmpty = "\n\t\t\t  AND last_publish_at <> ''"
	}
	rows := make([]AutoSeedRetentionCandidate, 0)
	err := r.store.DB.Table("auto_seed_items AS i").
		Select("i.*, r.seed_retention_minutes, "+lastPublishAtSelect).
		Joins("JOIN auto_seed_rules AS r ON r.id = i.rule_id").
		Joins(`LEFT JOIN (
			SELECT hash, MAX(last_publish_at) AS last_publish_at
			FROM seed_parameters
			WHERE hash IS NOT NULL
			  AND hash <> ''
			  AND last_publish_at IS NOT NULL` + lastPublishAtNonEmpty + `
			GROUP BY hash
		) AS sp ON LOWER(TRIM(sp.hash)) = LOWER(TRIM(i.downloader_hash))`).
		Where("i.status = ? AND r.seed_retention_minutes > 0", AutoSeedItemStatusPublished).
		Where("i.downloader_id <> '' AND i.downloader_hash <> ''").
		Order("COALESCE(sp.last_publish_at, i.published_at) ASC, i.id ASC").
		Limit(limit).
		Scan(&rows).Error
	if err != nil {
		return nil, err
	}
	return rows, nil
}

// ListProgressItems 查询下载器进度页所需的全部自动发种记录。
func (r *AutoSeedRepository) ListProgressItems(downloaderID string) ([]AutoSeedItem, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	db := r.store.DB.Table("auto_seed_items")
	if strings.TrimSpace(downloaderID) != "" {
		db = db.Where("downloader_id = ?", strings.TrimSpace(downloaderID))
	}
	rows := make([]AutoSeedItem, 0)
	if err := db.Order("updated_at DESC, id DESC").Limit(500).Find(&rows).Error; err != nil {
		return nil, err
	}
	return rows, nil
}

// GetSiteSpeedLimit 按站点昵称查询 sites 表中的 speed_limit（MB/s），未找到返回 0。
func (r *AutoSeedRepository) GetSiteSpeedLimit(nickname string) int {
	if r == nil || r.store == nil || r.store.DB == nil {
		return 0
	}
	nickname = strings.TrimSpace(nickname)
	if nickname == "" {
		return 0
	}
	var limit int
	err := r.store.DB.Table("sites").
		Select("speed_limit").
		Where("nickname = ? OR site = ?", nickname, nickname).
		Order("id DESC").
		Limit(1).
		Scan(&limit).Error
	if err != nil {
		return 0
	}
	return limit
}

// FindPublishLogsForItems 查询指定种子集合的最新发布日志，用于聚合发布结果。
func (r *AutoSeedRepository) FindPublishLogsForItems(items []AutoSeedItem) ([]PublishLogEntry, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("auto seed repo is nil")
	}
	keys := make([]string, 0, len(items))
	for _, item := range items {
		if strings.TrimSpace(item.TorrentID) != "" {
			keys = append(keys, strings.TrimSpace(item.TorrentID))
		}
	}
	if len(keys) == 0 {
		return []PublishLogEntry{}, nil
	}
	rows := make([]PublishLogEntry, 0)
	if err := r.store.DB.Model(&PublishLogEntry{}).
		Where("scene = ? AND torrent_id IN ?", "auto_seed", keys).
		Order("id DESC").
		Find(&rows).Error; err != nil {
		return nil, fmt.Errorf("查询自动发种发布日志失败: %w", err)
	}
	return rows, nil
}

package repository

import (
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"
)

const scheduledSeedTimeLayout = "2006-01-02 15:04:05"

const (
	ScheduledSeedStatusActive    = "active"
	ScheduledSeedStatusPaused    = "paused"
	ScheduledSeedStatusCompleted = "completed"
)

// normalizeNextRunAt 将任意常见时间字符串（ISO 8601 带 Z 后缀、带毫秒、
// 空格分隔等）统一归一化为 MySQL DATETIME 兼容格式 "2006-01-02 15:04:05"。
// 解析失败或为空时回退到当前时间，确保写入 next_run_at 不会触发
// MySQL Error 1292 (Incorrect datetime value)。
func normalizeNextRunAt(value string) string {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return time.Now().Format(scheduledSeedTimeLayout)
	}
	layouts := []string{
		scheduledSeedTimeLayout, // 2006-01-02 15:04:05（空格分隔）
		"2006-01-02T15:04:05",   // T 分隔、无时区
		time.RFC3339Nano,        // 2006-01-02T15:04:05.999999999Z07:00（兼容带/不带毫秒）
		time.RFC3339,            // 2006-01-02T15:04:05Z07:00
		"2006-01-02T15:04:05Z07:00",
		"2006-01-02",
	}
	for _, layout := range layouts {
		if t, err := time.Parse(layout, trimmed); err == nil {
			return t.Format(scheduledSeedTimeLayout)
		}
	}
	// 所有格式均无法解析，回退当前时间避免写入非法值
	return time.Now().Format(scheduledSeedTimeLayout)
}

// ScheduledSeedTask 表示一个定时发种任务定义，包含种子列表、目标站点与调度状态。
type ScheduledSeedTask struct {
	ID int64 `json:"id" gorm:"column:id;primaryKey"`

	Name   string `json:"name" gorm:"column:name"`
	Status string `json:"status" gorm:"column:status"`

	SeedsJSON       string `json:"seeds_json" gorm:"column:seeds_json"`
	TargetSitesJSON string `json:"target_sites_json" gorm:"column:target_sites_json"`

	IntervalMinutes  int `json:"interval_minutes" gorm:"column:interval_minutes"`
	CurrentSeedIndex int `json:"current_seed_index" gorm:"column:current_seed_index"`
	CurrentSiteIndex int `json:"current_site_index" gorm:"column:current_site_index"`
	TotalPublished   int `json:"total_published" gorm:"column:total_published"`
	TotalSkipped     int `json:"total_skipped" gorm:"column:total_skipped"`

	LoopEnabled bool   `json:"loop_enabled" gorm:"column:loop_enabled"`
	TriggerTag  string `json:"trigger_tag" gorm:"column:trigger_tag"`

	LastRunAt *string `json:"last_run_at,omitempty" gorm:"column:last_run_at"`
	NextRunAt string  `json:"next_run_at" gorm:"column:next_run_at"`

	CreatedAt string `json:"created_at" gorm:"column:created_at"`
	UpdatedAt string `json:"updated_at" gorm:"column:updated_at"`
}

func (ScheduledSeedTask) TableName() string { return "scheduled_seed_tasks" }

// SeedRef 表示种子引用，存储在 seeds_json 中。
type SeedRef struct {
	TorrentID string `json:"torrent_id"`
	SiteName  string `json:"site_name"`
	Title     string `json:"title,omitempty"`
}

// ParseSeeds 反序列化种子列表。
func (t *ScheduledSeedTask) ParseSeeds() ([]SeedRef, error) {
	var seeds []SeedRef
	if err := json.Unmarshal([]byte(t.SeedsJSON), &seeds); err != nil {
		return nil, fmt.Errorf("解析 seeds_json 失败: %w", err)
	}
	return seeds, nil
}

// ParseTargetSites 反序列化目标站点列表。
func (t *ScheduledSeedTask) ParseTargetSites() ([]string, error) {
	var sites []string
	if err := json.Unmarshal([]byte(t.TargetSitesJSON), &sites); err != nil {
		return nil, fmt.Errorf("解析 target_sites_json 失败: %w", err)
	}
	return sites, nil
}

// ScheduledSeedRepository 负责定时发种任务的 CRUD 与调度状态更新。
type ScheduledSeedRepository struct {
	store *Store
}

// NewScheduledSeedRepository 创建定时发种仓储实例。
func NewScheduledSeedRepository(store *Store) *ScheduledSeedRepository {
	return &ScheduledSeedRepository{store: store}
}

// Create 插入新任务并自动生成 trigger_tag。
func (r *ScheduledSeedRepository) Create(task *ScheduledSeedTask) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("scheduled seed repo is nil")
	}

	now := time.Now().Format(scheduledSeedTimeLayout)
	task.CreatedAt = now
	task.UpdatedAt = now
	if task.Status == "" {
		task.Status = ScheduledSeedStatusActive
	}
	// 归一化 next_run_at，兼容 ISO 8601 / 带时区 / 空格分隔等多种格式，
	// 避免 MySQL Error 1292 (Incorrect datetime value)。
	task.NextRunAt = normalizeNextRunAt(task.NextRunAt)

	if err := r.store.DB.Table("scheduled_seed_tasks").Create(task).Error; err != nil {
		return fmt.Errorf("创建定时发种任务失败: %w", err)
	}

	// 生成 trigger_tag 并回写
	task.TriggerTag = fmt.Sprintf("sched:%d", task.ID)
	if err := r.store.DB.Table("scheduled_seed_tasks").
		Where("id = ?", task.ID).
		Update("trigger_tag", task.TriggerTag).Error; err != nil {
		return fmt.Errorf("更新 trigger_tag 失败: %w", err)
	}
	return nil
}

// GetByID 按 ID 查询单个任务。
func (r *ScheduledSeedRepository) GetByID(id int64) (*ScheduledSeedTask, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("scheduled seed repo is nil")
	}

	var task ScheduledSeedTask
	if err := r.store.DB.Table("scheduled_seed_tasks").Where("id = ?", id).First(&task).Error; err != nil {
		return nil, fmt.Errorf("查询定时发种任务失败: %w", err)
	}
	return &task, nil
}

// List 分页查询任务列表，支持 status 筛选。
func (r *ScheduledSeedRepository) List(page, pageSize int, status string) ([]ScheduledSeedTask, int64, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, 0, errors.New("scheduled seed repo is nil")
	}

	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 200 {
		pageSize = 20
	}

	query := r.store.DB.Table("scheduled_seed_tasks")
	if status != "" {
		query = query.Where("status = ?", status)
	}

	var total int64
	if err := query.Count(&total).Error; err != nil {
		return nil, 0, fmt.Errorf("统计任务总数失败: %w", err)
	}

	var tasks []ScheduledSeedTask
	offset := (page - 1) * pageSize
	if err := query.Order("id DESC").Offset(offset).Limit(pageSize).Find(&tasks).Error; err != nil {
		return nil, 0, fmt.Errorf("查询任务列表失败: %w", err)
	}
	return tasks, total, nil
}

// Update 全量更新任务字段。
func (r *ScheduledSeedRepository) Update(task *ScheduledSeedTask) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("scheduled seed repo is nil")
	}

	task.UpdatedAt = time.Now().Format(scheduledSeedTimeLayout)
	// 归一化 next_run_at，兼容前端或历史数据可能传入的 ISO 8601 / 带时区格式，
	// 避免 MySQL Error 1292 (Incorrect datetime value)。
	task.NextRunAt = normalizeNextRunAt(task.NextRunAt)
	if err := r.store.DB.Table("scheduled_seed_tasks").
		Where("id = ?", task.ID).
		Updates(map[string]any{
			"name":               task.Name,
			"status":             task.Status,
			"seeds_json":         task.SeedsJSON,
			"target_sites_json":  task.TargetSitesJSON,
			"interval_minutes":   task.IntervalMinutes,
			"current_seed_index": task.CurrentSeedIndex,
			"current_site_index": task.CurrentSiteIndex,
			"total_published":    task.TotalPublished,
			"total_skipped":      task.TotalSkipped,
			"loop_enabled":       task.LoopEnabled,
			"next_run_at":        task.NextRunAt,
			"updated_at":         task.UpdatedAt,
		}).Error; err != nil {
		return fmt.Errorf("更新定时发种任务失败: %w", err)
	}
	return nil
}

// Delete 按 ID 删除任务。
func (r *ScheduledSeedRepository) Delete(id int64) error {
	if r == nil || r.store == nil || r.store.DB == nil {
		return errors.New("scheduled seed repo is nil")
	}

	result := r.store.DB.Table("scheduled_seed_tasks").Where("id = ?", id).Delete(nil)
	if result.Error != nil {
		return fmt.Errorf("删除定时发种任务失败: %w", result.Error)
	}
	if result.RowsAffected == 0 {
		return errors.New("任务不存在")
	}
	return nil
}

// BatchDelete 按 ID 批量删除任务，返回实际删除行数。
func (r *ScheduledSeedRepository) BatchDelete(ids []int64) (int64, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return 0, errors.New("scheduled seed repo is nil")
	}
	if len(ids) == 0 {
		return 0, nil
	}
	result := r.store.DB.Table("scheduled_seed_tasks").Where("id IN ?", ids).Delete(nil)
	if result.Error != nil {
		return 0, fmt.Errorf("批量删除定时发种任务失败: %w", result.Error)
	}
	return result.RowsAffected, nil
}

// BatchSetStatus 批量设置任务状态（active/paused），返回实际更新行数。
// 激活时同步将 next_run_at 重置为当前时间，使任务在下次调度周期即可执行；
// 暂停时保留原 next_run_at，便于恢复后按原节奏继续。
func (r *ScheduledSeedRepository) BatchSetStatus(ids []int64, status string) (int64, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return 0, errors.New("scheduled seed repo is nil")
	}
	if len(ids) == 0 {
		return 0, nil
	}
	if status != ScheduledSeedStatusActive && status != ScheduledSeedStatusPaused {
		return 0, fmt.Errorf("不支持的状态: %s", status)
	}
	now := time.Now().Format(scheduledSeedTimeLayout)
	updates := map[string]any{
		"status":     status,
		"updated_at": now,
	}
	if status == ScheduledSeedStatusActive {
		updates["next_run_at"] = now
	}
	result := r.store.DB.Table("scheduled_seed_tasks").Where("id IN ?", ids).Updates(updates)
	if result.Error != nil {
		return 0, fmt.Errorf("批量更新任务状态失败: %w", result.Error)
	}
	return result.RowsAffected, nil
}

// ToggleStatus 在 active 和 paused 之间切换状态。
func (r *ScheduledSeedRepository) ToggleStatus(id int64) (string, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return "", errors.New("scheduled seed repo is nil")
	}

	task, err := r.GetByID(id)
	if err != nil {
		return "", err
	}

	newStatus := ScheduledSeedStatusActive
	if task.Status == ScheduledSeedStatusActive {
		newStatus = ScheduledSeedStatusPaused
	} else if task.Status == ScheduledSeedStatusCompleted {
		// 已完成的任务可以重新启动
		newStatus = ScheduledSeedStatusActive
	}

	now := time.Now().Format(scheduledSeedTimeLayout)
	updates := map[string]any{
		"status":     newStatus,
		"updated_at": now,
	}

	// 重新激活时重置 next_run_at
	if newStatus == ScheduledSeedStatusActive && task.Status != ScheduledSeedStatusActive {
		nextRun := time.Now().Add(time.Duration(task.IntervalMinutes) * time.Minute).Format(scheduledSeedTimeLayout)
		updates["next_run_at"] = nextRun
	}

	if err := r.store.DB.Table("scheduled_seed_tasks").Where("id = ?", id).Updates(updates).Error; err != nil {
		return "", fmt.Errorf("切换任务状态失败: %w", err)
	}
	return newStatus, nil
}

// FindDueTasks 查询所有到期需要执行的活跃任务。
func (r *ScheduledSeedRepository) FindDueTasks(now time.Time) ([]ScheduledSeedTask, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("scheduled seed repo is nil")
	}

	nowStr := now.Format(scheduledSeedTimeLayout)
	var tasks []ScheduledSeedTask
	if err := r.store.DB.Table("scheduled_seed_tasks").
		Where("status = ? AND next_run_at <= ?", ScheduledSeedStatusActive, nowStr).
		Order("next_run_at ASC").
		Find(&tasks).Error; err != nil {
		return nil, fmt.Errorf("查询到期任务失败: %w", err)
	}
	return tasks, nil
}

// ClaimAndAdvance 更新任务的调度指针和状态。
// 使用 id 定位（单实例调度器 + CheckDuplicate 已防止重复发布，无需乐观锁）。
func (r *ScheduledSeedRepository) ClaimAndAdvance(
	taskID int64,
	prevUpdatedAt string,
	newSeedIndex int,
	newSiteIndex int,
	newStatus string,
	nextRunAt string,
	lastRunAt string,
	totalPublishedDelta int,
	totalSkippedDelta int,
) (bool, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return false, errors.New("scheduled seed repo is nil")
	}

	now := time.Now().Format(scheduledSeedTimeLayout)

	updates := map[string]any{
		"current_seed_index": newSeedIndex,
		"current_site_index": newSiteIndex,
		"status":             newStatus,
		"next_run_at":        nextRunAt,
		"last_run_at":        lastRunAt,
		"updated_at":         now,
	}
	if totalPublishedDelta != 0 {
		updates["total_published"] = gorm.Expr("total_published + ?", totalPublishedDelta)
	}
	if totalSkippedDelta != 0 {
		updates["total_skipped"] = gorm.Expr("total_skipped + ?", totalSkippedDelta)
	}

	result := r.store.DB.Table("scheduled_seed_tasks").
		Where("id = ?", taskID).
		Updates(updates)

	if result.Error != nil {
		return false, fmt.Errorf("更新调度状态失败: %w", result.Error)
	}
	return result.RowsAffected > 0, nil
}

// CheckDuplicate 查询发种日志，判断该种子是否已成功发布到目标站点。
func (r *ScheduledSeedRepository) CheckDuplicate(torrentID string, sourceSite string, targetSite string) (bool, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return false, errors.New("scheduled seed repo is nil")
	}

	var count int64
	if err := r.store.DB.Table("publish_logs").
		Where("torrent_id = ? AND source_site = ? AND target_site = ? AND scene = ? AND status = ?",
			torrentID, sourceSite, targetSite, "scheduled_seeding", "success").
		Count(&count).Error; err != nil {
		return false, fmt.Errorf("查重发种日志失败: %w", err)
	}
	return count > 0, nil
}

// SeedFilter 定义可选种子的筛选与排序参数。
type SeedFilter struct {
	Search        string
	Downloader    string
	ExistSites    []string // 存在于这些站点
	NotExistSites []string // 不存在于这些站点
	StateFilters  []string // 状态筛选
	PathFilters   []string // 保存路径筛选
	TagFilters    []string // 标签筛选（命中任一标签即保留）
	SortProp      string   // 排序字段: site_count, size, progress, title
	SortOrder     string   // ascending / descending
}

// ListAllSeedSites 返回所有已发现站点列表（torrents 表 + sites 表有 cookie 的）。
func (r *ScheduledSeedRepository) ListAllSeedSites() ([]string, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("scheduled seed repo is nil")
	}
	sitesSet := map[string]struct{}{}

	var torrentSites []string
	if err := r.store.DB.Raw("SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != '' AND (is_hidden = 0 OR is_hidden IS NULL)").Pluck("sites", &torrentSites).Error; err == nil {
		for _, s := range torrentSites {
			s = strings.TrimSpace(s)
			if s != "" {
				sitesSet[s] = struct{}{}
			}
		}
	}

	var sitesWithCookie []string
	if err := r.store.DB.Raw("SELECT nickname FROM sites WHERE cookie IS NOT NULL AND cookie != ''").Pluck("nickname", &sitesWithCookie).Error; err == nil {
		for _, s := range sitesWithCookie {
			s = strings.TrimSpace(s)
			if s != "" {
				sitesSet[s] = struct{}{}
			}
		}
	}

	result := make([]string, 0, len(sitesSet))
	for s := range sitesSet {
		result = append(result, s)
	}
	sort.Strings(result)
	return result, nil
}

// ListSeedUniqueTags 返回 seed_parameters 表中出现过的所有标准标签，用于前端标签下拉筛选。
// tags 字段以 JSON 数组字符串存储（如 ["1080p","国语"]），此处兼容旧的逗号分隔格式。
func (r *ScheduledSeedRepository) ListSeedUniqueTags() ([]string, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("scheduled seed repo is nil")
	}

	var tagsRaw []string
	if err := r.store.DB.Raw(
		"SELECT DISTINCT tags FROM seed_parameters WHERE tags IS NOT NULL AND tags != ''",
	).Pluck("tags", &tagsRaw).Error; err != nil {
		return nil, fmt.Errorf("查询种子标签失败: %w", err)
	}

	tagSet := map[string]struct{}{}
	for _, raw := range tagsRaw {
		trimmed := strings.TrimSpace(raw)
		if trimmed == "" {
			continue
		}
		var parsed []string
		if err := json.Unmarshal([]byte(trimmed), &parsed); err == nil {
			for _, t := range parsed {
				if t = strings.TrimSpace(t); t != "" {
					tagSet[t] = struct{}{}
				}
			}
			continue
		}
		for _, t := range strings.Split(trimmed, ",") {
			if t = strings.TrimSpace(t); t != "" {
				tagSet[t] = struct{}{}
			}
		}
	}

	result := make([]string, 0, len(tagSet))
	for t := range tagSet {
		result = append(result, t)
	}
	sort.Strings(result)
	return result, nil
}

// ListSeedUniques 返回所有唯一的保存路径和状态值，用于前端筛选 UI。
func (r *ScheduledSeedRepository) ListSeedUniques() (paths []string, states []string, err error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, nil, errors.New("scheduled seed repo is nil")
	}

	var uniquePaths []string
	r.store.DB.Raw("SELECT DISTINCT save_path FROM torrents WHERE save_path IS NOT NULL AND save_path != '' AND (is_hidden = 0 OR is_hidden IS NULL) ORDER BY save_path").Pluck("save_path", &uniquePaths)

	var uniqueStates []string
	r.store.DB.Raw("SELECT DISTINCT state FROM torrents WHERE state IS NOT NULL AND state != '' AND (is_hidden = 0 OR is_hidden IS NULL) ORDER BY state").Pluck("state", &uniqueStates)

	return uniquePaths, uniqueStates, nil
}

// GetSeedSites 根据种子 name 查询其在 torrents 表中已发布的所有站点。
func (r *ScheduledSeedRepository) GetSeedSites(name string) ([]string, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, errors.New("scheduled seed repo is nil")
	}

	var sites []string
	if err := r.store.DB.Raw(
		"SELECT DISTINCT sites FROM torrents WHERE name = ? AND is_hidden = 0 AND sites IS NOT NULL AND sites != '' ORDER BY sites",
		name,
	).Pluck("sites", &sites).Error; err != nil {
		return nil, fmt.Errorf("查询种子发布站点失败: %w", err)
	}
	return sites, nil
}

// ListAvailableSeeds 查询正在做种的可选种子列表（从 seed_parameters 表 JOIN torrents 表）。
// 返回完整字段用于表格展示，包括做种数（从 torrents 表统计，与一种多站一致）、下载器、大小、进度。
func (r *ScheduledSeedRepository) ListAvailableSeeds(page, pageSize int, f SeedFilter) ([]map[string]any, int64, int, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return nil, 0, 0, errors.New("scheduled seed repo is nil")
	}

	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 200 {
		pageSize = 20
	}

	// 根据数据库类型选择 GROUP_CONCAT 表达式
	var groupConcatExpr string
	switch r.store.DBType {
	case "postgresql":
		groupConcatExpr = "STRING_AGG(DISTINCT t.downloader_id, ',')"
	default:
		// sqlite, mysql
		groupConcatExpr = "GROUP_CONCAT(DISTINCT t.downloader_id)"
	}

	// 构建公共 WHERE 条件（用于计数和分页查询）
	// 只保留做种站点数大于 0 的种子，确保总数统计与分页结果一致。
	whereConditions := " AND EXISTS (SELECT 1 FROM torrents t0 WHERE t0.name = seed_parameters.name AND t0.is_hidden = 0 AND t0.sites IS NOT NULL AND t0.sites != '')"
	whereArgs := []any{}
	if f.Search != "" {
		likePattern := "%" + f.Search + "%"
		whereConditions += " AND (seed_parameters.title LIKE ? OR seed_parameters.torrent_id LIKE ? OR seed_parameters.site_name LIKE ? OR seed_parameters.subtitle LIKE ?)"
		whereArgs = append(whereArgs, likePattern, likePattern, likePattern, likePattern)
	}
	if f.Downloader != "" {
		whereConditions += " AND EXISTS (SELECT 1 FROM torrents t2 WHERE t2.name = seed_parameters.name AND t2.downloader_id = ? AND t2.is_hidden = 0)"
		whereArgs = append(whereArgs, f.Downloader)
	}
	if len(f.ExistSites) > 0 {
		placeholders := strings.Repeat("?,", len(f.ExistSites))
		placeholders = placeholders[:len(placeholders)-1]
		whereConditions += " AND EXISTS (SELECT 1 FROM torrents t3 WHERE t3.name = seed_parameters.name AND t3.is_hidden = 0 AND t3.sites IN (" + placeholders + "))"
		for _, s := range f.ExistSites {
			whereArgs = append(whereArgs, s)
		}
	}
	if len(f.NotExistSites) > 0 {
		placeholders := strings.Repeat("?,", len(f.NotExistSites))
		placeholders = placeholders[:len(placeholders)-1]
		whereConditions += " AND NOT EXISTS (SELECT 1 FROM torrents t4 WHERE t4.name = seed_parameters.name AND t4.is_hidden = 0 AND t4.sites IN (" + placeholders + "))"
		for _, s := range f.NotExistSites {
			whereArgs = append(whereArgs, s)
		}
	}
	if len(f.StateFilters) > 0 {
		placeholders := strings.Repeat("?,", len(f.StateFilters))
		placeholders = placeholders[:len(placeholders)-1]
		whereConditions += " AND EXISTS (SELECT 1 FROM torrents t5 WHERE t5.name = seed_parameters.name AND t5.is_hidden = 0 AND t5.state IN (" + placeholders + "))"
		for _, s := range f.StateFilters {
			whereArgs = append(whereArgs, s)
		}
	}
	if len(f.PathFilters) > 0 {
		placeholders := strings.Repeat("?,", len(f.PathFilters))
		placeholders = placeholders[:len(placeholders)-1]
		whereConditions += " AND EXISTS (SELECT 1 FROM torrents t6 WHERE t6.name = seed_parameters.name AND t6.is_hidden = 0 AND t6.save_path IN (" + placeholders + "))"
		for _, s := range f.PathFilters {
			whereArgs = append(whereArgs, s)
		}
	}
	if len(f.TagFilters) > 0 {
		// seed_parameters.tags 存储 JSON 数组字符串（如 ["1080p","国语"]），
		// 按带引号的完整元素匹配，避免子串误命中；多选之间为 OR（命中任一标签）。
		tagClauses := make([]string, 0, len(f.TagFilters))
		for _, t := range f.TagFilters {
			tagClauses = append(tagClauses, "seed_parameters.tags LIKE ?")
			whereArgs = append(whereArgs, `%"`+t+`"%`)
		}
		whereConditions += " AND (" + strings.Join(tagClauses, " OR ") + ")"
	}

	// 统计 total_site_count（所有已发现站点数）
	totalSiteCount := 0
	allSites, _ := r.ListAllSeedSites()
	totalSiteCount = len(allSites)

	// 使用子查询统计不同种子数，兼容所有数据库方言
	var total int64
	countSQL := "SELECT COUNT(*) FROM (SELECT DISTINCT seed_parameters.torrent_id, seed_parameters.site_name FROM seed_parameters LEFT JOIN torrents t ON seed_parameters.name = t.name AND t.is_hidden = 0 WHERE 1=1" + whereConditions + ") AS sub"
	if err := r.store.DB.Raw(countSQL, whereArgs...).Scan(&total).Error; err != nil {
		total = 0
	}

	// 做种数子查询：从 torrents 表统计（与一种多站一致）
	// 使用 MAX(seed_parameters.name) 满足 MySQL ONLY_FULL_GROUP_BY 模式
	siteCountSubquery := "(SELECT COUNT(DISTINCT t7.sites) FROM torrents t7 WHERE t7.name = MAX(seed_parameters.name) AND t7.is_hidden = 0 AND t7.sites IS NOT NULL AND t7.sites != '')"

	// 查询分页数据
	// 所有非 GROUP BY 列使用 MAX() 聚合，满足 MySQL ONLY_FULL_GROUP_BY 模式
	selectCols := fmt.Sprintf(`seed_parameters.torrent_id, seed_parameters.site_name,
		MAX(seed_parameters.name) AS name,
		MAX(seed_parameters.nickname) AS nickname,
		MAX(seed_parameters.title) AS title,
		MAX(seed_parameters.subtitle) AS subtitle,
		MAX(seed_parameters.team) AS team,
		MAX(seed_parameters.source) AS source,
		MAX(seed_parameters.tags) AS tags,
		%s AS site_count,
		%d AS total_site_count,
		%s AS downloader_ids,
		MAX(t.size) AS size,
		MAX(t.progress) AS progress`, siteCountSubquery, totalSiteCount, groupConcatExpr)

	baseQuery := r.store.DB.Table("seed_parameters").
		Joins("LEFT JOIN torrents t ON seed_parameters.name = t.name AND t.is_hidden = 0")
	// 应用 WHERE 条件（去掉开头的 " AND "）
	if len(whereConditions) > 5 {
		baseQuery = baseQuery.Where(whereConditions[5:], whereArgs...)
	}

	// 动态排序
	orderClause := "seed_parameters.site_name, seed_parameters.torrent_id"
	switch f.SortProp {
	case "site_count":
		direction := "ASC"
		if f.SortOrder == "descending" {
			direction = "DESC"
		}
		orderClause = fmt.Sprintf("site_count %s, seed_parameters.site_name", direction)
	case "size":
		direction := "ASC"
		if f.SortOrder == "descending" {
			direction = "DESC"
		}
		orderClause = fmt.Sprintf("MAX(t.size) %s, seed_parameters.site_name", direction)
	case "progress":
		direction := "ASC"
		if f.SortOrder == "descending" {
			direction = "DESC"
		}
		orderClause = fmt.Sprintf("MAX(t.progress) %s, seed_parameters.site_name", direction)
	case "title":
		direction := "ASC"
		if f.SortOrder == "descending" {
			direction = "DESC"
		}
		orderClause = fmt.Sprintf("MAX(seed_parameters.title) %s, seed_parameters.site_name", direction)
	}

	var seeds []map[string]any
	offset := (page - 1) * pageSize
	if err := baseQuery.Select(selectCols).
		Group("seed_parameters.torrent_id, seed_parameters.site_name").
		Order(orderClause).
		Offset(offset).Limit(pageSize).
		Find(&seeds).Error; err != nil {
		return nil, 0, 0, fmt.Errorf("查询可选种子列表失败: %w", err)
	}
	return seeds, total, totalSiteCount, nil
}

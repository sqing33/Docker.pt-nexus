package migrationflow

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/pt-nexus/server/internal/platform/logx"
	"github.com/pt-nexus/server/internal/repository"
	acquirefetch "github.com/pt-nexus/server/internal/service/acquire/fetch"
	processingpersist "github.com/pt-nexus/server/internal/service/processing/persist"
	processingshared "github.com/pt-nexus/server/internal/service/processing/shared"
	publishguard "github.com/pt-nexus/server/internal/service/publish/guard"
	publishworkflow "github.com/pt-nexus/server/internal/service/publish/workflow"
	"gorm.io/gorm"
)

const (
	publishQueueLogModule  = "发布-队列"
	queueAutoAddNotRunJSON = `{"success": false, "message": "未执行"}`
)

type publishQueueConfig struct {
	Enabled            bool
	MaxQueueSize       int64
	MaxRetries         int
	MaxRetryDelaySec   int
	MaxWorkers         int
	MonitorIntervalSec int
	RetryDelayBase     int
	TaskCleanupHours   int

	TriggerRecentCountBelow     int
	TriggerUploadSpeedBelowMBps float64
}

// InitPublishQueue 初始化发布队列依赖。
// 参数/返回：queueRepo 用于持久化队列任务；statsRepo 用于读取下载器速度（可为 nil）；无返回值。
// 失败场景：参数为空时仅记录日志并跳过初始化，避免启动阶段 panic。
// 副作用：写入服务内部依赖引用（不启动线程）。
func (s *MigrateService) InitPublishQueue(queueRepo *repository.PublishQueueRepository, statsRepo *repository.StatsRepository) {
	if s == nil {
		return
	}
	if queueRepo == nil {
		logx.Warnf(publishQueueLogModule, "初始化发布队列失败：queueRepo 为空")
		return
	}
	s.queueRepo = queueRepo
	s.statsRepo = statsRepo
}

// SetPublishQueueScheduledSeedContinueHook 注入发布队列“定时发种可继续下一种子”的外部通知回调。
// 触发时机：定时发种队列任务确定性跳过（目标站点已存在、预检查限制等）时调用。
// 参数/返回：fn 接收队列任务 trigger（格式 sched:<taskID>）；无返回值。
// 失败场景：服务为空时忽略。
// 副作用：保存回调引用，队列任务完成时可能触发定时发种调度。
func (s *MigrateService) SetPublishQueueScheduledSeedContinueHook(fn func(trigger string)) {
	if s == nil {
		return
	}
	s.publishQueueScheduledSeedContinueHook = fn
}

// StartPublishQueueWorker 启动发布队列后台监控线程（重复调用仅生效一次）。
// 参数/返回：无参数无返回。
// 失败场景：队列仓储未初始化时会记录日志并直接返回，不会影响主服务启动。
// 副作用：启动 goroutine，周期性领取队列任务并触发发布流程。
func (s *MigrateService) StartPublishQueueWorker() {
	if s == nil {
		return
	}
	s.queueStartOnce.Do(func() {
		if s.queueRepo == nil || s.queueRepo.DB() == nil {
			logx.Warnf(publishQueueLogModule, "发布队列未启动：仓储未初始化")
			return
		}
		s.queueStopCh = make(chan struct{})
		s.queueDoneCh = make(chan struct{})
		go s.runPublishQueueWorker()
	})
}

func (s *MigrateService) runPublishQueueWorker() {
	defer close(s.queueDoneCh)

	cfg := s.resolvePublishQueueConfig()
	intervalSec := clampInt(cfg.MonitorIntervalSec, 5, 3600)
	ticker := time.NewTicker(time.Duration(intervalSec) * time.Second)
	defer ticker.Stop()

	logx.Infof(publishQueueLogModule, "发布队列线程已启动 interval=%ds enabled=%v workers=%d", intervalSec, cfg.Enabled, clampInt(cfg.MaxWorkers, 1, 20))

	lastCleanup := time.Now()
	for {
		select {
		case <-s.queueStopCh:
			logx.Infof(publishQueueLogModule, "发布队列线程已停止")
			return
		case <-ticker.C:
			cfg = s.resolvePublishQueueConfig()
			newInterval := clampInt(cfg.MonitorIntervalSec, 5, 3600)
			if newInterval != intervalSec {
				intervalSec = newInterval
				ticker.Reset(time.Duration(intervalSec) * time.Second)
				logx.Infof(publishQueueLogModule, "队列轮询间隔已更新 interval=%ds", intervalSec)
			}

			if !cfg.Enabled {
				continue
			}

			s.drainPublishQueueOnce(cfg)

			if cfg.TaskCleanupHours > 0 && time.Since(lastCleanup) >= 30*time.Minute {
				lastCleanup = time.Now()
				cutoff := time.Now().Add(-time.Duration(cfg.TaskCleanupHours) * time.Hour)
				if deleted, err := s.queueRepo.CleanupFinishedTasks(cutoff); err != nil {
					logx.Warnf(publishQueueLogModule, "清理旧队列任务失败 err=%v", err)
				} else if deleted > 0 {
					logx.Infof(publishQueueLogModule, "已清理旧队列任务 deleted=%d cutoff=%s", deleted, cutoff.Format(time.RFC3339))
				}
			}
		}
	}
}

// EnqueuePublishQueue 将"选择站点发布"步骤生成的 payload 写入发布队列，等待后台触发。
// 参数/返回：payload 与发布接口一致（支持 targetSites/targetSite），必须包含 task_id 与 upload_data；返回入队结果与 HTTP 状态码。
// 失败场景：参数缺失、上下文过期、队列已满或入库失败时返回对应错误。
// 副作用：写入 publish_queue_tasks 与 publish_logs。
func (s *MigrateService) EnqueuePublishQueue(payload map[string]any) (map[string]any, int) {
	if s == nil || s.queueRepo == nil || s.queueRepo.DB() == nil {
		return map[string]any{"success": false, "message": "队列服务未初始化"}, 500
	}
	if payload == nil {
		payload = map[string]any{}
	}

	cfg := s.resolvePublishQueueConfig()
	if !cfg.Enabled {
		return map[string]any{"success": false, "message": "队列功能已关闭"}, 400
	}

	taskID := strings.TrimSpace(processingshared.ToString(payload["task_id"], processingshared.ToString(payload["taskId"], "")))
	if taskID == "" {
		return map[string]any{"success": false, "message": "缺少 task_id 参数"}, 400
	}

	uploadData, ok := payload["upload_data"].(map[string]any)
	if !ok || uploadData == nil {
		return map[string]any{"success": false, "message": "缺少 upload_data 参数"}, 400
	}

	ctx, ok := s.contextState.Get(taskID)
	if !ok {
		return map[string]any{"success": false, "message": "任务上下文已过期，请重新打开编辑面板后再加入队列"}, 400
	}

	targetSites := processingshared.ToStringSlice(payload["targetSites"])
	if len(targetSites) == 0 {
		targetSites = processingshared.ToStringSlice(payload["target_sites"])
	}
	if len(targetSites) == 0 {
		if single := strings.TrimSpace(processingshared.ToString(payload["targetSite"], "")); single != "" {
			targetSites = []string{single}
		}
	}
	if len(targetSites) == 0 {
		return map[string]any{"success": false, "message": "缺少 targetSites 参数"}, 400
	}

	if cfg.MaxQueueSize > 0 {
		active, err := s.queueRepo.CountActiveTasks()
		if err != nil {
			logx.Warnf(publishQueueLogModule, "统计队列任务失败 err=%v", err)
		} else if active+int64(len(targetSites)) > cfg.MaxQueueSize {
			return map[string]any{"success": false, "message": fmt.Sprintf("队列已满（当前 %d / 上限 %d）", active, cfg.MaxQueueSize)}, 400
		}
	}

	groupID := s.newID("queue")
	now := time.Now()
	nowText := now.Format(repository.PublishQueueTimeLayout)

	sourceSite := strings.TrimSpace(processingshared.ToString(payload["sourceSite"], processingshared.ToString(payload["source_site"], "")))
	if sourceSite == "" {
		sourceSite = strings.TrimSpace(ctx.SourceNickname)
	}
	if sourceSite == "" {
		sourceSite = strings.TrimSpace(ctx.SiteName)
	}

	torrentID := strings.TrimSpace(ctx.TorrentID)
	if torrentID == "" {
		torrentID = strings.TrimSpace(processingshared.ToString(uploadData["torrent_id"], processingshared.ToString(payload["torrent_id"], "")))
	}

	title, subtitle := resolvePublishLogTitleFromUploadData(uploadData, firstNonEmptyString(strings.TrimSpace(ctx.Name), torrentID))
	if title == "" {
		title = strings.TrimSpace(firstNonEmptyString(ctx.Name, torrentID))
	}
	uploadData["title"] = title

	downloaderID := strings.TrimSpace(processingshared.ToString(payload["downloaderId"], processingshared.ToString(payload["downloader_id"], "")))
	if downloaderID == "" {
		downloaderID = strings.TrimSpace(ctx.DownloaderID)
	}

	scene := strings.TrimSpace(processingshared.ToString(payload["publish_scene"], ""))
	trigger := "queue"

	normalizedPayload := map[string]any{}
	for key, value := range payload {
		normalizedPayload[key] = value
	}
	normalizedPayload["publish_trigger"] = trigger
	normalizedPayload["queue_group_id"] = groupID

	uploadBytes, _ := json.Marshal(uploadData)
	ctxBytes, _ := json.Marshal(ctx)

	scheduledAt := (*time.Time)(nil)
	if rawScheduled := strings.TrimSpace(processingshared.ToString(payload["scheduled_at"], "")); rawScheduled != "" {
		if t, err := time.Parse(time.RFC3339, rawScheduled); err == nil {
			scheduledAt = &t
		} else if t, err := time.Parse("2006-01-02 15:04:05", rawScheduled); err == nil {
			scheduledAt = &t
		}
	}

	// 可发种时间检查：未到可发种时间不能发种；仅当计划发布时间不早于可发种时间时允许入队等待。
	if publishAt, notReached := s.resolveSeedPublishAtNotReached(torrentID, now); notReached && (scheduledAt == nil || scheduledAt.Before(publishAt)) {
		return map[string]any{"success": false, "message": publishAtBlockMessage(publishAt)}, 400
	}

	queueTasks := make([]repository.PublishQueueTask, 0, len(targetSites))
	for _, target := range targetSites {
		targetSite := strings.TrimSpace(target)
		if targetSite == "" {
			continue
		}

		taskPayload := map[string]any{}
		for key, value := range normalizedPayload {
			taskPayload[key] = value
		}
		taskPayload["targetSite"] = targetSite
		delete(taskPayload, "targetSites")
		delete(taskPayload, "target_sites")

		taskPayloadBytes, _ := json.Marshal(taskPayload)

		record := repository.PublishQueueTask{
			GroupID:        groupID,
			Status:         repository.PublishQueueStatusQueued,
			TaskID:         taskID,
			Trigger:        trigger,
			Scene:          scene,
			TorrentID:      torrentID,
			SourceSite:     sourceSite,
			TargetSite:     targetSite,
			DownloaderID:   downloaderID,
			Title:          title,
			Subtitle:       subtitle,
			PayloadJSON:    string(taskPayloadBytes),
			UploadDataJSON: string(uploadBytes),
			ContextJSON:    string(ctxBytes),
			AttemptCount:   0,
			NextRunAt:      nil,
			ScheduledAt:    nil,
			StartedAt:      nil,
			FinishedAt:     nil,
			LastError:      "",
			LastResult:     "",
			CreatedAt:      nowText,
			UpdatedAt:      nowText,
		}

		if scheduledAt != nil {
			value := scheduledAt.Format(repository.PublishQueueTimeLayout)
			record.ScheduledAt = &value
			record.NextRunAt = &value
		} else {
			value := nowText
			record.NextRunAt = &value
		}

		queueTasks = append(queueTasks, record)
	}

	if len(queueTasks) == 0 {
		return map[string]any{"success": false, "message": "没有可入队的站点"}, 400
	}

	createdTasks, err := s.queueRepo.EnqueueTasks(queueTasks)
	if err != nil {
		return map[string]any{"success": false, "message": "入队失败: " + err.Error()}, 500
	}
	s.insertQueuedPublishLogs(createdTasks)

	logx.Infof(publishQueueLogModule, "已入队 group_id=%s task_id=%s torrent_id=%s sites=%d", groupID, taskID, torrentID, len(queueTasks))
	return map[string]any{
		"success":  true,
		"message":  fmt.Sprintf("已加入队列（%d 个站点）", len(queueTasks)),
		"group_id": groupID,
		"count":    len(queueTasks),
	}, 200
}

// EnqueuePublishQueueBatch 将"一站多种"批量转种请求批量写入发布队列。
// 参数/返回：payload 需包含 target_site_name 与 seeds；返回批量入队统计（group_id/publish_trigger/requested/queued/skipped）。
// 失败场景：参数缺失、队列未初始化/关闭、队列上限不足、入库失败时返回 4xx/5xx。
// 副作用：写入 publish_queue_tasks 与 publish_logs。
func (s *MigrateService) EnqueuePublishQueueBatch(payload map[string]any) (map[string]any, int) {
	if s == nil || s.queueRepo == nil || s.queueRepo.DB() == nil {
		return map[string]any{"success": false, "message": "队列服务未初始化"}, 500
	}
	if payload == nil {
		payload = map[string]any{}
	}

	cfg := s.resolvePublishQueueConfig()
	if !cfg.Enabled {
		return map[string]any{"success": false, "message": "队列功能已关闭"}, 400
	}

	targetSite := strings.TrimSpace(processingshared.ToString(payload["target_site_name"], processingshared.ToString(payload["targetSite"], processingshared.ToString(payload["target_site"], ""))))
	if targetSite == "" {
		return map[string]any{"success": false, "message": "缺少 target_site_name 参数"}, 400
	}

	rawSeeds, ok := payload["seeds"].([]any)
	if !ok || len(rawSeeds) == 0 {
		return map[string]any{"success": false, "message": "缺少 seeds 参数"}, 400
	}

	if cfg.MaxQueueSize > 0 {
		active, err := s.queueRepo.CountActiveTasks()
		if err != nil {
			logx.Warnf(publishQueueLogModule, "统计队列任务失败 err=%v", err)
		} else if active+int64(len(rawSeeds)) > cfg.MaxQueueSize {
			return map[string]any{"success": false, "message": fmt.Sprintf("队列已满（当前 %d / 上限 %d）", active, cfg.MaxQueueSize)}, 400
		}
	}

	publishTrigger := strings.TrimSpace(processingshared.ToString(payload["publish_trigger"], ""))
	if publishTrigger == "" {
		var triggerErr error
		publishTrigger, _, triggerErr = s.NextBatchCrossSeedTrigger()
		if strings.TrimSpace(publishTrigger) == "" {
			publishTrigger = batchCrossSeedTriggerPrefix + "1"
		}
		if triggerErr != nil {
			logx.Warnf(publishQueueLogModule, "计算批量触发标识失败，已回退 trigger=%s err=%v", publishTrigger, triggerErr)
		}
	}

	scene := strings.TrimSpace(processingshared.ToString(payload["publish_scene"], "multi_torrent"))
	if scene == "" {
		scene = "multi_torrent"
	}
	groupID := s.newID("queue")
	now := time.Now()
	nowText := now.Format(repository.PublishQueueTimeLayout)
	scheduledAt := (*time.Time)(nil)
	if rawScheduled := strings.TrimSpace(processingshared.ToString(payload["scheduled_at"], "")); rawScheduled != "" {
		if t, err := time.Parse(time.RFC3339, rawScheduled); err == nil {
			scheduledAt = &t
		} else if t, err := time.Parse(repository.PublishQueueTimeLayout, rawScheduled); err == nil {
			scheduledAt = &t
		}
	}

	queueTasks := make([]repository.PublishQueueTask, 0, len(rawSeeds))
	skipped := 0

	for idx, raw := range rawSeeds {
		seed, ok := raw.(map[string]any)
		if !ok || seed == nil {
			skipped++
			s.insertBatchQueueSkipLog(ExternalPublishLogInput{
				Trigger:       publishTrigger,
				Scene:         scene,
				QueueGroupID:  groupID,
				TargetSite:    targetSite,
				Status:        "failed",
				Logs:          "批量参数异常：seeds 项不是对象",
				AutoAddResult: queueAutoAddNotRunJSON,
			})
			continue
		}

		torrentID := strings.TrimSpace(processingshared.ToString(seed["torrent_id"], ""))
		siteName := strings.TrimSpace(processingshared.ToString(seed["site_name"], ""))
		sourceSite := strings.TrimSpace(processingshared.ToString(seed["nickname"], siteName))
		downloaderID := strings.TrimSpace(processingshared.ToString(seed["downloader_id"], ""))
		seedSavePath := strings.TrimSpace(processingshared.ToString(seed["save_path"], processingshared.ToString(seed["savePath"], "")))
		seedTorrentURL := strings.TrimSpace(processingshared.ToString(seed["torrent_url"], ""))

		if torrentID == "" || siteName == "" {
			skipped++
			s.insertBatchQueueSkipLog(ExternalPublishLogInput{
				Trigger:       publishTrigger,
				Scene:         scene,
				QueueGroupID:  groupID,
				TorrentID:     torrentID,
				SourceSite:    sourceSite,
				TargetSite:    targetSite,
				DownloaderID:  downloaderID,
				Title:         firstNonEmptyString(strings.TrimSpace(torrentID), fmt.Sprintf("seed-%d", idx+1)),
				Status:        "failed",
				Logs:          "缺少 torrent_id 或 site_name",
				AutoAddResult: queueAutoAddNotRunJSON,
			})
			continue
		}

		// 可发种时间检查：未到可发种时间不能发种；仅当计划发布时间不早于可发种时间时允许入队等待。
		if publishAt, notReached := s.resolveSeedPublishAtNotReached(torrentID, now); notReached && (scheduledAt == nil || scheduledAt.Before(publishAt)) {
			skipped++
			logx.Infof(publishQueueLogModule, "种子未到可发种时间，跳过入队 group_id=%s torrent_id=%s publish_at=%s", groupID, torrentID, formatSeedPublishAt(publishAt))
			s.insertBatchQueueSkipLog(ExternalPublishLogInput{
				Trigger:       publishTrigger,
				Scene:         scene,
				QueueGroupID:  groupID,
				TorrentID:     torrentID,
				SourceSite:    sourceSite,
				TargetSite:    targetSite,
				DownloaderID:  downloaderID,
				Title:         firstNonEmptyString(strings.TrimSpace(torrentID), fmt.Sprintf("seed-%d", idx+1)),
				Status:        "failed",
				Logs:          publishAtBlockMessage(publishAt),
				AutoAddResult: queueAutoAddNotRunJSON,
			})
			continue
		}

		lookup, err := processingpersist.LookupSeedForMigration(
			processingpersist.DBSeedLookupInput{TorrentID: torrentID, SiteName: siteName},
			s.repo,
		)
		if err != nil {
			skipped++
			message := "数据库读取失败: " + err.Error()
			if errors.Is(err, gorm.ErrRecordNotFound) {
				message = "数据库中未找到种子信息"
			}
			s.insertBatchQueueSkipLog(ExternalPublishLogInput{
				Trigger:       publishTrigger,
				Scene:         scene,
				QueueGroupID:  groupID,
				TorrentID:     torrentID,
				SourceSite:    sourceSite,
				TargetSite:    targetSite,
				DownloaderID:  downloaderID,
				Title:         torrentID,
				Status:        "failed",
				Logs:          message,
				AutoAddResult: queueAutoAddNotRunJSON,
			})
			continue
		}

		uploadData := map[string]any{}
		for key, value := range lookup.Normalized {
			uploadData[key] = value
		}
		if strings.TrimSpace(processingshared.ToString(uploadData["save_path"], "")) == "" && seedSavePath != "" {
			uploadData["save_path"] = seedSavePath
		}
		if seedTorrentURL != "" {
			uploadData["torrent_url"] = seedTorrentURL
		}

		if strings.TrimSpace(sourceSite) == "" {
			sourceSite = firstNonEmptyString(strings.TrimSpace(lookup.Nickname), strings.TrimSpace(lookup.SiteName), strings.TrimSpace(siteName))
		}
		if strings.TrimSpace(downloaderID) == "" {
			downloaderID = firstNonEmptyString(
				strings.TrimSpace(processingshared.ToString(uploadData["downloader_id"], "")),
				strings.TrimSpace(lookup.DownloaderID),
			)
		}
		if strings.TrimSpace(downloaderID) != "" {
			uploadData["downloader_id"] = downloaderID
		}

		title, subtitle := resolvePublishLogTitleFromUploadData(uploadData, torrentID)
		if title == "" {
			title = strings.TrimSpace(torrentID)
		}
		uploadData["title"] = title

		ctxTaskID := s.newID("ctx")
		ctx := publishworkflow.BuildContextFromDBRow(
			ctxTaskID,
			torrentID,
			strings.TrimSpace(firstNonEmptyString(lookup.SiteName, siteName)),
			strings.TrimSpace(lookup.Hash),
			strings.TrimSpace(firstNonEmptyString(lookup.Name, title)),
			strings.TrimSpace(firstNonEmptyString(processingshared.ToString(uploadData["save_path"], ""), seedSavePath, lookup.SavePath)),
			downloaderID,
			sourceSite,
			torrentID,
		)

		taskPayload := map[string]any{
			"task_id":                ctxTaskID,
			"upload_data":            uploadData,
			"targetSite":             targetSite,
			"sourceSite":             sourceSite,
			"source_site":            sourceSite,
			"torrent_id":             torrentID,
			"hash":                   strings.TrimSpace(lookup.Hash),
			"name":                   strings.TrimSpace(firstNonEmptyString(lookup.Name, title)),
			"downloaderId":           downloaderID,
			"auto_add_to_downloader": true,
			"publish_scene":          scene,
			"publish_trigger":        publishTrigger,
			"queue_group_id":         groupID,
		}
		if value, exists := payload["auto_add_existing_to_downloader"]; exists {
			taskPayload["auto_add_existing_to_downloader"] = value
		}
		if value, exists := payload["auto_update_existing_torrent"]; exists {
			taskPayload["auto_update_existing_torrent"] = value
		}

		taskPayloadBytes, _ := json.Marshal(taskPayload)
		uploadBytes, _ := json.Marshal(uploadData)
		ctxBytes, _ := json.Marshal(ctx)

		nextRunAt := nowText
		scheduledAtText := (*string)(nil)
		if scheduledAt != nil {
			nextRunAt = scheduledAt.Format(repository.PublishQueueTimeLayout)
			value := nextRunAt
			scheduledAtText = &value
		}
		queueTasks = append(queueTasks, repository.PublishQueueTask{
			GroupID:        groupID,
			Status:         repository.PublishQueueStatusQueued,
			TaskID:         ctxTaskID,
			Trigger:        publishTrigger,
			Scene:          scene,
			TorrentID:      torrentID,
			SourceSite:     sourceSite,
			TargetSite:     targetSite,
			DownloaderID:   downloaderID,
			Title:          title,
			Subtitle:       subtitle,
			PayloadJSON:    string(taskPayloadBytes),
			UploadDataJSON: string(uploadBytes),
			ContextJSON:    string(ctxBytes),
			AttemptCount:   0,
			NextRunAt:      &nextRunAt,
			ScheduledAt:    scheduledAtText,
			StartedAt:      nil,
			FinishedAt:     nil,
			LastError:      "",
			LastResult:     "",
			CreatedAt:      nowText,
			UpdatedAt:      nowText,
		})
	}

	if len(queueTasks) == 0 {
		return map[string]any{
			"success":         false,
			"message":         "没有可入队的种子",
			"group_id":        groupID,
			"publish_trigger": publishTrigger,
			"requested":       len(rawSeeds),
			"queued":          0,
			"skipped":         skipped,
		}, 400
	}

	createdTasks, err := s.queueRepo.EnqueueTasks(queueTasks)
	if err != nil {
		return map[string]any{"success": false, "message": "入队失败: " + err.Error()}, 500
	}
	s.insertQueuedPublishLogs(createdTasks)

	queuedCount := len(createdTasks)
	skipped = len(rawSeeds) - queuedCount
	message := fmt.Sprintf("已加入队列（%d/%d）", queuedCount, len(rawSeeds))

	logx.Infof(publishQueueLogModule, "批量入队完成 group_id=%s trigger=%s target_site=%s requested=%d queued=%d skipped=%d", groupID, publishTrigger, targetSite, len(rawSeeds), queuedCount, skipped)
	return map[string]any{
		"success":         true,
		"message":         message,
		"group_id":        groupID,
		"publish_trigger": publishTrigger,
		"requested":       len(rawSeeds),
		"queued":          queuedCount,
		"skipped":         skipped,
	}, 200
}

// EnqueuePublishQueueBatchByNames 根据种子名称批量查找 seed_parameters 并加入发种队列。
// 参数/返回：payload 需包含 torrent_names([]string) 和 target_site_name；返回批量入队统计与批次标识。
// 失败场景：参数缺失、队列未初始化、seed_parameters 中未找到对应记录会跳过。
// 副作用：写入 publish_queue_tasks 与 publish_logs。
func (s *MigrateService) EnqueuePublishQueueBatchByNames(payload map[string]any) (map[string]any, int) {
	if s == nil || s.queueRepo == nil || s.queueRepo.DB() == nil {
		return map[string]any{"success": false, "message": "队列服务未初始化"}, 500
	}
	if payload == nil {
		payload = map[string]any{}
	}

	targetSite := strings.TrimSpace(processingshared.ToString(payload["target_site_name"], ""))
	if targetSite == "" {
		return map[string]any{"success": false, "message": "缺少 target_site_name 参数"}, 400
	}

	rawNames, ok := payload["torrent_names"].([]any)
	if !ok || len(rawNames) == 0 {
		return map[string]any{"success": false, "message": "缺少 torrent_names 参数"}, 400
	}

	// Deduplicate names
	seenNames := map[string]struct{}{}
	uniqueNames := make([]string, 0, len(rawNames))
	for _, raw := range rawNames {
		name := strings.TrimSpace(processingshared.ToString(raw, ""))
		if name == "" {
			continue
		}
		if _, exists := seenNames[name]; exists {
			continue
		}
		seenNames[name] = struct{}{}
		uniqueNames = append(uniqueNames, name)
	}

	if len(uniqueNames) == 0 {
		return map[string]any{"success": false, "message": "没有有效的种子名称"}, 400
	}

	// Resolve each name to seed_parameters entry
	seeds := make([]any, 0, len(uniqueNames))
	unresolvedNames := make([]string, 0)

	for _, name := range uniqueNames {
		entries, err := s.repo.GetSeedParametersByName(name)
		if err != nil || len(entries) == 0 {
			unresolvedNames = append(unresolvedNames, name)
			continue
		}

		// Pick the best entry: prefer one that is not the target site
		var best map[string]any
		for _, entry := range entries {
			entrySite := strings.TrimSpace(processingshared.ToString(entry["site_name"], ""))
			if entrySite == "" || entrySite == targetSite {
				continue
			}
			best = entry
			break
		}
		// If no non-target entry found, try first entry
		if best == nil && len(entries) > 0 {
			best = entries[0]
		}
		if best == nil {
			unresolvedNames = append(unresolvedNames, name)
			continue
		}

		torrentID := strings.TrimSpace(processingshared.ToString(best["torrent_id"], ""))
		siteName := strings.TrimSpace(processingshared.ToString(best["site_name"], ""))
		if torrentID == "" || siteName == "" {
			unresolvedNames = append(unresolvedNames, name)
			continue
		}

		seeds = append(seeds, map[string]any{
			"torrent_id":    torrentID,
			"site_name":     siteName,
			"nickname":      processingshared.ToString(best["nickname"], siteName),
			"hash":          processingshared.ToString(best["hash"], ""),
			"downloader_id": processingshared.ToString(best["downloader_id"], ""),
		})
	}

	if len(seeds) == 0 {
		return map[string]any{
			"success":          false,
			"message":          fmt.Sprintf("所有 %d 个种子均未找到 seed_parameters 记录", len(uniqueNames)),
			"unresolved_names": unresolvedNames,
		}, 400
	}

	// Delegate to existing batch enqueue
	delegatePayload := map[string]any{
		"target_site_name": targetSite,
		"seeds":            seeds,
		"publish_scene":    processingshared.ToString(payload["publish_scene"], "multi_site"),
	}
	if trigger, ok := payload["publish_trigger"]; ok {
		delegatePayload["publish_trigger"] = trigger
	}

	result, status := s.EnqueuePublishQueueBatch(delegatePayload)

	// Enrich response with unresolved info
	if unresolvedNames != nil {
		result["unresolved_names"] = unresolvedNames
	}
	result["requested_names"] = len(uniqueNames)

	return result, status
}

// DeleteQueuedPublishTask 将待发布的 queued 任务标记为 cancelled（供日志页"删除"操作调用）。
// 参数/返回：queueTaskID 为队列任务主键；返回标准响应与状态码。
// 失败场景：任务不存在返回 404；任务非 queued 返回 409；数据库更新失败返回 500。
// 副作用：更新 publish_queue_tasks 与 publish_logs。
func (s *MigrateService) DeleteQueuedPublishTask(queueTaskID int64) (map[string]any, int) {
	if s == nil || s.queueRepo == nil || s.queueRepo.DB() == nil {
		return map[string]any{"success": false, "message": "队列服务未初始化"}, 500
	}
	if queueTaskID <= 0 {
		return map[string]any{"success": false, "message": "缺少有效的 queue_task_id"}, 400
	}

	task, ok, err := s.queueRepo.FindTaskByID(queueTaskID)
	if err != nil {
		return map[string]any{"success": false, "message": "查询队列任务失败: " + err.Error()}, 500
	}
	if !ok || task == nil {
		return map[string]any{"success": false, "message": "队列任务不存在"}, 404
	}
	if strings.TrimSpace(task.Status) != repository.PublishQueueStatusQueued {
		return map[string]any{"success": false, "message": "仅待发布任务支持删除"}, 409
	}

	reason := "已从队列移除"
	if err := s.queueRepo.CancelQueuedTask(queueTaskID, reason); err != nil {
		switch {
		case errors.Is(err, repository.ErrPublishQueueTaskNotFound):
			return map[string]any{"success": false, "message": "队列任务不存在"}, 404
		case errors.Is(err, repository.ErrPublishQueueTaskNotQueued):
			return map[string]any{"success": false, "message": "仅待发布任务支持删除"}, 409
		default:
			return map[string]any{"success": false, "message": "删除队列任务失败: " + err.Error()}, 500
		}
	}

	if s.publishLogRepo != nil {
		if updateErr := s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(queueTaskID, repository.PublishQueueStatusCancelled, reason); updateErr != nil {
			logx.Warnf(publishLogModule, "更新已取消日志失败 queue_task_id=%d err=%v", queueTaskID, updateErr)
		}
	}

	logx.Infof(publishQueueLogModule, "队列任务已删除 queue_task_id=%d group_id=%s target_site=%s", queueTaskID, strings.TrimSpace(task.GroupID), strings.TrimSpace(task.TargetSite))
	return map[string]any{"success": true, "message": "队列任务已移除"}, 200
}

func (s *MigrateService) insertQueuedPublishLogs(tasks []repository.PublishQueueTask) {
	if s == nil || s.publishLogRepo == nil || len(tasks) == 0 {
		return
	}
	for _, task := range tasks {
		if task.ID <= 0 {
			continue
		}
		taskID := task.ID
		message := "等待发布"
		if task.ScheduledAt != nil && strings.TrimSpace(*task.ScheduledAt) != "" {
			message = "等待发布（计划时间：" + strings.TrimSpace(*task.ScheduledAt) + "）"
		}

		entry := repository.PublishLogEntry{
			Trigger:       strings.TrimSpace(task.Trigger),
			Scene:         strings.TrimSpace(task.Scene),
			QueueTaskID:   &taskID,
			QueueGroupID:  strings.TrimSpace(task.GroupID),
			TaskID:        strings.TrimSpace(task.TaskID),
			TorrentID:     strings.TrimSpace(task.TorrentID),
			SourceSite:    s.normalizePublishLogSourceSite(task.SourceSite),
			TargetSite:    strings.TrimSpace(task.TargetSite),
			DownloaderID:  strings.TrimSpace(task.DownloaderID),
			Title:         strings.TrimSpace(task.Title),
			Subtitle:      strings.TrimSpace(task.Subtitle),
			Status:        repository.PublishQueueStatusQueued,
			ResultURL:     "",
			Logs:          message,
			AutoAddResult: "",
			CostMS:        0,
			CreatedAt:     task.CreatedAt,
			UpdatedAt:     task.UpdatedAt,
		}

		if _, err := s.publishLogRepo.Insert(&entry); err != nil {
			logx.Warnf(publishLogModule, "写入队列等待日志失败 queue_task_id=%d target=%s err=%v", taskID, task.TargetSite, err)
		}
	}
}

func (s *MigrateService) insertBatchQueueSkipLog(input ExternalPublishLogInput) {
	if s == nil || s.publishLogRepo == nil {
		return
	}
	if strings.TrimSpace(input.Status) == "" {
		input.Status = "failed"
	}
	if strings.TrimSpace(input.AutoAddResult) == "" {
		input.AutoAddResult = queueAutoAddNotRunJSON
	}
	if strings.TrimSpace(input.Trigger) == "" {
		input.Trigger = "queue"
	}
	if strings.TrimSpace(input.Scene) == "" {
		input.Scene = "multi_torrent"
	}
	if strings.TrimSpace(input.Title) == "" {
		input.Title = strings.TrimSpace(firstNonEmptyString(input.TorrentID, "-"))
	}
	if err := s.InsertExternalPublishLog(input); err != nil {
		logx.Warnf(
			publishQueueLogModule,
			"写入批量入队失败日志失败 trigger=%s group_id=%s torrent_id=%s target=%s err=%v",
			input.Trigger,
			input.QueueGroupID,
			input.TorrentID,
			input.TargetSite,
			err,
		)
	}
}

func (s *MigrateService) drainPublishQueueOnce(cfg publishQueueConfig) {
	if s == nil || s.queueRepo == nil {
		return
	}

	workers := clampInt(cfg.MaxWorkers, 1, 20)
	now := time.Now()

	latestSpeeds := map[string]float64{}
	if cfg.TriggerUploadSpeedBelowMBps > 0 && s.statsRepo != nil {
		if rows, err := s.statsRepo.QueryLatestSpeeds(); err == nil {
			for _, row := range rows {
				id := strings.TrimSpace(row.DownloaderID)
				if id == "" {
					continue
				}
				latestSpeeds[id] = row.UploadSpeed
			}
		}
	}

	for i := 0; i < workers; i++ {
		task, ok, err := s.queueRepo.ClaimNextRunnableTask(now)
		if err != nil {
			logx.Warnf(publishQueueLogModule, "领取队列任务失败 err=%v", err)
			return
		}
		if !ok || task == nil {
			return
		}
		s.executePublishQueueTask(cfg, *task, latestSpeeds)
	}
}

func (s *MigrateService) executePublishQueueTask(cfg publishQueueConfig, taskRecord repository.PublishQueueTask, latestSpeeds map[string]float64) {
	if s == nil || s.queueRepo == nil {
		return
	}

	taskID := taskRecord.ID
	if taskID <= 0 {
		return
	}

	payload := map[string]any{}
	if err := json.Unmarshal([]byte(taskRecord.PayloadJSON), &payload); err != nil {
		reason := "payload_json 解析失败: " + err.Error()
		_ = s.queueRepo.UpdateTaskAfterFailure(taskID, taskRecord.AttemptCount+1, nil, reason, "")
		if s.publishLogRepo != nil {
			_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "failed", reason)
		}
		return
	}

	uploadData := map[string]any{}
	_ = json.Unmarshal([]byte(taskRecord.UploadDataJSON), &uploadData)
	ctx := publishworkflow.Context{}
	_ = json.Unmarshal([]byte(taskRecord.ContextJSON), &ctx)

	execTaskID := strings.TrimSpace(taskRecord.TaskID)
	if execTaskID == "" {
		execTaskID = fmt.Sprintf("queue-%d", taskID)
	}
	if hydratedTaskID := s.hydrateQueuePublishLogContext(taskRecord, payload, uploadData, ctx, execTaskID); hydratedTaskID != "" {
		execTaskID = hydratedTaskID
	}

	payload["publish_trigger"] = strings.TrimSpace(firstNonEmptyString(taskRecord.Trigger, "queue"))
	payload["queue_task_id"] = taskID
	payload["queue_group_id"] = strings.TrimSpace(taskRecord.GroupID)
	payload["targetSite"] = strings.TrimSpace(processingshared.ToString(payload["targetSite"], taskRecord.TargetSite))
	payload["upload_data"] = uploadData
	payload = s.normalizePublishPayloadWithCrossSeedDefaults(payload)

	downloaderID := s.resolveQueueTaskDownloaderID(taskRecord, payload, ctx)
	if strings.TrimSpace(downloaderID) != "" {
		rootConfig := map[string]any{}
		if s.cfg != nil {
			rootConfig = s.cfg.Get()
		}
		stats, err := publishguard.CheckDownloaderGateStats(downloaderID, rootConfig)
		if err != nil {
			nextRunAt := time.Now().Add(time.Duration(clampInt(cfg.MonitorIntervalSec, 5, 3600)) * time.Second)
			reason := "预检查统计失败: " + err.Error()
			_ = s.queueRepo.UpdateTaskAfterRequeue(taskID, nextRunAt, reason, "")
			if s.publishLogRepo != nil {
				_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "queued", reason)
			}
			logx.Warnf(publishQueueLogModule, "队列任务等待预检查恢复 id=%d downloader_id=%s err=%v", taskID, downloaderID, err)
			return
		}
		if !stats.CanContinue {
			nextRunAt := time.Now().Add(time.Duration(clampInt(cfg.MonitorIntervalSec, 5, 3600)) * time.Second)
			reason := strings.TrimSpace(stats.Message)
			if reason == "" {
				reason = "已触发限制"
			}
			waitMessage := "发布前限制: " + reason
			_ = s.queueRepo.UpdateTaskAfterRequeue(taskID, nextRunAt, waitMessage, "")
			if s.publishLogRepo != nil {
				_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "queued", waitMessage)
			}
			logx.Infof(publishQueueLogModule, "队列任务等待限制解除 id=%d downloader_id=%s next_run_at=%s", taskID, downloaderID, nextRunAt.Format(time.RFC3339))
			return
		}

		recentOK := false
		if cfg.TriggerRecentCountBelow > 0 {
			recentOK = stats.RecentCount < cfg.TriggerRecentCountBelow
		}

		speedOK := false
		if cfg.TriggerUploadSpeedBelowMBps > 0 {
			thresholdBytes := cfg.TriggerUploadSpeedBelowMBps * 1024 * 1024
			currentSpeed := latestSpeeds[strings.TrimSpace(downloaderID)]
			speedOK = currentSpeed <= thresholdBytes
		}

		if cfg.TriggerRecentCountBelow <= 0 && cfg.TriggerUploadSpeedBelowMBps <= 0 {
			recentOK = true
		}

		if !recentOK && !speedOK {
			nextRunAt := time.Now().Add(time.Duration(clampInt(cfg.MonitorIntervalSec, 5, 3600)) * time.Second)
			reason := "等待触发条件"
			_ = s.queueRepo.UpdateTaskAfterRequeue(taskID, nextRunAt, reason, "")
			if s.publishLogRepo != nil {
				_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "queued", reason)
			}
			return
		}
	}

	targetSite := strings.TrimSpace(processingshared.ToString(payload["targetSite"], taskRecord.TargetSite))
	torrentID := strings.TrimSpace(processingshared.ToString(payload["torrent_id"], taskRecord.TorrentID))
	if torrentID == "" {
		torrentID = strings.TrimSpace(processingshared.ToString(uploadData["torrent_id"], ctx.TorrentID))
	}

	// 可发种时间检查：未到可发种时间不能发种，任务重新排队等待到可发种时间。
	if publishAt, notReached := s.resolveSeedPublishAtNotReached(torrentID, time.Now()); notReached {
		reason := publishAtBlockMessage(publishAt)
		_ = s.queueRepo.UpdateTaskAfterRequeue(taskID, publishAt, reason, "")
		if s.publishLogRepo != nil {
			_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "queued", reason)
		}
		logx.Infof(publishQueueLogModule, "队列任务等待可发种时间 id=%d torrent_id=%s publish_at=%s", taskID, torrentID, formatSeedPublishAt(publishAt))
		return
	}

	logx.Infof(publishQueueLogModule, "开始执行队列任务 id=%d torrent_id=%s target_site=%s attempt=%d", taskID, torrentID, targetSite, taskRecord.AttemptCount)

	startedAt := time.Now()
	rootConfig := map[string]any{}
	if s.cfg != nil {
		rootConfig = s.cfg.Get()
	}
	result, status := publishworkflow.ExecutePublishWithContext(
		publishworkflow.PublishWithContextInput{
			TargetSite:          targetSite,
			TaskID:              execTaskID,
			Payload:             payload,
			UploadData:          uploadData,
			Context:             ctx,
			TorrentPath:         "",
			DefaultDownloaderID: s.resolveDefaultPublishDownloaderID(),
			RootConfig:          rootConfig,
		},
		publishworkflow.PublishWithContextDeps{
			GetSiteByName: s.repo.GetSiteByName,
			ResolveTorrentPath: func(ctx publishworkflow.Context) string {
				return acquirefetch.ResolvePublishTorrentPath(s.repo, acquirefetch.ResolvePublishTorrentPathInput{
					OriginalTorrentPath: ctx.OriginalTorrentPath,
					TorrentDir:          ctx.TorrentDir,
					SiteName:            ctx.SiteName,
					TorrentID:           ctx.TorrentID,
					SourceNickname:      ctx.SourceNickname,
					SourceDetailURL:     ctx.SourceDetailURL,
				})
			},
			AddToDownloader:                   s.AddToDownloader,
			FindSiteNicknameByGroup:           s.repo.FindSiteNicknameByGroup,
			IsTransferForbiddenByOfficialSite: s.repo.IsTransferForbiddenByOfficialSite,
		},
	)
	cost := time.Since(startedAt)
	s.appendPublishLog(payload, execTaskID, torrentID, result, status, cost)

	encodedResult, _ := json.Marshal(result)
	resultText := strings.TrimSpace(string(encodedResult))
	logText := strings.TrimSpace(processingshared.ToString(result["logs"], processingshared.ToString(result["message"], "")))

	success := processingshared.ToBool(result["success"])
	isPreCheck := processingshared.ToBool(result["pre_check"])
	limitReached := processingshared.ToBool(result["limit_reached"])

	if success && status < 400 {
		if err := s.queueRepo.UpdateTaskAfterSuccess(taskID, resultText); err != nil {
			logx.Warnf(publishQueueLogModule, "标记任务成功失败 id=%d err=%v", taskID, err)
		}
		if processingshared.ToBool(result["is_existing_torrent"]) {
			s.notifyScheduledSeedContinue(taskRecord, "目标站点已存在")
		}
		logx.Infof(publishQueueLogModule, "队列任务完成 id=%d success=true status=%d", taskID, status)
		return
	}

	if isPreCheck && limitReached {
		_ = s.queueRepo.UpdateTaskAfterFailure(taskID, taskRecord.AttemptCount+1, nil, logText, resultText)
		if s.publishLogRepo != nil {
			_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "pre_check_limit", logText)
		}
		logx.Warnf(publishQueueLogModule, "队列任务失败（预检查限制） id=%d", taskID)
		// 定时发种场景下预检查限制为确定性失败，通知调度器立即继续处理下一个种子
		s.notifyScheduledSeedContinue(taskRecord, "预检查限制: "+strings.TrimSpace(logText))
		return
	}

	if status >= 400 && status < 500 {
		reason := fmt.Sprintf("请求失败 status=%d: %s", status, logText)
		_ = s.queueRepo.UpdateTaskAfterFailure(taskID, taskRecord.AttemptCount+1, nil, reason, resultText)
		if s.publishLogRepo != nil {
			_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "failed", reason)
		}
		logx.Warnf(publishQueueLogModule, "队列任务失败（不可重试） id=%d status=%d", taskID, status)
		return
	}

	attempt := taskRecord.AttemptCount + 1
	if cfg.MaxRetries >= 0 && attempt > cfg.MaxRetries {
		reason := fmt.Sprintf("超过最大重试次数(%d): %s", cfg.MaxRetries, logText)
		_ = s.queueRepo.UpdateTaskAfterFailure(taskID, attempt, nil, reason, resultText)
		if s.publishLogRepo != nil {
			_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "failed", reason)
		}
		logx.Warnf(publishQueueLogModule, "队列任务失败（达到最大重试） id=%d attempts=%d", taskID, attempt)
		return
	}

	delaySec := computeBackoffSeconds(cfg.RetryDelayBase, attempt, cfg.MaxRetryDelaySec)
	nextRunAt := time.Now().Add(time.Duration(delaySec) * time.Second)
	_ = s.queueRepo.UpdateTaskAfterFailure(taskID, attempt, &nextRunAt, logText, resultText)
	if s.publishLogRepo != nil {
		_ = s.publishLogRepo.UpdateStatusAndLogsByQueueTaskID(taskID, "queued", logText)
	}
	logx.Warnf(publishQueueLogModule, "队列任务失败，已重试入队 id=%d attempt=%d next_run_at=%s", taskID, attempt, nextRunAt.Format(time.RFC3339))
}

func (s *MigrateService) hydrateQueuePublishLogContext(taskRecord repository.PublishQueueTask, payload map[string]any, uploadData map[string]any, ctx publishworkflow.Context, fallbackTaskID string) string {
	if payload == nil {
		return strings.TrimSpace(fallbackTaskID)
	}
	if uploadData == nil {
		uploadData = map[string]any{}
	}

	execTaskID := strings.TrimSpace(firstNonEmptyString(ctx.TaskID, taskRecord.TaskID, fallbackTaskID))
	if execTaskID != "" {
		payload["task_id"] = execTaskID
	}

	torrentID := strings.TrimSpace(firstNonEmptyString(
		taskRecord.TorrentID,
		ctx.TorrentID,
		processingshared.ToString(payload["torrent_id"], ""),
		processingshared.ToString(uploadData["torrent_id"], ""),
	))
	if torrentID != "" {
		payload["torrent_id"] = torrentID
		uploadData["torrent_id"] = torrentID
	}

	sourceSite := strings.TrimSpace(firstNonEmptyString(
		taskRecord.SourceSite,
		processingshared.ToString(payload["sourceSite"], ""),
		processingshared.ToString(payload["source_site"], ""),
		ctx.SourceNickname,
		ctx.SiteName,
	))
	if sourceSite != "" {
		payload["sourceSite"] = sourceSite
		payload["source_site"] = sourceSite
	}

	name := strings.TrimSpace(firstNonEmptyString(
		processingshared.ToString(uploadData["name"], ""),
		processingshared.ToString(payload["name"], ""),
		ctx.Name,
		taskRecord.Title,
	))
	if name != "" {
		payload["name"] = name
		uploadData["name"] = name
	}

	hash := strings.TrimSpace(firstNonEmptyString(
		processingshared.ToString(uploadData["hash"], ""),
		processingshared.ToString(payload["hash"], ""),
		ctx.Hash,
	))
	if hash != "" {
		payload["hash"] = hash
		uploadData["hash"] = hash
	}

	if execTaskID != "" && s != nil && s.contextState != nil {
		if strings.TrimSpace(ctx.TaskID) == "" {
			ctx.TaskID = execTaskID
		}
		if strings.TrimSpace(ctx.TorrentID) == "" {
			ctx.TorrentID = torrentID
		}
		if strings.TrimSpace(ctx.Name) == "" {
			ctx.Name = name
		}
		if strings.TrimSpace(ctx.Hash) == "" {
			ctx.Hash = hash
		}
		if strings.TrimSpace(ctx.SourceNickname) == "" {
			ctx.SourceNickname = sourceSite
		}
		s.contextState.Set(execTaskID, ctx)
	}

	return execTaskID
}

// notifyScheduledSeedContinue 通知定时发种调度器当前种子无需继续等待，立即处理下一个种子。
// 触发场景：目标站点已存在、预检查限制等确定性跳过。
// 参数/返回：task 为刚完成的队列任务；reason 为跳过原因（用于日志）；无返回值。
// 失败场景：未注入回调或任务非定时发种场景时直接返回。
// 副作用：调用外部回调，可能触发定时发种调度器立即执行。
func (s *MigrateService) notifyScheduledSeedContinue(task repository.PublishQueueTask, reason string) {
	if s == nil || s.publishQueueScheduledSeedContinueHook == nil {
		return
	}
	if strings.TrimSpace(task.Scene) != "scheduled_seeding" {
		return
	}
	trigger := strings.TrimSpace(task.Trigger)
	if trigger == "" {
		return
	}
	logx.Infof(
		publishQueueLogModule,
		"定时发种队列任务跳过发布(%s)，触发继续处理下一种子 queue_task_id=%d trigger=%s torrent_id=%s target_site=%s",
		strings.TrimSpace(reason),
		task.ID,
		trigger,
		strings.TrimSpace(task.TorrentID),
		strings.TrimSpace(task.TargetSite),
	)
	s.publishQueueScheduledSeedContinueHook(trigger)
}

func (s *MigrateService) resolveQueueTaskDownloaderID(task repository.PublishQueueTask, payload map[string]any, ctx publishworkflow.Context) string {
	downloaderID := strings.TrimSpace(task.DownloaderID)
	if downloaderID == "" {
		downloaderID = strings.TrimSpace(processingshared.ToString(payload["downloaderId"], processingshared.ToString(payload["downloader_id"], "")))
	}
	if downloaderID == "" {
		downloaderID = strings.TrimSpace(ctx.DownloaderID)
	}

	root := map[string]any{}
	if s != nil && s.cfg != nil {
		root = s.cfg.Get()
	}
	if crossSeed, ok := root["cross_seed"].(map[string]any); ok && crossSeed != nil {
		if defaultID := strings.TrimSpace(processingshared.ToString(crossSeed["default_downloader"], "")); defaultID != "" {
			return defaultID
		}
	}

	return downloaderID
}

func (s *MigrateService) resolvePublishQueueConfig() publishQueueConfig {
	out := publishQueueConfig{
		Enabled:                     true,
		MaxQueueSize:                1000,
		MaxRetries:                  3,
		MaxRetryDelaySec:            60,
		MaxWorkers:                  1,
		MonitorIntervalSec:          30,
		RetryDelayBase:              2,
		TaskCleanupHours:            24,
		TriggerRecentCountBelow:     15,
		TriggerUploadSpeedBelowMBps: 0,
	}

	root := map[string]any{}
	if s != nil && s.cfg != nil {
		root = s.cfg.Get()
	}
	if root == nil {
		return out
	}
	raw, ok := root["downloader_queue"].(map[string]any)
	if !ok || raw == nil {
		return out
	}

	if value, exists := raw["enabled"]; exists {
		out.Enabled = processingshared.ToBool(value)
	}
	if value, exists := raw["max_queue_size"]; exists {
		if parsed := int64(processingshared.ToFloat(value)); parsed > 0 {
			out.MaxQueueSize = parsed
		}
	}
	if value, exists := raw["max_retries"]; exists {
		if parsed := int(processingshared.ToFloat(value)); parsed >= 0 {
			out.MaxRetries = parsed
		}
	}
	if value, exists := raw["max_retry_delay"]; exists {
		if parsed := int(processingshared.ToFloat(value)); parsed > 0 {
			out.MaxRetryDelaySec = parsed
		}
	}
	if value, exists := raw["max_workers"]; exists {
		if parsed := int(processingshared.ToFloat(value)); parsed > 0 {
			out.MaxWorkers = parsed
		}
	}
	if value, exists := raw["queue_monitor_interval"]; exists {
		if parsed := int(processingshared.ToFloat(value)); parsed > 0 {
			out.MonitorIntervalSec = parsed
		}
	}
	if value, exists := raw["retry_delay_base"]; exists {
		if parsed := int(processingshared.ToFloat(value)); parsed > 0 {
			out.RetryDelayBase = parsed
		}
	}
	if value, exists := raw["task_cleanup_hours"]; exists {
		if parsed := int(processingshared.ToFloat(value)); parsed > 0 {
			out.TaskCleanupHours = parsed
		}
	}
	if value, exists := raw["trigger_recent_count_below"]; exists {
		if parsed := int(processingshared.ToFloat(value)); parsed >= 0 {
			out.TriggerRecentCountBelow = parsed
		}
	}
	if value, exists := raw["trigger_upload_speed_below_mbps"]; exists {
		if parsed := processingshared.ToFloat(value); parsed >= 0 {
			out.TriggerUploadSpeedBelowMBps = parsed
		}
	}

	return out
}

func clampInt(value int, min int, max int) int {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}

func computeBackoffSeconds(base int, attempt int, maxDelay int) int {
	if attempt <= 0 {
		return clampInt(5, 1, maxDelay)
	}
	if base <= 1 {
		return clampInt(attempt*5, 1, maxDelay)
	}

	delay := 1
	for i := 0; i < attempt; i++ {
		delay *= base
		if maxDelay > 0 && delay >= maxDelay {
			return maxDelay
		}
	}
	if delay < 1 {
		delay = 1
	}
	if maxDelay > 0 && delay > maxDelay {
		delay = maxDelay
	}
	return delay
}

func firstNonEmptyString(items ...string) string {
	for _, item := range items {
		trimmed := strings.TrimSpace(item)
		if trimmed != "" {
			return trimmed
		}
	}
	return ""
}

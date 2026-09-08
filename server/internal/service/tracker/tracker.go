package tracker

import (
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/pt-nexus/server/internal/config"
	"github.com/pt-nexus/server/internal/platform/logx"
	"github.com/pt-nexus/server/internal/repository"
	"github.com/pt-nexus/server/internal/service/downloaderclient"
)

const (
	trackerModule                 = "流量采集"
	defaultAggregationIntervalSec = 21600
	defaultRetentionHours         = 48
	defaultFlushPeriodSec         = 60
)

type downloaderConfig struct {
	ID        string
	Name      string
	Type      string
	Host      string
	Username  string
	Password  string
	Enabled   bool
	UseProxy  bool
	ProxyPort int
}

// Service 负责周期性采集下载器速度与累计流量，并批量写入 traffic_stats。
// 参数/返回：由配置管理器提供下载器列表，由仓储层落库并执行小时聚合。
// 失败场景：下载器连接失败、代理不可达或数据库写入异常时仅记录日志，不中断主循环。
// 副作用：持续发起下载器/代理网络请求并写入数据库表 traffic_stats、traffic_stats_hourly。
type Service struct {
	repo *repository.StatsRepository
	cfg  *config.Manager

	startOnce sync.Once
	stopOnce  sync.Once
	stopCh    chan struct{}
	doneCh    chan struct{}

	stateMu          sync.Mutex
	started          bool
	trafficBuffer    []repository.TrafficStatRecord
	lastCumulative   map[string]repository.CumulativeSnapshot
	lastFlushTime    time.Time
	aggregationCount int
}

// New 创建流量采集服务实例。
// 参数/返回：repo 用于写库与聚合，cfg 用于读取运行时下载器配置。
// 失败场景：无直接失败场景，初始化失败在 Start 中记录日志。
// 副作用：无副作用，仅构造内存对象。
func New(repo *repository.StatsRepository, cfg *config.Manager) *Service {
	return &Service{
		repo:           repo,
		cfg:            cfg,
		stopCh:         make(chan struct{}),
		doneCh:         make(chan struct{}),
		trafficBuffer:  make([]repository.TrafficStatRecord, 0),
		lastCumulative: map[string]repository.CumulativeSnapshot{},
		lastFlushTime:  time.Now(),
	}
}

// Start 启动后台采集循环，重复调用只会生效一次。
// 参数/返回：无参数无返回。
// 失败场景：建表或初始快照加载失败时会记录日志并继续运行。
// 副作用：启动 goroutine，开始定时网络采集与数据库写入。
func (s *Service) Start() {
	s.startOnce.Do(func() {
		s.stateMu.Lock()
		s.started = true
		s.stateMu.Unlock()
		go s.run()
	})
}

// Stop 停止后台采集循环并在退出前刷新缓冲区。
// 参数/返回：无参数无返回。
// 失败场景：未启动时直接返回。
// 副作用：关闭停止信号并等待 goroutine 退出。
func (s *Service) Stop() {
	s.stateMu.Lock()
	started := s.started
	s.stateMu.Unlock()
	if !started {
		return
	}

	s.stopOnce.Do(func() {
		close(s.stopCh)
	})
	<-s.doneCh
}

func (s *Service) run() {
	defer close(s.doneCh)

	if err := s.repo.EnsureTrafficStatsTables(); err != nil {
		logx.Errorf(trackerModule, "初始化流量表失败 err=%v", err)
		return
	}

	initialSnapshots, err := s.repo.QueryLatestCumulativeByDownloader()
	if err != nil {
		logx.Warnf(trackerModule, "加载累计流量快照失败 err=%v", err)
	} else {
		s.stateMu.Lock()
		s.lastCumulative = initialSnapshots
		s.stateMu.Unlock()
	}

	intervalSeconds := s.resolveIntervalSeconds()
	batchSize := s.resolveBatchSize(intervalSeconds)
	// logx.Infof(
	// 	trackerModule,
	// 	"采集线程已启动 interval=%ds batch_size=%d aggregation_interval=%ds",
	// 	intervalSeconds,
	// 	batchSize,
	// 	defaultAggregationIntervalSec,
	// )

	ticker := time.NewTicker(time.Duration(intervalSeconds) * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-s.stopCh:
			s.flushBuffer("停止前刷新")
			logx.Infof(trackerModule, "采集线程已停止")
			return
		case <-ticker.C:
			currentInterval := s.resolveIntervalSeconds()
			if currentInterval != intervalSeconds {
				intervalSeconds = currentInterval
				batchSize = s.resolveBatchSize(intervalSeconds)
				ticker.Reset(time.Duration(intervalSeconds) * time.Second)
				logx.Infof(trackerModule, "采集间隔已更新 interval=%ds batch_size=%d", intervalSeconds, batchSize)
			}

			records := s.collectTrafficRecords()
			if len(records) > 0 {
				s.appendRecords(records)
				if s.bufferSize() >= batchSize {
					s.flushBuffer("达到批量阈值")
				}
			}

			if s.shouldPeriodicFlush() {
				s.flushBuffer("达到周期刷新阈值")
			}

			s.aggregationCount += intervalSeconds
			if s.aggregationCount >= defaultAggregationIntervalSec {
				s.aggregationCount = 0
				aggregated, deleted, aggErr := s.repo.AggregateHourlyTraffic(defaultRetentionHours)
				if aggErr != nil {
					logx.Warnf(trackerModule, "小时聚合失败 err=%v", aggErr)
				} else if aggregated > 0 || deleted > 0 {
					logx.Infof(trackerModule, "小时聚合完成 aggregated=%d deleted=%d", aggregated, deleted)
				}
			}
		}
	}
}

func (s *Service) resolveIntervalSeconds() int {
	settings := s.cfg.Get()
	realtimeEnabled := toBool(settings["realtime_speed_enabled"], false)
	if realtimeEnabled {
		return 1
	}
	return 60
}

func (s *Service) resolveBatchSize(intervalSeconds int) int {
	if intervalSeconds <= 0 {
		return 1
	}
	size := defaultFlushPeriodSec / intervalSeconds
	if size <= 0 {
		return 1
	}
	return size
}

func (s *Service) collectTrafficRecords() []repository.TrafficStatRecord {
	settings := s.cfg.Get()
	downloaders := parseEnabledDownloaders(settings)
	if len(downloaders) == 0 {
		return []repository.TrafficStatRecord{}
	}

	currentTime := time.Now()
	records := make([]repository.TrafficStatRecord, 0, len(downloaders))
	for _, downloader := range downloaders {
		stats, err := s.fetchDownloaderStats(downloader)
		if err != nil {
			logx.Warnf(
				trackerModule,
				"采集失败 id=%s name=%s type=%s err=%v",
				downloader.ID,
				downloader.Name,
				downloader.Type,
				err,
			)
			continue
		}

		totalUpload := nonNegative(stats.TotalUpload)
		totalDownload := nonNegative(stats.TotalDownload)
		if totalUpload == 0 && totalDownload == 0 {
			continue
		}
		if !s.shouldAcceptCumulative(downloader.ID, totalUpload, totalDownload) {
			logx.Warnf(
				trackerModule,
				"检测到累计流量回退，已跳过 id=%s name=%s ul=%d dl=%d",
				downloader.ID,
				downloader.Name,
				totalUpload,
				totalDownload,
			)
			continue
		}

		records = append(records, repository.TrafficStatRecord{
			StatDatetime:         currentTime,
			DownloaderID:         downloader.ID,
			Uploaded:             0,
			Downloaded:           0,
			UploadSpeed:          nonNegative(stats.UploadSpeed),
			DownloadSpeed:        nonNegative(stats.DownloadSpeed),
			CumulativeUploaded:   totalUpload,
			CumulativeDownloaded: totalDownload,
		})
	}
	return records
}

func (s *Service) fetchDownloaderStats(d downloaderConfig) (downloaderclient.TrafficStats, error) {
	client := downloaderclient.Downloader{
		ID:       d.ID,
		Name:     d.Name,
		Type:     d.Type,
		Host:     d.Host,
		Username: d.Username,
		Password: d.Password,
		Enabled:  d.Enabled,
	}
	if d.UseProxy && d.Type == "qbittorrent" {
		return client.FetchProxyTrafficStats(d.ProxyPort)
	}
	return client.FetchTrafficStats()
}

func (s *Service) shouldAcceptCumulative(downloaderID string, currentUL, currentDL int64) bool {
	s.stateMu.Lock()
	defer s.stateMu.Unlock()

	last, exists := s.lastCumulative[downloaderID]
	if exists {
		if (currentUL > 0 && currentUL < last.CumulativeUploaded) ||
			(currentDL > 0 && currentDL < last.CumulativeDownloaded) ||
			(currentUL == 0 && last.CumulativeUploaded > 0) ||
			(currentDL == 0 && last.CumulativeDownloaded > 0) {
			return false
		}
	}

	s.lastCumulative[downloaderID] = repository.CumulativeSnapshot{
		CumulativeUploaded:   currentUL,
		CumulativeDownloaded: currentDL,
	}
	return true
}

func (s *Service) appendRecords(records []repository.TrafficStatRecord) {
	if len(records) == 0 {
		return
	}
	s.stateMu.Lock()
	s.trafficBuffer = append(s.trafficBuffer, records...)
	s.stateMu.Unlock()
}

func (s *Service) bufferSize() int {
	s.stateMu.Lock()
	defer s.stateMu.Unlock()
	return len(s.trafficBuffer)
}

func (s *Service) shouldPeriodicFlush() bool {
	s.stateMu.Lock()
	defer s.stateMu.Unlock()
	if len(s.trafficBuffer) == 0 {
		return false
	}
	return time.Since(s.lastFlushTime) >= time.Duration(defaultFlushPeriodSec)*time.Second
}

func (s *Service) flushBuffer(reason string) {
	_ = reason

	s.stateMu.Lock()
	if len(s.trafficBuffer) == 0 {
		s.stateMu.Unlock()
		return
	}
	pending := make([]repository.TrafficStatRecord, len(s.trafficBuffer))
	copy(pending, s.trafficBuffer)
	s.trafficBuffer = s.trafficBuffer[:0]
	s.lastFlushTime = time.Now()
	s.stateMu.Unlock()

	_, err := s.repo.UpsertTrafficStats(pending)
	if err != nil {
		// logx.Errorf(trackerModule, "写入流量数据失败 reason=%s err=%v", reason, err)
		return
	}
	// logx.Infof(trackerModule, "写入流量数据完成 reason=%s count=%d", reason, inserted)
}

func parseEnabledDownloaders(settings map[string]any) []downloaderConfig {
	rawDownloaders := toSlice(settings["downloaders"])
	result := make([]downloaderConfig, 0, len(rawDownloaders))
	for _, raw := range rawDownloaders {
		item := toMap(raw)
		enabled := toBool(item["enabled"], true)
		if !enabled {
			continue
		}

		downloaderID := strings.TrimSpace(toString(item["id"], ""))
		downloaderType := strings.ToLower(strings.TrimSpace(toString(item["type"], "")))
		host := strings.TrimSpace(toString(item["host"], ""))
		if downloaderID == "" || host == "" {
			continue
		}
		if downloaderType != "qbittorrent" && downloaderType != "transmission" {
			continue
		}

		result = append(result, downloaderConfig{
			ID:        downloaderID,
			Name:      toString(item["name"], downloaderID),
			Type:      downloaderType,
			Host:      host,
			Username:  toString(item["username"], ""),
			Password:  toString(item["password"], ""),
			Enabled:   true,
			UseProxy:  toBool(item["use_proxy"], false),
			ProxyPort: toInt(item["proxy_port"], 9090),
		})
	}
	return result
}

func toSlice(value any) []any {
	if value == nil {
		return []any{}
	}
	if typed, ok := value.([]any); ok {
		return typed
	}
	return []any{}
}

func toMap(value any) map[string]any {
	if value == nil {
		return map[string]any{}
	}
	if typed, ok := value.(map[string]any); ok {
		return typed
	}
	return map[string]any{}
}

func toString(value any, fallback string) string {
	switch typed := value.(type) {
	case string:
		trimmed := strings.TrimSpace(typed)
		if trimmed == "" {
			return fallback
		}
		return trimmed
	case nil:
		return fallback
	default:
		trimmed := strings.TrimSpace(fmt.Sprintf("%v", typed))
		if trimmed == "" || trimmed == "<nil>" {
			return fallback
		}
		return trimmed
	}
}

func toBool(value any, fallback bool) bool {
	switch typed := value.(type) {
	case bool:
		return typed
	case string:
		lower := strings.ToLower(strings.TrimSpace(typed))
		if lower == "true" || lower == "1" || lower == "yes" {
			return true
		}
		if lower == "false" || lower == "0" || lower == "no" {
			return false
		}
		return fallback
	default:
		return fallback
	}
}

func toInt(value any, fallback int) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	case string:
		trimmed := strings.TrimSpace(typed)
		if trimmed == "" {
			return fallback
		}
		parsed, err := strconv.Atoi(trimmed)
		if err != nil {
			return fallback
		}
		return parsed
	default:
		return fallback
	}
}

func nonNegative(value int64) int64 {
	if value < 0 {
		return 0
	}
	return value
}
